# 生产就绪度评估报告(Production Readiness Assessment)

> 被审计对象:题库系统(Flask + Flask-SQLAlchemy/SQLite + Jinja2 服务端渲染 + Bootstrap5/MathJax)
> 审计范围:`app.py` / `config.py` / `models.py` / `auth.py` / `pdf_gen.py` / `ratelimit.py` / `captcha.py` / `seed.py` / `api/*` / `static/js/*` / `templates/*` / `latex_templates/*` 及 `SPEC.md`、`README.md`、技术文档
> 报告日期:2026-07-06
> 说明:登录页正在并行新增【图片验证码 + 登录限流/锁定】(`captcha.py`、`ratelimit.py` 已落地),本报告**不**将"缺验证码/无登录限流/无防暴破"列为发现。

---

## 一、总体评价

**成熟度定位:功能完整、单人自托管的高质量原型(Well-crafted single-tenant prototype),尚未达到"多用户企业级生产"标准。**

代码本身写得相当克制、规范:应用工厂 + 蓝图分层、统一 JSON 响应契约、自研 CSRF、全程 ORM 参数化查询、`LIKE` 通配符转义、`next` 跳转白名单校验、LaTeX 编译已做 `-no-shell-escape` + `openin_any/openout_any=p` 沙箱、上传扩展名白名单(明确排除 SVG)、`SECRET_KEY` 走环境变量注入且拒绝硬编码回退——这些都体现了明显高于"玩具项目"的安全与工程意识。

但它距离企业级生产仍有**结构性差距**,集中在四条主线:

1. **部署形态**:仍以 `app.run(debug=True)` 开发服务器对外提供服务(`app.py:200`),`debug` 硬编码为 `True`——这是**同时命中安全(Werkzeug 调试器 RCE)与可靠性(单进程无并发)的最高危缺陷**,必须在上生产前解决。
2. **持久化根基**:SQLite 未开 WAL/busy_timeout、未开外键约束、无迁移框架(启动即 `create_all()`);多用户并发写会 `database is locked`,schema 演进会丢数据。
3. **运维可观测性**:无日志系统配置、无请求日志、无安全审计日志、无健康检查、无错误追踪/指标、无容器化与 CI。故障"看不见、查不到、报不出"。
4. **重负载路径**:LaTeX 编译在请求线程内同步阻塞(最坏 120s),可被几个并发请求打满全部 worker,单点拖垮整站。

值得强调:这些差距**几乎全部是"生产化配置与运维基建"的缺失,而非业务逻辑或核心安全模型的错误**。补齐 P0/P1 清单后,该系统具备成为稳健小规模生产服务的底子。

### 成熟度评分表(1–5,5 为企业级就绪)

| 维度 | 评分 | 一句话理由 |
|---|:---:|---|
| **安全性** | **3 / 5** | 核心防护到位(CSRF、参数化、LaTeX 沙箱、SECRET_KEY 环境注入、验证码/限流在补),但 `debug=True` RCE、全站零安全响应头、Cookie 未设 Secure/SameSite、无审计日志把分数压低。 |
| **数据模型与持久化** | **2 / 5** | 模型清晰、有唯一约束与索引,但 SQLite 未开 WAL/外键、无迁移框架、tags/source/chapter 建模欠规范、存在 N+1,均为生产硬伤。 |
| **可靠性 / 健壮性** | **2 / 5** | 错误处理有分流意识,但同步阻塞式 PDF 编译可拖垮整站,生成物永不清理会写满磁盘,`create_all()` 无迁移。 |
| **可观测性 / 部署运维** | **1 / 5** | 几乎为零:无日志配置、无请求/审计日志、无健康检查、无 Sentry/Prometheus、无 Docker/CI、无 ProxyFix、依赖未锁定。 |
| **测试 / 工程化 / 可维护性** | **2 / 5** | 已有一份验证码/限流测试(`tests/test_auth_captcha.py`)难能可贵,但无 lint/format/类型检查/CI,`questions.js` 1313 行巨型脚本,依赖仅 `>=` 浮动。 |
| **前端质量 / 性能 / 可访问性** | **2.5 / 5** | 转义防护做得较好,但全量 CDN 无 SRI、无 CSP、多处对比度不达 WCAG AA、无 lazy-load、无前端错误上报。 |

---

## 二、分维度发现

> 严重度徽章:🔴 High(上生产前必须处理) / 🟠 Medium(短中期修复) / 🟡 Low(择机优化)
> 工作量:S(<0.5 天) / M(0.5–2 天) / L(>2 天)
> 相近/重复的原始发现已在下方合并为单条,并汇总证据。

---

### A. 安全性(Security)

#### A1. 🔴 生产以 `app.run(debug=True)` 开发服务器运行,Werkzeug 交互式调试器可致 RCE 【工作量 M】

- **问题**:`app.py:196-200` 末尾 `app.run(host=host, port=port, debug=True)`,`debug` 硬编码为 `True` 且无环境变量开关;`README.md:33` 以 `.venv/bin/python app.py` 作为运行方式。全仓无 gunicorn/uwsgi/waitress/Dockerfile/Procfile。
- **代码证据**:
  ```python
  # app.py:200
  app.run(host=host, port=port, debug=True)
  ```
- **生产后果**:`debug=True` 下任一触发未捕获异常的请求都会返回 Werkzeug 交互式调试器,其 PIN 保护可被绕过/爆破,进而在服务器上执行任意 Python(RCE),并回显完整堆栈泄露源码与环境;同时该模式会架空 `@app.errorhandler(500)`。开发服务器本身单进程、无并发、无请求超时,任一慢请求(如 60s LaTeX 编译)即阻塞整个进程。
- **改进建议**:`debug` 改由环境变量控制并默认 `False`(`debug=os.environ.get('FLASK_DEBUG')=='1'`);生产用 `gunicorn -w 4 -k gthread 'app:app'`(`app.py:194` 已在模块级导出 `app`,可直接作 WSGI 入口)+ 前置 Nginx 做 TLS 终止与静态文件;补 `@app.errorhandler(Exception)` 兜底。
- **对应标准**:OWASP Top 10:2021 A05 Security Misconfiguration;Flask "Deploying to Production";Gunicorn "Design"。

#### A2. 🔴 全站缺少安全响应头(CSP / HSTS / X-Frame-Options / X-Content-Type-Options / Referrer-Policy)【工作量 M】

