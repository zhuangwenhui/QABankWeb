# 题库系统

面向大学院入学考试备考的理工科题库管理系统。以 LaTeX 存储和渲染数学公式,支持错题本管理与 LaTeX 试卷 PDF 生成。依据《题库系统技术文档.md》实现。

## 功能

- **题目管理**(`/questions`,默认首页):表格/卡片双视图;课程、章节、难度、来源、关键词筛选;高级搜索(题目 ID、标签、创建时间范围);搜索历史与筛选预设;批量删除/编辑标签/修改来源/加入错题本;题目详情弹窗(记录查看日志);书签一键加入/移出错题本;右键上下文菜单;新建/编辑弹窗(CodeMirror LaTeX 编辑器 + MathJax 实时预览 + 来源判重 + 题目/解答图片上传,支持 image/* 与 PDF)
- **错题本**(`/error_book`):与题库一致的筛选维度;备注编辑;批量移出;总数与科目分布统计;**PDF 试卷生成**(标题/副标题/考试日期/科目/时长/总分/注意事项 + 三套 `.tex` 模板可选)
- **意见反馈**(`/feedback`):提交工单;按状态筛选(全部/待处理/已处理);管理员处理与回复
- **总览**(`/overview`,管理员):题库统计、查看趋势、Top 常看题目、错题分布(学生访问自动重定向到题目管理)
- **登录安全**:图片验证码(服务端 Pillow 栅格化,点击刷新、大小写不敏感、一次性)+ 登录限流(同一 IP/用户名 5 分钟内失败 5 次锁定 15 分钟),抵御脚本爬取与暴力破解

## 技术栈

- 后端:Python Flask + Flask-SQLAlchemy(SQLite),同源 Session 认证 + CSRF 保护
- 前端:服务端渲染 MPA;Bootstrap 5.1.3、Font Awesome 6、MathJax 3(boldsymbol 扩展)、CodeMirror 5.65.2(stex),均走 CDN
- 页面脚本按功能域拆分为独立模块文件(`static/js/questions.js` 等),非巨型内联脚本
- PDF:服务端 LaTeX 编译(xelatex/pdflatex 自动探测)

## 快速开始

```bash
cd question-bank

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt          # 生产依赖(锁定版本)
.venv/bin/pip install -r requirements-dev.txt      # 开发/测试(可选)
.venv/bin/flask --app app db upgrade               # 初始化/升级数据库 schema
.venv/bin/python seed.py                           # (可选)首次灌入开发演示数据(空库直接跑)
# 重置已有数据需显式 --force 防误清:.venv/bin/python seed.py --drop --force
.venv/bin/python app.py                            # 开发服务器
# 访问 http://127.0.0.1:5000
```

演示账号(**仅限本地开发 `seed.py` 灌入的数据,生产环境不适用**):

| 账号 | 密码 | 角色 |
|---|---|---|
| `admin` | `admin123` | 管理员(可访问总览、处理反馈) |
| `student` | `student123` | 学生 |

> 生产环境不运行 `seed.py`,因此不存在上表这两个弱口令账号。生产环境请用
> `flask --app app create-admin <用户名>` 引导创建管理员(首次登录会强制改密),
> 详见 [docs/ops/deploy.md](docs/ops/deploy.md) 与 [docs/ops/launch-checklist.md](docs/ops/launch-checklist.md)。

## 生产部署

生产环境请勿使用 `python app.py`(开发服务器)。完整流程见
[docs/ops/deploy.md](docs/ops/deploy.md)(gunicorn + systemd + Nginx + TLS + 备份),
上线前逐项核对 [docs/ops/launch-checklist.md](docs/ops/launch-checklist.md)。
最小形态:`APP_ENV=production SECRET_KEY=<强随机> .venv/bin/gunicorn -w 2 -k gthread --threads 4 -b 127.0.0.1:8000 app:app`

## PDF 生成说明

生成试卷依赖 LaTeX 引擎。服务器会按 `xelatex → pdflatex` 顺序探测:

- 已安装:直接编译产出 PDF(中文试卷推荐 `xelatex`,需 CJK 字体,如 Noto Serif CJK)
- 未安装:自动降级为生成 `.tex` 源文件供下载,可在本地或 Overleaf 编译

Ubuntu 安装参考:`sudo apt install texlive-xetex texlive-lang-chinese fonts-noto-cjk`

三套模板位于 `latex_templates/`:`custom_exam_template.tex`(正式试卷)、`试卷模板.tex`(简洁版)、`error_book_template.tex`(错题整理,含备注栏)。

## 项目结构

```
question-bank/
├── app.py               # 应用入口:页面路由、蓝图注册、CSRF、文件服务
├── config.py            # 配置与固定枚举(课程/难度/模板白名单)
├── models.py            # User / Question / ErrorBook / Feedback / ViewLog
├── auth.py              # login_required / admin_required / CSRF 校验
├── seed.py              # 演示数据(7 门课程真实 LaTeX 例题)
├── pdf_gen.py           # LaTeX → PDF 编译(引擎探测、模板渲染、降级)
├── api/                 # JSON 接口蓝图
│   ├── questions.py     #   题目查询/CRUD/批量/筛选项/判重/图片上传
│   ├── error_book.py    #   错题本增删查/备注/统计/PDF 生成
│   ├── feedback.py      #   反馈工单
│   └── overview.py      #   管理统计
├── templates/           # Jinja2 页面模板
├── static/              # css / js(utils、toast、各页面模块)
├── latex_templates/     # 三套 .tex 试卷模板
├── uploads/             # 题目/解答图片(uuid 重命名)
├── generated_pdfs/      # 生成的试卷 PDF/.tex
├── instance/            # SQLite 数据库
└── SPEC.md              # 接口与页面契约文档(前后端解耦依据)
```

## 接口一览

所有接口位于 `/api/` 下,需登录会话 + `X-CSRFToken` 请求头,统一响应格式
`{success, data, message}` / `{success: false, error, code}`。完整契约(参数、响应结构、权限)见 [SPEC.md](SPEC.md)。

## 测试

```bash
.venv/bin/python -m pytest tests/ -q                        # 全量测试
.venv/bin/python -m pytest tests/test_auth_captcha.py -q    # 仅登录验证码 + 限流
```

## 安全说明

- 登录带**图片验证码**([captcha.py](captcha.py))与**限流锁定**([ratelimit.py](ratelimit.py));验证码答案在会话中仅存 HMAC 摘要(不落明文,防机器人读取自身 Cookie),一次性使用
- 限流为进程内实现,适合单进程自托管;多 worker/多实例生产应改用 Redis + Flask-Limiter,并配 `ProxyFix` 以取到真实客户端 IP
- 生产部署前请通过环境变量 `SECRET_KEY` 设置强随机密钥
- 上传文件按扩展名白名单校验并以 UUID 重命名;文件服务与模板名均做路径穿越防护
- PDF 模板名走白名单,LaTeX 编译子进程带超时
- 更全面的生产就绪度评估见 [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md)(审计报告)
