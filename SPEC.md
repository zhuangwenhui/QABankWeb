# 题库系统 模块开发契约

本文档约束各功能模块的实现,与《题库系统技术文档.md》配套。**所有模块必须严格遵守本契约**,基础层(已完成)不得修改。

## 0. 已完成的基础层(只读,不得修改)

- `app.py` — 应用工厂;页面路由 `/questions` `/error_book` `/feedback` `/overview` `/login` `/logout`;文件服务 `/uploads/<filename>`、`/generated/<filename>`;已注册四个蓝图:`api.questions.bp`、`api.error_book.bp`、`api.feedback.bp`、`api.overview.bp`
- `config.py` — `Config` 类与枚举:`SUBJECTS`(7 门课程)、`DIFFICULTIES`、`PER_PAGE_OPTIONS = [10,20,50,100]`、`FEEDBACK_STATUSES`、`PDF_TEMPLATES = ['custom_exam_template', '试卷模板', 'error_book_template']`
- `models.py` — `db`、`User`、`Question`(含 `tags_list` 属性与 `to_dict()`)、`ErrorBook`(含 `to_dict()`,内嵌 question)、`Feedback`(含 `to_dict()`)、`ViewLog`
- `auth.py` — `login_required`、`admin_required` 装饰器(API 路径下返回 JSON 401/403);CSRF 已由全局 before_request 校验,前端需在请求头带 `X-CSRFToken`(`apiFetch` 已自动处理)
- `templates/base.html` — 固定顶部导航、flash 消息、MathJax 3(含 boldsymbol)、Bootstrap 5.1.3、FA6;子模板可用块:`{% block title %}`、`{% block head %}`、`{% block content %}`、`{% block scripts %}`
- `static/js/utils.js` — `apiFetch(url, opts)`(自动 CSRF/JSON,失败抛 Error)、`buildQuery(params)`、`escapeHtml`、`debounce`、`typesetMath(el)`、`difficultyBadge(d)`、`tagBadges(tags)`、`formatDate(s)`
- `static/js/toast.js` — `showToast(message, type)`,type: success|danger|warning|info
- `static/css/style.css` — 全部公共样式类(见 §4)

模板中可直接使用的 Jinja 全局变量:`current_user`、`csrf_token`、`SUBJECTS`、`DIFFICULTIES`、`PER_PAGE_OPTIONS`、`PDF_TEMPLATES`。

## 1. 统一响应格式

所有 `/api/` 接口返回 JSON:

```json
成功: { "success": true, "data": {...}, "message": "可选提示" }
失败: { "success": false, "error": "人类可读错误", "code": "机器可读错误码" }  + 恰当的 HTTP 状态码
```

蓝图定义模式(以 questions 为例):

```python
from flask import Blueprint
bp = Blueprint('api_questions', __name__, url_prefix='/api')
```

注意:四个蓝图的 Blueprint 第一参数(名称)必须互不相同,分别为 `api_questions`、`api_error_book`、`api_feedback`、`api_overview`。error_book 蓝图的 url_prefix 为 `/api/error_book`(但 `check_batch` 等见下文精确路径)。

`Question.to_dict()` 返回字段:`id, subject, chapter, difficulty, source, tags(数组), question_latex, question_image(文件名), question_image_url, solution_latex, solution_image, solution_image_url, created_at('YYYY-MM-DD HH:MM:SS')`。

## 2. 接口契约

### 2.1 题目模块(api/questions.py,蓝图名 api_questions,url_prefix='/api')

全部需要 `login_required`。