- **问题**:全仓 `grep` 安全头相关键为空(`after_request`、`Talisman`、`Content-Security-Policy`、`X-Frame-Options`、`Strict-Transport-Security`、`X-Content-Type-Options` 均无命中);`base.html` 仅有 `meta viewport/csrf`。
- **生产后果**:①无 `X-Frame-Options`/`frame-ancestors` → 可被任意站点 iframe 嵌套,点击劫持;②无 CSP → 前端大量手工 `innerHTML` 拼接(`error_book.js`/`feedback.js`/`overview.js`),虽普遍用了 `escapeHtml`,但任一处遗漏即 XSS 无纵深防御,且从 `cdn.jsdelivr.net`/`cdnjs` 加载 Bootstrap/MathJax/FontAwesome 却无 CSP 亦无 SRI,CDN 被投毒即全站脚本注入;③无 `nosniff` → `/uploads` 文件存在 MIME 嗅探风险;④无 HSTS。
- **改进建议**:引入 **Flask-Talisman** 一次性下发 CSP、HSTS、`X-Frame-Options=SAMEORIGIN`、`X-Content-Type-Options=nosniff`、Referrer-Policy;为支持严格 CSP,需把 `base.html` 的内联 MathJax 配置与 `PAGE_CONFIG` 改为 nonce 或外部文件(当前 6 个模板均含内联 `<script>`)。
- **对应标准**:OWASP Top 10:2021 A05;OWASP Secure Headers Project;Flask-Talisman。

#### A3. 🟠 Session Cookie 未设 Secure/SameSite,且永久会话回退到 31 天默认过期 【工作量 S】

- **问题**:`config.Config` 无任何 `SESSION_COOKIE_SECURE/HTTPONLY/SAMESITE` 与 `PERMANENT_SESSION_LIFETIME`(全仓无命中);`app.py:113` 登录后 `session.permanent = True` 但未配 `PERMANENT_SESSION_LIFETIME`,Flask 默认 31 天。Werkzeug 默认 `HttpOnly=True` 但 `Secure=False`、`SameSite=None`。
- **生产后果**:①Secure 未开 → 明文信道下会话 Cookie 可被中间人窃取;②SameSite 未设 → 削弱对 CSRF 的纵深防御(目前仅靠自研单层 token);③31 天不失效 → 被盗 Cookie 长期有效、无空闲超时。
- **改进建议**:`Config` 显式设 `SESSION_COOKIE_SECURE=True`(生产)、`HTTPONLY=True`、`SAMESITE='Lax'`,并设 `PERMANENT_SESSION_LIFETIME=timedelta(hours=12)`;可随 Flask-Talisman 一并完成。
- **对应标准**:OWASP ASVS 3.4.1/3.4.2/3.4.3、3.3.2;Flask Security Considerations。

#### A4. 🟠 无任何安全审计日志(登录成功/失败、越权 401/403、题库删除均不记录)【工作量 M】

- **问题**:登录成功/失败仅 `flash` 给用户;`current_app.logger` 仅在 `except` 分支记异常;`ratelimit` 触发锁定也无日志。全仓无"谁在何时从哪个 IP 登录/删除/触发 403"的记录。
- **生产后果**:暴力破解、越权尝试、恶意批量删除题库等事件发生后无审计轨迹可检测、告警与取证,无法满足 A09;也无法定位是哪个账号删了数据。
- **改进建议**:为登录成功/失败(含用户名 + `remote_addr`)、访问控制拒绝、题库删除/批量删除、反馈删除补结构化审计日志(JSON:`user_id/ip/action/target`)输出到 stdout;**切勿**记录密码、会话 token、验证码答案(CWE-532)。
- **对应标准**:OWASP Top 10:2021 A09;ASVS V7。

#### A5. 🟡 seed 内置弱默认口令 `admin/admin123`、`student/student123`,且系统无改密/注册入口 【工作量 M】

- **问题**:`seed.py:404-406` 硬编码创建 admin/student 弱口令并 `print` 到控制台(`seed.py:451`);`models.set_password` 无长度/复杂度校验;全仓无 register/change_password 路由。
- **生产后果**:文档中即写明的弱口令是凭据填充/暴破首要目标,admin 一旦被猜中即完全接管;因无改密功能,部署者若不手工改库,默认口令长期有效。(注:密码算法本身 werkzeug 默认 scrypt 达标,问题在口令强度与生命周期。)
- **改进建议**:移除硬编码口令,改为首次启动从环境变量注入或随机生成并强制首登改密;`set_password` 加最小长度(≥12)与复杂度校验;提供改密入口。
- **对应标准**:OWASP A07;OWASP Password Storage / Authentication Cheat Sheet。

#### A6. 🟡 生成 PDF/tex 走可枚举命名空间提供,登录用户间存在弱 IDOR 【工作量 M】

- **问题**:`/generated/<path:filename>`(`app.py:165-168`)仅 `@login_required`、不校验文件归属;错题本 PDF 含用户私有错题与备注,文件名为 `uuid4().hex[:12]`(约 48 bit)。任一登录用户访问 `/generated/<basename>.pdf` 即可下载。
- **生产后果**:学生若获知/猜中他人 basename 即可下载其错题本 PDF(含私有备注),构成越权信息泄露。48 bit 随机使在线枚举不现实,故风险较低;但"登录即可下任意人 PDF"的授权模型不满足按对象归属的访问控制,且文件无生命周期管理(见 C2)。
- **改进建议**:为生成文件记录 owner 并在下载时校验归属,或改为一次性签名令牌下载;配合过期清理。
- **对应标准**:OWASP A01 Broken Access Control(IDOR)。

---

### B. 数据模型与持久化(Data & Persistence)

#### B1. 🔴 SQLite 未启用外键约束(`PRAGMA foreign_keys` 默认 OFF),ForeignKey 与级联形同虚设 【工作量 S】

- **问题**:`models.py` 大量声明 `db.ForeignKey(...)` 与 `cascade='all, delete-orphan'`(`24-26/56-59/100-101/119/144-145`),但全仓无 `PRAGMA`/`event.listen`/`connect_args`;`config.py:25` 为裸 SQLite URI,无 connect 钩子。SQLite 默认每连接 `foreign_keys=OFF`,必须每次连接显式打开。
- **生产后果**:数据库层不强制引用完整性。ORM 侧删除依赖 relationship 级联,但底层 `DELETE`(如 `.delete(synchronize_session=False)`、任何外部脚本或直连 SQL)不会触发外键 `ON DELETE`,可产生指向已删题目/用户的孤儿 ErrorBook/ViewLog/Feedback,一致性得不到 DB 兜底。
- **改进建议**:用 `event.listen(Engine, 'connect', ...)` 在每个连接上执行 `PRAGMA foreign_keys=ON`;或迁移到 PostgreSQL(外键默认强制)。
- **对应标准**:SQLite 官方 Foreign Key Support;OWASP A03(数据完整性);12factor-db 要点 13–14。

#### B2. 🔴 无数据库迁移方案:启动即 `create_all()`,schema 变更只能 drop 重建、生产改表即丢数据 【工作量 M】

- **问题**:`app.py:188-189` 在 `create_app()` 内 `db.create_all()`,每次启动执行;`requirements.txt` 无 flask-migrate/alembic;全仓无 `migrations/`。`create_all()` 只建不存在的表、对已存在表不做任何 `ALTER`;改列只能靠 `seed.py --drop` 清空全库重建。
- **生产后果**:任何 schema 演进(加字段/改列宽/加约束)都无法在保留数据下完成:要么不生效(代码与库结构漂移,新字段读写 `OperationalError`),要么 drop 重建导致题库/错题本/用户/日志全丢;无版本化即无法回滚、无法审计变更、多实例滚动发布结构不一致。
- **改进建议**:引入 **Flask-Migrate**(封装 Alembic,4.0+ 对 SQLite 默认 `render_as_batch=True` + `compare_type=True`),`flask db init/migrate/upgrade`;把 `flask db upgrade` 作为部署管线中应用启动前的独立幂等步骤,从启动逻辑移除 `create_all()`;autogenerate 脚本人工 review。
- **对应标准**:12factor-db 要点 9/11/12;Flask-Migrate 官方文档。

#### B3. 🔴 SQLite 单写者 + 未配 WAL/busy_timeout,多用户并发写将频繁 `database is locked` 【工作量 M】

- **问题**:`config.py:25` 裸 SQLite URI,无 `SQLALCHEMY_ENGINE_OPTIONS`、无 `journal_mode=WAL`、无 `busy_timeout`(全仓无命中)。写路径密集:每次看题都 `INSERT ViewLog`(`api/questions.py:527`),另有错题增删、批量加标签/改来源、反馈提交等。SQLite 全局写锁,同一时刻仅一个写者。
- **生产后果**:多学生并发(尤其高频 ViewLog 写入)或 gunicorn 多 worker 下,写事务命中全局写锁,默认无 `busy_timeout` 时立即抛 `SQLITE_BUSY`/`database is locked`,请求 500;无重试,用户直接看到失败。
- **改进建议**:短期——`SQLALCHEMY_ENGINE_OPTIONS` + connect 事件里 `PRAGMA journal_mode=WAL; busy_timeout=5000; synchronous=NORMAL`,写事务短小化 + 忙时有限重试,ViewLog 这类高频写考虑批量/异步落库;中长期——多进程/多实例或数据增长时迁移到 **PostgreSQL**(配 `pool_pre_ping`/`pool_recycle`)。
- **对应标准**:12factor-db 要点 5/6/13/14;SQLite File Locking And Concurrency;SQLAlchemy Connection Pooling。

#### B4. 🟠 `ErrorBook.to_dict` 内嵌 question 触发 N+1 查询,错题列表与 PDF 生成随规模线性放大 【工作量 S】

- **问题**:`models.py:111` `'question': self.question.to_dict()`,Question 侧 backref 未指定 eager loading;`api/error_book.py` 的 `list_entries`(`117-165`)虽 `join` 但仅用于过滤(非 `contains_eager`),分页后 `[e.to_dict() ...]` 逐条 SELECT question;`generate_pdf`(`382-388`)取全部错题后逐个访问 `entry.question` 同样 N+1。全仓无 `joinedload/selectinload/contains_eager/options(`。
- **生产后果**:错题列表每页 100 条 → 1 次分页 + 100 次单题查询;PDF 生成遍历用户全部错题(可达数百条)每题一条 SELECT。规模增长后列表与导出接口延迟明显上升。
- **改进建议**:查询加 `.options(selectinload(ErrorBook.question))`(把 N+1 降为 2 条),或对 `list_entries` 用 `contains_eager(ErrorBook.question)` 复用已有 join;开发期开启 `record_queries`/SQL echo 主动发现。
- **对应标准**:12factor-db 要点 15;SQLAlchemy Relationship Loading Techniques。

#### B5. 🟠 `tags` 以 JSON 字符串存储,筛选靠 `LIKE '%"tag"%'` 子串匹配,无法索引、有误命中风险、无标签统计 【工作量 L】

- **问题**:`models.py:49` `tags = db.Column(db.Text, default='[]')`;`api/questions.py:242` `Question.tags.like(f'%"{_escape_like(t)}"%')`;`question_filters`(`458+`)需全量拉回 `chapter/source/tags` 到 Python 侧 `json.loads` 去重才能列出可选标签。
- **生产后果**:①tags 列无法建有效索引,筛选是全表 LIKE 扫描;②`%"tag"%` 子串匹配存在边界误命中;③标签管理/重命名/频次统计只能应用层遍历,无法 SQL 聚合。(技术文档 §9.3 已指出。)
- **改进建议**:规范化为关联表——`tags(id, name unique)` + `question_tags` 多对多联结表,筛选/统计走 JOIN + GROUP BY,`name` 建唯一索引。
- **对应标准**:技术文档 §9.3;12factor-db(规范化与可索引查询)。

#### B6. 🟠 `chapter` 字段混用"知识点章节"与"考试年份"两种语义,无法按年份检索/统计 【工作量 M】

- **问题**:`models.py:45-46` 注释明说 `chapter` 同时承载知识点(如"1 変数関数の微分法")与年份(2008–2021);`seed.py` 中同列既有 `'2019'` 又有 `'行列式与逆矩阵'`。筛选把 `chapter` 当单一维度匹配。
- **生产后果**:无法可靠"按年份区间筛选"或做年份维度统计(用户在 `FEEDBACK_ITEMS` 中已明确提此需求),因年份与知识点挤在同列、类型不可区分;章节字典下拉会把两者混排。
- **改进建议**:拆分独立字段——新增 `exam_year`(Integer, nullable, index),`chapter` 只承载知识点;迁移时按内容(纯数字→年份)回填,配合 Flask-Migrate。
- **对应标准**:技术文档 §9.3。

#### B7. 🟡 `source` 无字典表,自由文本重复存储,判重与统计脆弱 【工作量 M】

- **问题**:`source = db.String(128)` 自由文本,每题独立存储;`source_exists`(`api/questions.py:496+`)用精确 `==` 判重,`batch_update_source` 整批覆盖字符串。无来源字典表。
- **生产后果**:同一来源因空格/全半角/年份写法差异被视为不同值,精确判重易漏判,来源维度统计不可靠;重命名需全表更新字符串。
- **改进建议**:建 `sources(id, name unique)` 字典表,`Question.source_id` 外键引用;判重与统计走 JOIN。可先落最小字典表,不必一次做机构/年份拆分。
- **对应标准**:技术文档 §9.3。