| 路由 | 方法 | 请求 | 响应 data |
|---|---|---|---|
| `/api/questions` | GET | query: subject, chapter, difficulty, source(模糊), search(对 question_latex/solution_latex/source/chapter 模糊), questionId, tagFilter(逗号分隔,含任一即命中), dateFrom, dateTo(YYYY-MM-DD,含当天), page(默认1), per_page(默认20,限 10/20/50/100) | `{questions: [to_dict...], total, page, per_page, pages}` |
| `/api/questions` | POST | JSON: subject(必填,须在 SUBJECTS 内), chapter, difficulty(须在 DIFFICULTIES 内), source, tags(数组), question_latex, solution_latex, question_image, solution_image | `{question: to_dict}`,message='创建成功' |
| `/api/questions/<int:qid>` | GET | — | `{question: to_dict}` |
| `/api/questions/<int:qid>` | PUT | JSON 同 POST(部分字段可省略,省略则不改) | `{question: to_dict}` |
| `/api/questions/<int:qid>` | DELETE | — | message='删除成功'(同时清理其错题本关联、查看日志由级联处理;删除关联图片文件) |
| `/api/questions/batch_delete` | POST | `{ids: [int]}` | `{deleted: n}` |
| `/api/questions/batch_update_tags` | POST | `{ids: [int], tags: [str], mode: 'replace'\|'add'}` | `{updated: n}` |
| `/api/questions/batch_update_source` | POST | `{ids: [int], source: str}` | `{updated: n}` |
| `/api/questions/filters` | GET | query: subject(可选,联动章节) | `{chapters: [str], sources: [str], tags: [str]}`(去重排序,供筛选下拉) |
| `/api/source_exists` | GET | query: source, exclude_id(可选) | `{exists: bool}` |
| `/api/log_view_question` | POST | `{question_id: int}` | message='ok'(写 ViewLog,user 取 g.user) |
| `/api/upload_question_image` | POST | multipart 字段 `file`;仅允许 config 中扩展名(image/* 与 pdf) | `{filename, url: '/uploads/<filename>'}`(存储名用 `uuid4().hex + 扩展名`,保存到 `Config.UPLOAD_FOLDER`) |
| `/api/delete_question_image` | POST | `{filename}` | message='已删除'(用 `os.path.basename` 防路径穿越;文件不存在也返回成功;不自动清空引用它的题目字段,由调用方在保存题目时处理) |

筛选实现注意:tags 存 JSON 字符串,tagFilter 用 `Question.tags.like(f'%"{tag}"%')` 匹配即可;分页用 `query.paginate(page=..., per_page=..., error_out=False)`。

### 2.2 错题本模块(api/error_book.py,蓝图名 api_error_book)

全部 `login_required`,数据均限定 `user_id = g.user.id`。精确路径:

| 路由 | 方法 | 请求 | 响应 data |
|---|---|---|---|
| `/api/error_book` | GET | query: subject, chapter, difficulty, source, search, page, per_page | `{entries: [ErrorBook.to_dict...], total, page, per_page, pages}` |
| `/api/error_book/add` | POST | `{question_id, notes?}` | message='已加入错题本';已存在则 success=true + message='已在错题本中' |
| `/api/error_book/add_batch` | POST | `{question_ids: [int]}` | `{added: n, skipped: n}` |
| `/api/error_book/remove` | POST | `{question_id}` 或 `{question_ids: [int]}`(两种都要支持) | `{removed: n}` |
| `/api/error_book/check_batch` | POST | `{question_ids: [int]}` | `{in_error_book: [question_id...]}` |
| `/api/error_book/update_notes` | POST | `{question_id, notes}` | message='备注已保存' |
| `/api/error_book/stats` | GET | — | `{total: int, by_subject: {课程名: 数量}}` |
| `/api/error_book/generate_pdf` | POST | `{title, subtitle, exam_date, subject, duration, total_score, notice, template, question_ids?(缺省=当前用户全部错题,按筛选可传), include_solutions: bool}` | 成功:`{pdf_url: '/generated/xx.pdf', filename}`;LaTeX 引擎缺失时:success=true 但 data 含 `{tex_url: '/generated/xx.tex', filename, engine_missing: true}` + message 说明仅生成 .tex 源文件 |

### 2.3 PDF 生成(pdf_gen.py,项目根)

```python
def generate_pdf(template_name, context, questions, output_basename) -> dict
# 返回 {'ok': bool, 'pdf_path' 或 'tex_path', 'engine_missing': bool, 'error': str|None}
```

- 模板位于 `Config.LATEX_TEMPLATE_FOLDER` 下 `<template_name>.tex`,template_name 必须在 `config.PDF_TEMPLATES` 白名单内(防任意文件读取)
- 模板中的占位符用 `((KEY))` 形式(避免与 LaTeX 花括号冲突):`((TITLE)) ((SUBTITLE)) ((EXAM_DATE)) ((SUBJECT)) ((DURATION)) ((TOTAL_SCORE)) ((NOTICE)) ((QUESTIONS))`
- 需实现 `escape_latex(text)` 处理用户输入的标题等字段(转义 `# $ % & _ { } ~ ^ \`);题目 LaTeX 内容原样注入
- `((QUESTIONS))` 注入为 `\item` 列表或 `\section*{第 n 题}` 块;`include_solutions` 为真时在每题后加解答区块
- 编译:`shutil.which('xelatex')` → `shutil.which('pdflatex')` 依次探测;有引擎则在 `Config.GENERATED_PDF_FOLDER` 内用 `subprocess.run([...,'-interaction=nonstopmode','-halt-on-error', tex], cwd=输出目录, timeout=60)` 编译两遍;无引擎或编译失败则保留 .tex 并在返回中说明(编译失败时 error 带上日志尾部 30 行)
- 输出文件名:`output_basename + '.pdf'/'.tex'`,basename 由调用方生成(`uuid4().hex[:12]`),不含用户输入
- 三套模板都必须是完整可编译的 xelatex 文档(`\documentclass{ctexart}` 或 article+CJK,假定 Noto Serif CJK 字体存在):`custom_exam_template.tex`(正式试卷版式:大标题、考试信息表、注意事项框)、`试卷模板.tex`(简洁版式)、`error_book_template.tex`(错题整理版式:含"我的备注"栏,题目备注通过 questions 注入时一并渲染)

### 2.4 反馈模块(api/feedback.py,蓝图名 api_feedback,url_prefix='/api/feedback')

| 路由 | 方法 | 权限 | 请求 | 响应 data |
|---|---|---|---|---|
| `/api/feedback` | GET | login;学生只看自己的,管理员看全部 | query: status(全部/待处理/已处理,'全部'或空=不过滤) | `{feedbacks: [to_dict...], counts: {全部: n, 待处理: n, 已处理: n}}`(counts 按可见范围统计) |
| `/api/feedback` | POST | login | `{title(必填), content}` | `{feedback: to_dict}` |
| `/api/feedback/<int:fid>/status` | POST | admin | `{status, reply?}` | `{feedback: to_dict}` |
| `/api/feedback/<int:fid>` | DELETE | 本人或 admin | — | message='已删除' |

### 2.5 总览模块(api/overview.py,蓝图名 api_overview,url_prefix='/api/overview')

`admin_required`。

| 路由 | 方法 | 响应 data |
|---|---|---|
| `/api/overview/stats` | GET | `{question_total, user_total, error_book_total, feedback_pending, by_subject: {课程: 题数}, by_difficulty: {难度: 题数}, views_last_14_days: [{date: 'MM-DD', count}...], top_viewed: [{id, subject, source, count}...前10], error_by_subject: {课程: 错题数(全体用户)}, recent_questions: [to_dict...最近5条]}` |

## 3. 页面契约

三个页面模板都 `{% extends 'base.html' %}`,页首放面包屑:

```html
<div class="breadcrumb-container">
  <div class="breadcrumb-custom">
    <a href="/questions"><i class="fa-solid fa-house"></i> 首页</a>
    <span class="breadcrumb-separator">/</span>
    <span>题目管理</span>
  </div>
</div>
```

页面脚本放独立文件 `static/js/<页面>.js`(不要写巨型内联脚本,这是文档 §9.1 的改进要求),模板 `{% block scripts %}` 中引入。需要向 JS 传递的服务端常量用一个小的内联 `<script>window.PAGE_CONFIG = {...}</script>` 传递(如科目列表)。

### 3.1 题目管理页(templates/questions.html + static/js/questions.js + api/questions.py)

功能(文档 §6.1 全部):

- **视图切换**:表格视图(`question-table`,列:选择框/编号/课程/章节/难度/来源/标签/题目预览/操作)与卡片视图(`question-card-view` 网格,卡片 `question-card-item`);用 `view-toggle`/`view-toggle-btn` 按钮组切换,状态存 localStorage
- **基础筛选**:课程(下拉,固定 7 门)、章节(下拉,根据课程从 `/api/questions/filters` 联动加载)、难度、来源(文本)、关键词;变更即刷新(关键词 debounce 400ms)
- **高级搜索**(可折叠面板):题目 ID、标签筛选(逗号分隔)、创建时间范围 dateFrom/dateTo;"搜索/重置"按钮
- **搜索增强**:每次执行搜索把条件存入 localStorage 搜索历史(最多 20 条,去重),提供历史下拉可回放;"保存为预设"给预设起名保存(localStorage),预设列表可加载/删除
- **分页**:Bootstrap 分页组件 + 每页条数选择(10/20/50/100)
- **批量操作**:全选/单选(选中行/卡片加 `selected` 类);选中后显示 `batch-toolbar`(显示选中数、批量删除、批量编辑标签、批量修改来源、批量加入错题本、取消选择);批量弹窗用 Bootstrap Modal
- **题目详情**:点击题目公式区打开详情 Modal,五个区块:题目信息(编号/课程/章节/难度/来源/标签/创建时间)、题目内容(MathJax 渲染)、题目图片、解答内容(默认折叠,"查看答案"按钮展开)、解答图片;打开时 POST `/api/log_view_question`
- **书签**:每题右上角书签图标(`bookmark-btn`,已收藏加 `bookmarked`);列表渲染后 POST `/api/error_book/check_batch` 批量回填状态;点击切换 add/remove
- **右键菜单**:题目卡片/行上 contextmenu 弹出自定义菜单(`context-menu` 样式已有):查看详情、编辑、加入/移出错题本、复制题目 LaTeX、删除
- **新建/编辑弹窗**:全字段表单(课程、章节、难度、来源、标签、题目 LaTeX、解答 LaTeX、题目图片、解答图片);LaTeX 编辑用 CodeMirror 5.65.2(CDN:`https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.2/` 下的 `codemirror.min.css`、`codemirror.min.js`、`mode/stex/stex.min.js`,在本页 `{% block head %}/{% block scripts %}` 引入),stex 模式,编辑时 debounce 500ms 在 `latex-preview` 区实时 MathJax 预览;来源输入失焦时调 `/api/source_exists` 判重提示(编辑时传 exclude_id);图片上传用 `/api/upload_question_image`(接受 image/*,application/pdf;上传后显示缩略图/PDF 链接,可删除→调 `/api/delete_question_image`);保存后刷新列表
- 渲染列表后务必调用 `typesetMath(容器)`;所有用户内容经 `escapeHtml`(LaTeX 原文除外——LaTeX 直接放入 `latex-content` 让 MathJax 渲染,但仍需先 escapeHtml 再插入,MathJax 处理的是文本层,`$...$` 定界符不受 HTML 转义影响)

### 3.2 错题本页(templates/error_book.html + static/js/error_book.js + api/error_book.py + pdf_gen.py + latex_templates/)

- 顶部统计:总错题数 + 按科目分布(`stat-card` 行 + 徽章列表)
- 筛选:课程/章节/难度/来源/关键词(同题库维度)
- 列表:卡片式(`question-card`),含题目内容(MathJax)、难度、来源、标签、加入时间、备注区(可内联编辑保存→`update_notes`)、操作(快速预览 Modal、移出)
- 批量:全选/多选,批量移出
- **PDF 生成**(核心):"生成 PDF 试卷"按钮打开配置 Modal:试卷标题、副标题、考试日期(date input)、科目、考试时间(分钟)、总分、注意事项(textarea)、模板选择(下拉,选项来自 `PDF_TEMPLATES`)、是否包含解答、范围(全部错题/当前筛选结果/勾选题目);确认后 POST `generate_pdf`,按钮 loading 态;成功给出下载链接(pdf 或 tex),`engine_missing` 时用 warning toast 说明服务器未装 LaTeX、已生成 .tex 源文件

### 3.3 反馈页(templates/feedback.html + static/js/feedback.js + api/feedback.py)

- "提交反馈"表单(标题+内容)
- 工单列表:状态筛选 tab(全部/待处理/已处理,带计数徽章)+ 重置筛选按钮;每条显示标题、内容、状态徽章(待处理黄/已处理绿)、时间、提交人(管理员视角)、管理员回复(若有)
- 管理员:每条可"标记已处理/待处理"并填写回复;删除
- 学生:可删除自己的反馈

### 3.4 总览页(templates/overview.html + static/js/overview.js + api/overview.py)

管理侧仪表盘:顶部 4 张 `stat-card`(题目总数/用户数/错题总数/待处理反馈);按课程题数分布(进度条或纯 CSS 柱状)、难度分布;近 14 天查看趋势(纯 CSS/SVG 柱状图,不引入图表库);最常查看题目 Top10 表格;全体用户错题按科目分布;最近新增题目列表。

## 4. 公共样式类(style.css 已提供,直接使用)

`main-content` `content-area` `breadcrumb-container` `breadcrumb-custom` `breadcrumb-separator` `question-card` `question-card-view` `question-card-item` `question-table` `latex-code` `latex-content` `latex-preview` `difficulty-badge`(配 `difficulty-easy/medium/hard`,用 `difficultyBadge()` 生成) `batch-toolbar` `view-toggle` `view-toggle-btn` `selected` `flash-messages` `tag-badge` `bookmark-btn`(`bookmarked`) `context-menu`(`context-menu-item`) `stat-card`(`stat-value` `stat-label`) `image-preview-thumb` `question-detail-image`

页面级补充样式写在各自模板的 `{% block head %}` 内的小型 `<style>` 中(≤60 行),不修改公共 css。

## 5. 编码规范

- Python:每个接口用 try/except 包裹数据库写操作,异常时 `db.session.rollback()` 并返回统一错误格式;输入校验失败返回 400 + code='INVALID_INPUT'
- JS:原生 ES6+,不引入框架;函数注释;避免全局散落——每页用一个立即执行的模块模式或 `document.addEventListener('DOMContentLoaded', init)` 组织
- 所有面向用户的文案用中文