---

### C. 可靠性 / 错误处理 / 健壮性(Reliability)

#### C1. 🔴 PDF 编译在请求线程内同步阻塞,可耗尽 worker、拖垮整站 【工作量 L】

- **问题**:`pdf_gen.py:212-215` 在 HTTP 请求线程内 `for _ in range(2): subprocess.run(cmd, timeout=COMPILE_TIMEOUT)`,`COMPILE_TIMEOUT=60` → 单请求最坏阻塞约 120s;`api/error_book.py:346` 的 `generate_pdf_route` 直接调用并等待。技术文档 §9.4 亦记载该风险并建议引入异步任务队列。
- **生产后果**:gunicorn 4 worker 下,只要 4 个用户同时点"生成试卷"或题量大导致编译慢,worker 全被占满,期间登录/题库浏览/错题本全部排队甚至超时;恶意用户连续触发编译即构成 DoS。
- **改进建议**:把编译放入异步任务队列(**Celery/RQ + Redis**):接口立即返回 `job_id`,前端轮询 `/status` 获取进度与结果 URL;同一 (模板+题目集+参数) 结果缓存复用。若坚持单机,至少用独立进程池执行并对并发编译数设信号量上限。
- **对应标准**:技术文档 §9.4;flask-prod 第 1 条(WSGI + worker 隔离阻塞任务);ops-test 异步任务惯例。

#### C2. 🟠 生成的 `.tex`/`.pdf` 永不清理,磁盘持续增长直至写满 【工作量 M】

- **问题**:每次生成写出 `<basename>.tex` 与 `<basename>.pdf`,成功后仅 `_cleanup_aux`(`pdf_gen.py:116-123`)删 `.aux/.log/.out/.toc`,`.tex`/`.pdf` 被有意保留(注释:"保留 .tex 与 .pdf")。全仓无对 `generated_pdfs/` 的 TTL/定时/LRU 清理。(`uploads/` 有孤儿清理,生成目录没有。)
- **生产后果**:`generated_pdfs/` 无限膨胀最终写满磁盘;磁盘满后 PDF 生成、SQLite 写入(WAL/journal)、日志、上传全部报错,整站进入不可写状态——典型"慢性资源泄漏致宕机";历史 PDF 长期滞留还叠加 A6 的信息泄露面。
- **改进建议**:①下载后即删/流式返回临时文件;或②APScheduler/cron 按 mtime 清理超 N 小时文件;或③写入带自动过期的对象存储。至少给目录设配额并在写入前检查可用空间。
- **对应标准**:12factor-db Disposability;ops-test 资源治理。

#### C3. 🟡 LaTeX 编译超时/失败时残留半成品 `.pdf` 与 `.tex`,叠加无清理放大磁盘泄漏 【工作量 S】

- **问题**:两遍编译第一遍可能已生成不完整 `.pdf`;超时分支(`pdf_gen.py:218-221`)与失败分支(`226-230`)只调 `_cleanup_aux`,不删 `<basename>.pdf`/`.tex`;`error_book.py` 对失败仅回错误码、不回收 basename 文件。
- **生产后果**:每次超时/失败可能留下孤儿 `.tex`(及个别半成品 `.pdf`),与 C2 叠加加速磁盘增长;半成品 `.pdf` 若被猜到 basename 还可能被下载到损坏文件。
- **改进建议**:失败/超时分支一并删除 `<basename>.pdf` 与 `.tex`;或统一改为"成功才落盘、失败即清空该 basename 全部产物",配合 C2 的目录级 TTL 双保险。
- **对应标准**:12factor-db Disposability;技术文档 §9.4。

#### C4. 🟡 `413` 处理器一律返回 JSON,浏览器表单上传场景体验错乱 【工作量 S】

- **问题**:`app.py:178-180` 的 `@app.errorhandler(413)` 直接 `jsonify`,而 404/500 已按 `request.path.startswith('/api/')` 分流。`MAX_CONTENT_LENGTH=20MB` 超限即触发。
- **生产后果**:非 `/api` 的浏览器直传或未来新增表单上传时,用户会看到裸 JSON 而非友好页面;错误格式不一致增加前端处理复杂度。
- **改进建议**:与 404/500 一致按 `/api/` 分流;更彻底地把"API vs 页面"分流抽成 helper 统一所有 errorhandler。
- **对应标准**:flask-prod 第 9 条(统一错误处理)。

---

### D. 可观测性 / 部署 / 运维(Observability & Ops)

#### D1. 🔴 无日志系统配置:`current_app.logger` 被用但从未配置 handler/level/格式 【工作量 M】

- **问题**:各 API 蓝图有 20+ 处 `current_app.logger.exception/warning`,但全仓无 `basicConfig/dictConfig/StreamHandler/setLevel/addHandler/Formatter`;`create_app()` 无任何日志初始化。
- **生产后果**:以 gunicorn(非 debug)运行时 Flask 默认 logger 仅在 WARNING+ 用非结构化格式输出到 stderr,INFO 级业务事件全部丢失,无 request_id/时间戳/级别的机器可解析结构,故障时无法按请求聚合排障,也无法接入 ELK/Splunk/Cloud Logging。
- **改进建议**:`create_app()` 中用 `logging.dictConfig` 统一配置:输出到 **stdout**(12-Factor XI),生产用 JSON 结构化(`structlog`/`python-json-logger`,含 ISO8601 时间戳/level/logger),开发用彩色可读;级别按环境从配置读取。
- **对应标准**:12-Factor XI;Flask 官方 Logging;structlog Best Practices。

#### D2. 🔴 生产入口无 dev/prod 配置分离,单一 `Config` 类且缺安全 Cookie/会话时长 【工作量 M】

> 与 A1(部署形态)、A3(Cookie 标志)互补:此处聚焦"配置分层"这一根因。

- **问题**:`config.py` 只有一个 `class Config`,无 Production/Development/Testing 继承;`app.py:24` `from_object(config.Config)` 固定加载;安全 Cookie/会话时长全缺(见 A3)。
- **生产后果**:无法按环境切换配置(生产/开发/测试同一套),`debug=True`、明文 Cookie、31 天会话等生产不安全默认值容易被误用带上线。
- **改进建议**:拆 `Config` 基类 + `DevelopmentConfig/ProductionConfig/TestingConfig`,`APP_ENV` 选择,`from_prefixed_env()` 注入敏感值;生产类显式设安全 Cookie 与 `PERMANENT_SESSION_LIFETIME`。
- **对应标准**:Flask Configuration Handling;12-Factor III;ASVS 3.3/3.4;OWASP A05。

#### D3. 🟠 无请求/访问日志,无 request_id,缺失可观测性基线 【工作量 M】

- **问题**:`@app.before_request` 只做 CSRF 与用户加载,无 `after_request` 记录 method/path/status/耗时/用户;全仓无 request_id/trace_id。切到 gunicorn 后 access log 需显式配置,当前无。
- **生产后果**:无法回答"谁在何时访问了什么、响应多少、耗时多久";登录失败、越权、慢查询(总览统计、PDF 生成)均无请求维度记录,安全与性能问题都难追溯,无法接 APM。
- **改进建议**:`after_request` 记结构化访问日志;`before_request` 生成 request_id 并用日志上下文绑定;gunicorn 侧 `--access-logfile -`。**勿写密码/session/PII**(CWE-532)。
- **对应标准**:12-Factor XI;OWASP A09;structlog context binding。

#### D4. 🟠 依赖仅用 `>=` 浮动约束,无锁文件、无哈希、无 CVE 扫描 【工作量 S】

- **问题**:`requirements.txt` 三行全 `>=`(`flask>=3.0` / `flask-sqlalchemy>=3.1` / `Pillow>=10.0`),无上限、无精确版本、无哈希;无 `poetry.lock`/`uv.lock`/`pip-compile` 产物。实际装的是 Flask 3.1.x、SQLAlchemy 2.0.x、Pillow 12.x,与下限差距大且不可复现;Werkzeug/Jinja2 等传递依赖完全未列。另:`api/overview.py:75` 仍硬编码 `Feedback.status == '待处理'`,而 `config.FEEDBACK_STATUSES` 已集中定义;角色 `'admin'/'student'` 字面量散落。
- **生产后果**:不同机器/时间 `pip install` 解析出不同版本,构建不可复现;上游不兼容或含 CVE 的新版会被自动引入(Pillow 历史多次有图像解析 CVE,而本项目用 Pillow 渲染验证码);无哈希无法校验供应链完整性;魔法字符串散落使新增角色/状态时易漏改一处导致权限/统计静默错乱。
- **改进建议**:改用 `pip-compile`(`requirements.in` → 带 pinned 版本 + 哈希)或 uv/Poetry 锁定完整依赖树;CI 接 `pip-audit`/Dependabot;把角色抽为常量/Enum 全局引用,`overview.py` 的 `'待处理'` 换 `config.FEEDBACK_STATUSES`。
- **对应标准**:OWASP A06;12-Factor I;PEP 751;ops-test 要点 6。

#### D5. 🟠 缺 ProxyFix:反向代理后 `remote_addr` 取到代理 IP,污染登录限流的 IP 维度 【工作量 S】

- **问题**:`create_app()` 未用 `werkzeug.middleware.proxy_fix.ProxyFix` 包裹;而 `app.py:87` 用 `request.remote_addr` 作登录限流 IP key。生产部署 Nginx/LB 后 `remote_addr` 会是代理固定内网 IP。
- **生产后果**:所有真实客户端被折叠成同一代理 IP:①单个恶意客户端的失败会连累全体正常用户被按 IP 锁定(自造 DoS);②不同真实 IP 的暴破共享同一计数无法区分;③`url_for(_external=True)` 与 HTTPS 判定也会出错。
- **改进建议**:按可信代理层数 `app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)`,Nginx 侧设 `proxy_set_header X-Forwarded-For/Proto`;限流 IP key 改用修正后的 `remote_addr`。
- **对应标准**:Flask "Tell Flask it is Behind a Proxy";Werkzeug ProxyFix;OWASP A07。

#### D6. 🟠 无健康检查/就绪探针端点 【工作量 S】

- **问题**:路由表只有业务页面与需登录的文件服务;无 `/healthz`/`/readyz`。所有页面路由被登录/权限装饰器保护,LB 无法免鉴权探活。
- **生产后果**:上 K8s/LB/systemd 时无轻量免鉴权端点判定进程存活(liveness)与依赖就绪(readiness,如 DB 连通),故障实例不能被自动摘除/重启,滚动发布缺就绪判断。
- **改进建议**:加免鉴权、低开销、不写日志噪声的 `/healthz`(仅进程存活)与 `/readyz`(执行 `SELECT 1` 检查 DB);确保不被 `login_required`/CSRF 拦截。
- **对应标准**:Kubernetes Liveness/Readiness 惯例;flask-prod 健康检查要点。

#### D7. 🟠 无错误追踪(Sentry)与运行指标(Prometheus)接入 【工作量 M】

- **问题**:全仓无 `sentry-sdk`/`prometheus_client`;`server_error`(`app.py:182-186`)只返回文案不上报;无 `/metrics`。
- **生产后果**:生产异常只落本地日志、无实时告警,故障发现靠人工翻日志;无请求量/延迟/错误率指标,无法建 SLO、无法用 Grafana 做容量与性能监控,也难及时发现 PDF 编译、DB 查询等高开销路径劣化。
- **改进建议**:接入 **Sentry**(`sentry_sdk.init + FlaskIntegration`)做异常聚合告警;用 `prometheus-flask-exporter` 暴露 `/metrics` 接 Prometheus+Grafana。
- **对应标准**:ops-test(Sentry/Prometheus);OWASP A09。

#### D8. 🟠 无容器化(Dockerfile)与 CI/CD 流水线 【工作量 L】

- **问题**:全仓无 Dockerfile/docker-compose/`.github`/`.gitlab-ci`/Procfile;无 lint/typecheck/test 自动化流水线;`requirements.txt` 无质量工具(pytest/ruff/mypy)。
- **生产后果**:部署全手工(venv + `python app.py`),环境不可复现、难横向扩容与滚动发布;无 CI 即每次改动无自动化门禁,回归风险高;无标准化镜像制品导致"在我机器上能跑"。
- **改进建议**:加多阶段 Dockerfile(最小基础镜像、非 root、含 `HEALTHCHECK`、gunicorn 作 CMD);加 GitHub Actions:依赖→ruff lint/format→(可选 mypy)→pytest 带覆盖率门禁(`--cov-fail-under`),矩阵测 3.11/3.12。
- **对应标准**:12-Factor(build/release/run);Docker Best Practices;pytest-cov;Real Python CI/CD。

---

### E. 测试 / 工程化 / 可维护性(Testing & Engineering)

> 客观补充:项目已有 `tests/test_auth_captcha.py`(验证码 + 限流,8 项,用内存库隔离),这是明显的工程化亮点;下列发现针对"覆盖面/工具链"的缺口,而非"零测试"。

#### E1. 🟠 `questions.js` 单文件 1313 行、73 个函数塞进单个 IIFE,无模块化与构建 【工作量 L】

- **问题**:`static/js/questions.js` 1313 行(全前端 JS 合计 2600 行,该文件占一半),职责跨 13 个分区,73 个函数全定义在一个 IIFE 内,无 ES module、无 import/export。技术文档 §9.1 已列为高优先。
- **生产后果**:单文件职责过多,改一处易牵动全局;函数封闭在 IIFE 内无法被单测独立引用;无法代码分割/按需加载;新人定位成本高,是所有前端改进的瓶颈。
- **改进建议**:按功能域拆 ES modules(filters/render/batch/bookmark/detail/editor),用 import/export 组织;引入 **Vite/esbuild** 打包压缩;对纯逻辑函数补 Vitest/Jest 单测。
- **对应标准**:flask-prod/ops-test(模块化与构建);技术文档 §9.1。

#### E2. 🟠 前端无构建/打包/压缩流程,静态资源原样交付 【工作量 M】

- **问题**:无 `package.json`/Vite/webpack;`static/js/` 7 个文件均未压缩源码,由 `base.html` 以多个独立 `<script src>` 逐一引入。技术文档 §9.1 建议引入构建工具。
- **生产后果**:无压缩/合并 → 传输体积偏大、请求数偏多、首屏慢;无 tree-shaking 与 hash 文件名 → 缓存失效控制粗糙;无 sourcemap → 生产排障困难。
- **改进建议**:引入 Vite/esbuild:生产 build 产出带 content-hash 的压缩 bundle 与 sourcemap,模板改引 manifest,构建纳入 CI。
- **对应标准**:ops-test 要点 8;技术文档 §9.1。

#### E3. 🟠 关键前端依赖全部 CDN 引入,无本地托管、无 SRI、无失败回退 【工作量 M】

> 与 A2(CSP)同源,此处从"供应链完整性 + 离线可用"角度独立记录。

- **问题**:`base.html:8/9/26/100` 从 `cdn.jsdelivr.net`/`cdnjs` 引 Bootstrap 5.1.3/MathJax 3/Font Awesome 6;`questions.html:6/384/385` 引 CodeMirror 5.65.2。全仓 `integrity=`/`crossorigin=` 零命中,无本地副本回退。技术文档 §9.6 已列改进项。
- **生产后果**:离线/内网自托管场景 CDN 不可达即整站样式与公式渲染失效(自托管备考工具却强依赖公网);无 SRI → CDN 被投毒/中间人篡改会静默加载被篡改脚本、可窃取会话 Cookie/CSRF token(A08);CDN 抖动直接拖慢首屏。CodeMirror 有降级到 textarea,但 Bootstrap/MathJax 无任何回退。
- **改进建议**:下载到 `static/vendor/` 本地自托管并锁版本,用 `url_for('static', ...)` 引用;若保留 CDN 必须加 `integrity="sha384-..."` + `crossorigin`,并提供 `onerror` 本地回退。
- **对应标准**:OWASP A08;SubResource Integrity (SRI) W3C;技术文档 §9.6。

#### E4. 🟡 无 lint/format/pre-commit 工具链 【工作量 M】

- **问题**:全仓无 `pyproject.toml`/`.ruff.toml`/`.flake8`/`.pre-commit-config.yaml`;`.vscode/` 仅设解释器路径。代码风格靠人工维持(`api/questions.py` 与 `api/error_book.py` 各自复制了一份 `_escape_like`/`_ok`/`_err`)。
- **生产后果**:无统一格式与静态检查,长期积累风格漂移、未用导入、裸 `except`、shadowing 等隐患;多人协作 diff 噪声大、review 成本高;"本地过 CI 红"无法提交前拦截。
- **改进建议**:引入 **ruff**(同时 lint + format)配置写入 `pyproject.toml`;`.pre-commit-config.yaml` 挂 `ruff-pre-commit` 的 check 与 format;CI 与本地共用同一配置。
- **对应标准**:ops-test 要点 5;flask-prod(代码质量)。

#### E5. 🟡 全代码库零类型注解,无 mypy 静态类型检查 【工作量 L】

- **问题**:约 99 个函数定义中带参数/返回类型注解者近乎为 0(仅 `pdf_gen.py` 有零星);函数间数据契约仅靠 docstring 与阅读实现推断。无 mypy 配置。
- **生产后果**:IDE 与静态分析无法在编译期发现类型误用(如把 `None` 传给期望 `str` 的转义函数、字典键拼写错误),只能运行时暴露;契约不明显著拖慢新维护者上手与安全重构。
- **改进建议**:为公共边界(api 处理函数入参出参、`pdf_gen`/`ratelimit`/`captcha` 公开函数、`models.to_dict`)逐步补注解;引入 mypy 并在 CI 运行,先宽松后收紧;可结合 pydantic/marshmallow 为请求体建 schema 顺带获类型。
- **对应标准**:ops-test 要点 4。

#### E6. 🟡 README 缺生产运维手册(仅开发快速启动)【工作量 S】

- **问题**:`README.md` "快速开始"教的是 `.venv/bin/python app.py` 跑开发服务器;未列 Gunicorn/反向代理/ProxyFix、环境变量清单(仅一句提 `SECRET_KEY`)、`/healthz`、结构化日志、备份/回滚/迁移步骤。
- **生产后果**:接手者无法据文档把系统安全拉到生产,易误用 `debug=True` 内置服务器上线;缺健康检查与日志规范使可观测性差;缺环境变量与迁移手册,部署与升级易出错。
- **改进建议**:补运维章节——Gunicorn+Nginx 部署命令与 worker 计算、ProxyFix 配置、环境变量表、`/healthz`/`/readyz`、结构化日志到 stdout、SQLite 备份与(引入 Flask-Migrate 后的)迁移步骤、回滚触发条件。
- **对应标准**:flask-prod 要点 1/9/10/12;engineering documentation(runbook)。

---

### F. 前端质量 / 性能 / 可访问性(Frontend Quality)

#### F1. 🟠 多处 UI 文本对比度低于 WCAG AA 4.5:1 【工作量 M】

- **问题**:`static/css/style.css:53/231` 与 `overview.html:38/46/47`、`feedback.html:24`、`questions.html:15`、`error_book.html:20` 用 `#adb5bd`(约 2.0:1)、`#98a1ab`(约 3.0:1)、`#8b939c`(约 3.1:1)灰字于白底,承载日期/来源/提交人/分布计数等**有意义信息**,低于 AA 正文 4.5:1;CSS 无 `prefers-reduced-motion`/`prefers-color-scheme`。
- **生产后果**:低视力用户与强光/低质屏用户难以阅读元信息;趋势图日期(0.7rem + `#98a1ab`)几乎不可读;无法通过无障碍合规审查(若面向学校/机构推广)。
- **改进建议**:承载信息的灰字统一提升到至少 `#6c757d`(约 4.6:1)或更深;纯装饰分隔符可保留浅色但补非颜色区分;用 axe DevTools/Lighthouse 跑对比度审计。
- **对应标准**:WCAG 2.1 SC 1.4.3 Contrast (Minimum) AA。

#### F2. 🟡 搜索历史与筛选预设仅存 localStorage,未绑定账户,跨设备不同步且同浏览器他人可见 【工作量 M】

- **问题**:`static/js/questions.js:30-34` 定义 `LS_KEYS`(viewMode/history/presets),`renderHistoryMenu/recordHistory/saveCurrentPreset` 全走 localStorage,键名不含 user_id,后端无对应存储。
- **生产后果**:换设备/清缓存即全丢(技术文档 §9.5 跨设备不同步),对多设备长期备考体验差;共用同一浏览器的不同人能看到彼此搜索历史(轻微隐私泄漏)。
- **改进建议**:为搜索历史/筛选预设新增后端表(user_id 外键 + JSON)与 REST 接口,前端改读写服务端,localStorage 仅作离线兜底;视图模式偏好可保留在 localStorage(设备级合理)。
- **对应标准**:ASVS V8;12-Factor(状态在后端);技术文档 §9.5。

#### F3. 🟡 无前端错误上报,也无全局 `error`/`unhandledrejection` 捕获 【工作量 M】

- **问题**:`static/js/app.js` 仅处理 flash 淡出;全站无 `window.onerror`/`addEventListener('error')`/`unhandledrejection`/Sentry;异常仅散落 `console.warn/error`(8 处)或 `showToast`。
- **生产后果**:MathJax 渲染失败、`apiFetch` 抛错、CDN 加载失败导致的运行时 TypeError,运维侧完全无感知;用户白屏/功能失效时无线上错误数据可排查——这是 A09 在前端的体现。
- **改进建议**:最简加 `window.addEventListener('error'/'unhandledrejection', ...)` 把错误 POST 到后端 `/api/client_error` 落结构化日志;规模化接前端 Sentry;散落 `console.warn` 关键错误统一上报。
- **对应标准**:OWASP A09;structlog/Sentry 前端最佳实践。

#### F4. 🟡 首屏加载重型渲染/编辑器库,无按需加载 【工作量 M】

- **问题**:MathJax `tex-svg.js`(数百 KB)在 `base.html:26` 对每个页面(含无公式的 overview/feedback)加载;`questions.html:384-385` 同步加载 CodeMirror 主库 + stex 模式(即便用户从不点新建/编辑);内容图片无 `loading="lazy"`、无 width/height。
- **生产后果**:MathJax 全站付出下载解析成本;CodeMirror 对只读用户是纯浪费首屏字节;图片无 lazy-load 与固有尺寸 → 长列表一次性加载 + 布局抖动(CLS);移动端弱网首屏明显变慢。
- **改进建议**:MathJax 仅在含公式页加载或 IntersectionObserver 触发;CodeMirror 改点击新建/编辑时 `import()`;内容图片加 `loading="lazy" decoding="async"` 并给容器固定宽高避免 CLS;用 Lighthouse 量化。
- **对应标准**:Web Vitals(LCP/CLS);MDN `loading=lazy`。

#### F5. 🟡 纯 CSS 趋势柱状图无可访问的数据表征;缺 favicon/manifest 【工作量 S】(两项低频合并)

- **问题**:`overview.html:23-38` + `overview.js:96-115` 的趋势图仅靠柱高 + `title` + 可视文本呈现,无 `role="img"`/`aria-label`/等价数据表;`.progress` 分布条无 `aria-valuenow`。`base.html` `<head>` 无 favicon/manifest/theme-color,浏览器对 `/favicon.ico` 发一次 404。
- **生产后果**:屏幕阅读器用户无法从趋势图/分布条获得信息(管理总览为决策页);标签页无图标观感不专业 + 一次 favicon 404 噪声 + 缺移动端"添加到主屏幕"体验。
- **改进建议**:趋势图容器加 `role="img"` + 概括 `aria-label` 或 visually-hidden 等价 `<table>`,progress 补 `role="progressbar"`;添加 favicon + apple-touch-icon,可选 `manifest.webmanifest` + `theme-color`。
- **对应标准**:WCAG 2.1 SC 1.1.1;ARIA 图表实践;PWA/Web App Manifest MDN。

---

## 三、改进路线图(分阶段 Checklist)

> 每项标注工作量与对应上文编号。P0 = 上生产前必须完成;P1 = 短期(上线后 2–4 周);P2 = 中期(对应技术文档 §9 改进方向);P3 = 长期。

### P0 — 上生产前必须做(阻断上线)

- [ ] **关 debug + 换 WSGI 承载**:`debug` 从环境变量读取默认 False;用 `gunicorn -w 4 -k gthread 'app:app'` + Nginx;补 `@app.errorhandler(Exception)` 兜底。〔A1 / M〕
- [ ] **下发安全响应头**:引入 Flask-Talisman 配 CSP/HSTS/X-Frame-Options/nosniff/Referrer-Policy(内联脚本先改 nonce/外置)。〔A2 / M〕
- [ ] **安全 Cookie + 会话时长 + 配置分层**:拆 dev/prod Config,生产设 `SESSION_COOKIE_SECURE/HTTPONLY/SAMESITE` 与 `PERMANENT_SESSION_LIFETIME=12h`。〔A3 / D2 / S–M〕
- [ ] **开启 SQLite 外键 + WAL + busy_timeout**:connect 事件里 `PRAGMA foreign_keys=ON; journal_mode=WAL; busy_timeout=5000; synchronous=NORMAL`。〔B1 / B3 / S–M〕
- [ ] **引入迁移框架**:接入 Flask-Migrate,从启动逻辑移除 `create_all()`,`flask db upgrade` 作为部署管线独立步骤。〔B2 / M〕
- [ ] **配置日志系统**:`create_app()` 用 `dictConfig` 输出 JSON 到 stdout(含时间戳/level/request_id)。〔D1 / M〕
- [ ] **PDF 编译移出请求线程**:至少加进程池 + 并发信号量上限;更彻底走 Celery/RQ 异步队列。〔C1 / L〕
- [ ] **移除硬编码默认口令**:改环境变量注入/随机生成 + 强制首登改密。〔A5 / M〕

### P1 — 短期(上线后尽快)

- [ ] 请求日志 + request_id + 安全审计日志(登录/越权/删除)。〔D3 / A4 / M〕
- [ ] ProxyFix 包裹 + Nginx X-Forwarded 头;限流 IP key 用修正后的 remote_addr。〔D5 / S〕
- [ ] `/healthz` + `/readyz` 免鉴权探针。〔D6 / S〕
- [ ] 依赖锁定(pip-compile/uv,带哈希)+ pip-audit/Dependabot;消除 `待处理`/角色魔法字符串。〔D4 / S〕
- [ ] 生成物生命周期管理:下载即删或定时 TTL 清理 + 磁盘配额;失败/超时分支清理半成品。〔C2 / C3 / M〕
- [ ] Dockerfile(多阶段/非 root/HEALTHCHECK)+ GitHub Actions(ruff + pytest 覆盖率门禁)。〔D8 / L〕
- [ ] Sentry 错误追踪 + `/metrics`(prometheus-flask-exporter)。〔D7 / M〕
- [ ] 消除 `ErrorBook` N+1(`selectinload`/`contains_eager`)。〔B4 / S〕
- [ ] `413` 处理器按 API/页面分流。〔C4 / S〕
- [ ] 补 README 生产运维手册。〔E6 / S〕

### P2 — 中期(呼应技术文档 §9)

- [ ] **前端模块化 + 构建**:拆 `questions.js` 为 ES modules,引入 Vite/esbuild 打包压缩(§9.1)。〔E1 / E2 / L–M〕
- [ ] **前端依赖本地化 + SRI**:Bootstrap/MathJax/FontAwesome/CodeMirror 自托管或加 SRI(§9.6)。〔E3 / M〕
- [ ] **数据模型规范化**:`tags` 关联表、`chapter` 拆 `exam_year`、`source` 字典表(§9.3)。〔B5 / B6 / B7 / L〕
- [ ] **搜索历史/预设后端化**:新增用户维度表 + REST 接口(§9.5)。〔F2 / M〕
- [ ] lint/format/pre-commit(ruff)全量落地。〔E4 / M〕
- [ ] WCAG AA 对比度整改 + 图表 ARIA。〔F1 / F5 / M〕
- [ ] 前端错误上报(`error`/`unhandledrejection` → 后端/Sentry)。〔F3 / M〕
- [ ] 首屏按需加载(MathJax/CodeMirror 懒加载,图片 lazy-load)。〔F4 / M〕

### P3 — 长期(规模化)

- [ ] **迁移到 PostgreSQL**:当出现多进程/多实例并发写、数据超几 GB、需真正并发能力时;配 `pool_pre_ping`/`pool_recycle`,引入 PgBouncer。〔B3 延伸 / L〕
- [ ] 补全类型注解 + mypy 进 CI,渐进收紧。〔E5 / L〕
- [ ] 扩展测试覆盖(在现有 captcha/限流测试基础上覆盖 api/权限/PDF/迁移),CI 设覆盖率 ratchet。〔E 主题延伸 / L〕
- [ ] PDF 生成结果缓存 + `/generated` 下载 owner 校验/一次性签名令牌。〔A6 / C1 延伸 / M〕

---

## 四、已经做得好的地方(客观优点)

审计中确认以下工程与安全实践**已到位且质量良好**,是该项目高于普通原型的基础,值得保留:

1. **应用工厂 + 蓝图分层**:`create_app()` 模块级导出 `app`,`api/{questions,error_book,feedback,overview}` 按业务域分蓝图——直接可作 WSGI 入口,结构清晰。
2. **统一 JSON 响应契约**:`_ok`/`_err` 统一 `{success, data/error, code}`,404/500 已按 `/api/` 分流,前后端契约稳定。
3. **CSRF 防护**:`csrf_protect()` 对所有非安全方法校验 header/表单双通道 token,登录成功 `session.clear()` 防会话固定。
4. **全程参数化查询 + LIKE 转义**:全部走 SQLAlchemy ORM,无字符串拼 SQL;`_escape_like` + `.like(..., escape='\\')` 正确转义通配符,防 LIKE 注入。
5. **LaTeX 编译沙箱**:`-no-shell-escape` + `openin_any/openout_any=p` + 超时 + 模板白名单 + `output_basename.isalnum()` 双保险——有效防 `\write18`/任意文件读取/路径穿越。
6. **SECRET_KEY 环境注入且拒绝硬编码回退**:`config._resolve_secret_key()` 优先环境变量,未配则随机生成并告警,绝不保留可用硬编码密钥——优于常见"默认弱密钥"反模式。
7. **上传扩展名白名单**:`ALLOWED_UPLOAD_EXTENSIONS` 明确排除 SVG(注释指出 SVG 内联渲染可携脚本构成存储型 XSS),体现细致的安全考量。
8. **`next` 跳转白名单**:`app.py:116` 仅允许 `/` 开头且非 `//` 的相对跳转,防开放重定向。
9. **验证码 + 登录限流(进行中)**:`captcha.py` 用 HMAC(SECRET_KEY, 答案) 摘要 + 一次性 + TTL + 常量时间比较,答案不明文入会话;`ratelimit.py` 线程安全的 IP/用户名双维度滑动窗口锁定——设计正确且注释坦诚说明了多进程局限。
10. **已有针对性测试**:`tests/test_auth_captcha.py`(8 项,内存库隔离)覆盖验证码与限流关键路径,是难得的工程化起点。
11. **契约与设计文档**:`SPEC.md` + 技术文档 §9 已自评改进方向(前端重构、模型规范化、PDF 健壮化等),本报告多条 P2 与之呼应——团队对自身债务有清醒认知。

---

## 五、结论与优先级建议

**一句话结论**:这是一份**代码质量扎实、核心安全模型正确的单人自托管原型**,与企业级生产的差距**几乎全部集中在"部署形态、持久化根基、运维可观测性"三类基建缺失**,而非业务或核心安全缺陷;补齐 P0 清单即可安全承载小规模多用户生产,补齐 P1/P2 后可达稳健生产标准。

**优先级建议(强约束)**:
- **P0 是硬门槛,未完成不得对外上线**——尤其是「关 debug + 换 WSGI」这一项,它同时消除最高危的 RCE 安全面与单进程不可用的可靠性面。
- P1 应在上线后 2–4 周内闭环,建立最基本的可观测性与供应链纪律。
- P2/P3 按技术文档 §9 节奏推进,其中「PostgreSQL 迁移」与「前端模块化」是决定系统能否规模化的两个长期投资点。

---

*本报告所有结论均对应仓库中真实代码位置,已逐条核实。评分与分级反映"距企业级生产"的相对差距,不代表对现有原型质量的否定。*
