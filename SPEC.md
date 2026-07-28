# 题库系统 模块开发契约

本文档记录各功能模块的接口契约。

> **📌 覆盖范围(2026-07-28 V1 钉版时校订)**:§2 现已覆盖**全部 9 个蓝图、55 条 `/api` 路由**
> —— questions / error_book / feedback / overview 四个自 v1.0.0 起就在,
> lists / study / progress / review / submissions 五个是 2026-07-28 补写的(§2.6–§2.10)。
> 每条路由都有测试触及(比对方式见 `tests/` 与 CHANGELOG 中「55 条 /api 路由无一遗漏」一节)。
> **V2 自动判题直接建在 §2.10 之上,开工前先读那一节。**
>
> 本文档描述现状、不下禁令 —— 早期版本写有"基础层不得修改",那句话已不成立(`app.py`/`config.py`/`models.py`
> 从 v1.0.0 一路改到今天),据此拒绝改动是误读。

## 0. 公共基础层

各模块共用的底座。改动会波及全站,改前请通读调用方。

- `app.py` — 应用工厂;页面路由 `/` `/login` `/logout` `/change_password` `/captcha` `/questions` `/questions/<qid>` `/lists` `/lists/<lid>` `/review` `/error_book` `/feedback` `/overview`;探针 `/healthz` `/readyz`;文件服务 `/uploads/<filename>`、`/generated/<filename>`;**注册 9 个蓝图**:`questions`、`error_book`、`feedback`、`overview`、`progress`、`review`、`lists`、`submissions`、`study`(注册顺序见 `app.py` 的 `register_blueprint` 段,该顺序决定 URL 冲突的解析次序)
- `config.py` — `Config` 类与枚举:`SUBJECTS`(7 门课程,**该行即唯一真源**)、`DIFFICULTIES`、`PER_PAGE_OPTIONS = [10,20,50,100]`、`FEEDBACK_STATUSES`、`PDF_TEMPLATES = ['custom_exam_template', '试卷模板', 'error_book_template']`
- `models.py` — **14 张表**:`User`、`Question`(含 `tags_list` 属性与 `to_dict()`)、`ErrorBook`(含 `to_dict()`,内嵌 question)、`QuestionProgress`、`QuestionList`、`QuestionListItem`、`QuestionNote`、`QuestionBookmark`、`Feedback`(含 `to_dict()`)、`ViewLog`、`GeneratedFile`、`Tag`、`QuestionTag`、`AnswerSubmission`。标签早已规范化为 `Tag` + `QuestionTag` 关联表(`Question.tags` 的 JSON 字段是另一套"自由标签",两者并存、用途不同)
- `auth.py` — `login_required`、`admin_required` 装饰器(API 路径下返回 JSON 401/403);CSRF 已由全局 before_request 校验,前端需在请求头带 `X-CSRFToken`(`apiFetch` 已自动处理)
- `api/_helpers.py` — 响应信封 `ok()` / `err()`、`escape_like()`、`apply_question_search()`、`prune_view_logs()`。**7 个蓝图都从这里导入**,新增共享逻辑放这里
- `templates/base.html` — 固定顶部导航、flash 消息;**Bootstrap 5.1.3 与 Font Awesome 6.4.0 已自托管**在 `static/vendor/`(不再走 CDN);**MathJax 4.1.3**(tex-svg,仍走 jsdelivr CDN,开场自动排版已关闭 `typeset: false`);子模板可用块:`{% block title %}`、`{% block head %}`、`{% block content %}`、`{% block scripts %}`
- `static/js/utils.js` — `getCsrfToken()`、`apiFetch(url, opts)`(自动 CSRF/JSON,失败抛 Error)、`buildQuery(params)`、`escapeHtml`、`debounce`、`typesetMath(el)`(有共享管线时一律委托 `QDRender`)、`difficultyClass(d)`、`difficultyBadge(d)`、`tagBadges(tags)`、`formatDate(s, withTime=false)`、`pad2(n)`、`formatLocalDate(d)`、`pageNumbers(current, total)`
- `templates/_macros.html` — 页面级共用片段:`breadcrumb(current)`、`stat_card(icon, title, body_id, card_class)`。用 `{% from '_macros.html' import ... %}` 引入
- `static/js/qd_render.js` — 富文本/数学渲染管线(`QDRender`)。凡把题目内容写进 DOM 的页面都必须经它,由 `templates/_render_pipeline.html` 统一 include。⚠️ 其中三段被 `tests/test_math_render_wiring.py` 按源码文本切片保护,改前先读该文件
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
| `/api/questions/facets` | GET | — | 院試定位字典 `{schools: [{name, count, majors: [{name, count}]}], years: [str 倒序], subjectGroups: [{name, count}]}`;院校/専攻/年份从 `source` 解析,非院試格式的题不进这三级 |
| `/api/questions/tag_facets` | GET | — | `{categories: [{name, tags: [{name, count}]}]}`;**只列至少被一道题引用的标签**(孤儿标签点了没结果,不进 facet) |
| `/api/questions/<int:qid>/related` | GET | query: limit(默认 6,夹在 1–12) | `{questions: [{id, source, subject, difficulty, chapter, shared_tags, shared_count, has_solution}], basis: 'tags'\|'subject'\|'mixed'}`;按共享知识点标签数排序,不足则以同科目最新题兜底 |
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
| `/api/overview/users` | GET | `{users: [{id, username, role, is_active, must_change_password, created_at}]}`,按 id 升序不分页 |
| `/api/overview/users` | POST | 请求 `{username(3–32 位字母/数字/下划线/连字符), role: 'student'\|'admin'}`;响应 `{user: 同上, initial_password: str}` |
| `/api/overview/users/<int:uid>/reset_password` | POST | `{initial_password: str}` |
| `/api/overview/users/<int:uid>/toggle_active` | POST | `{user: 同上}`;**禁止停用自己**(否则管理员会把自己踢下线,而启用又需要管理员权限,最后一个管理员这么干就把系统锁死了) |

> ⚠️ **建号与重置密码的成功响应带明文初始密码**,因此这两处**必须**挂 `Cache-Control: no-store`,
> 且实现里刻意保持裸 `jsonify` 而不走 `_ok()` —— `_ok()` 返回 `(Response, status)` 二元组,
> 拿不到 Response 去设头,换过去不会报错,只会**静默丢掉这个头**,明文凭据从此可被缓存。
> 明文只在本次响应返回一次、不落库、不重发;忘了就重置一个新的。新号强制 `must_change_password`。

### 2.6 题单模块(api/lists.py,蓝图名 api_lists,url_prefix='/api/lists')

全部 `login_required`。**可见性**:公开单(`is_public`)或自己拥有的单;私有单对他人按 **404** 处理(不是 403,避免泄露存在性)。**可改性** `_can_edit` = owner 或 admin;官方单由 admin 拥有,天然只有 admin 能动。

进度语义与 §2.8 对齐:有 `QuestionProgress` 行即计入 `done`(含 mastered),`status=='mastered'` 另计入 `mastered`。

| 路由 | 方法 | 请求 | 响应 data |
|---|---|---|---|
| `/api/lists` | GET | — | `{lists: [meta...]}`,官方置顶,其后按 created_at/id 倒序 |
| `/api/lists` | POST | `{title(必填,≤128), description(≤2000), is_official?, is_public?(默认 true)}` | `meta`(item_count=0);**`is_official` 仅 admin 可置**,非管理员传了也会被降为 false |
| `/api/lists/<int:lid>` | GET | — | `{list: meta, questions: [to_dict(with_solution=False)...按 position 升序], progress}` |
| `/api/lists/<int:lid>/items` | POST | `{question_id}` | `{list_id, question_id, position}`;position=当前最大值+1(空单为 0);**重复加题幂等**,返回已有 position + message='题目已在题单中' |
| `/api/lists/<int:lid>/items/<int:qid>` | DELETE | — | `{list_id, question_id}`;题不在单中回 404 |
| `/api/lists/<int:lid>/reorder` | POST | `{question_ids: [int]}`(≤5000) | `{list_id}`;按给定顺序重排 position,**列表中未提到的既有题目顺延排到末尾**,重复 id 忽略,不在单中的 id 忽略 |

`meta` = `{id, owner_id, title, description, is_official, is_public, item_count, progress: {total, done, mastered}, created_at}`。

> 广场页的 item_count 与 progress 由 `list_lists` 一次性聚合后传进 `_list_meta`,不在其中逐单查询 —— 几十个题单会变成 N+1。

### 2.7 个人学习工具(api/study.py,蓝图名 api_study,url_prefix='/api')

全部 `login_required`,数据均限定 `user_id = g.user.id`。

| 路由 | 方法 | 请求 | 响应 data |
|---|---|---|---|
| `/api/questions/<int:qid>/note` | GET | — | `{content: str}`;**没写过返回空串而不是 404**(前端直接填进输入框) |
| `/api/questions/<int:qid>/note` | PUT | `{content: str}`(≤20000;**空串合法,表示清空**) | `{content}`,message='已保存';整体覆盖非追加 |
| `/api/questions/<int:qid>/bookmark` | GET | — | `{bookmarked: bool}` |
| `/api/questions/<int:qid>/bookmark` | POST | — | `{bookmarked: bool}`(切换后的值) |
| `/api/bookmarks` | GET | — | `{question_ids: [int]}`,按收藏时间倒序 |

> ⚠️ 收藏是 **toggle 不是 set**,因此**同一请求重发不幂等** —— 网络重试会把刚收藏的又取消掉。前端靠按钮禁用防重复点击。若 V2 要做离线重放或幂等重试,得先把它改成 `PUT {bookmarked: bool}`。

写入端点(PUT note / POST bookmark)先校验题目存在,不存在回 404:不挡的话会插出指向空题的行,SQLite 的外键要 `PRAGMA foreign_keys=ON` 才拦得住。

### 2.8 学习进度(api/progress.py,蓝图名 api_progress,url_prefix='/api/progress')

全部 `login_required`,数据均限定当前用户。**状态轴**:`done` / `mastered`,**无行=未做**。

| 路由 | 方法 | 请求 | 响应 data |
|---|---|---|---|
| `/api/progress/set` | POST | `{question_id, status: 'done'\|'mastered'\|'none'}` | `{question_id, status}`;**`none` 删行**(回到未做),此时 status 回 `null` |
| `/api/progress/check_batch` | POST | `{question_ids: [int]}` | `{statuses: {"<qid>": status}}`;**键是字符串**(JSON 限制);空列表回 `{statuses: {}}` 而非 400 |
| `/api/progress/summary` | GET | — | `{overall: {total, done, mastered}, by_difficulty: {难度: {total, done, mastered}}, by_subject: {课程: 同上}}` |
| `/api/progress/calendar` | GET | query: days(默认 365,上限 366) | `{calendar: [{date: 'YYYY-MM-DD', count}...]}`,缺日补 0 |

汇总口径:`total` 是**题库中该组的总题数**(不是用户做过的),`done` 是有进度行的数量,`mastered` 是其中 status=='mastered' 的数量。分组用 `setdefault` 补槽而非直接索引 —— 库里可能有已从 `config.SUBJECTS` 移除的历史分类值,直接索引会 KeyError 让整个统计 500。

> `by_subject` / `by_difficulty` 的**键顺序不可依赖**:Flask `json.sort_keys` 默认为 true,会按码点重排。要按课程表显示就在前端用 `utils.js:orderedKeys` 定序(见 §3.1)。

### 2.9 复习队列(api/review.py,蓝图名 api_review,url_prefix='/api/review')

全部 `login_required`。**复习队列 = 当前用户的 error_book 成员 + SM-2 排期**,排期字段直接长在 `ErrorBook` 上(ease / interval_days / repetitions / due_at / last_reviewed_at),没有独立的排期表。

| 路由 | 方法 | 请求 | 响应 data |
|---|---|---|---|
| `/api/review/due` | GET | query: limit(默认 20,上限 100) | `{entries: [entry...], count}`;到期判据=`due_at IS NULL`(未排期=立即到期)**或** `due_at <= now`;NULL 排最前 |
| `/api/review/rate` | POST | `{question_id, rating: 'again'\|'hard'\|'good'\|'easy'}` | `{question_id, ease, interval_days, repetitions, due_at, last_reviewed_at}`;不在队列中回 404 |
| `/api/review/stats` | GET | — | `{due_today, upcoming_7d, total_in_review}` |

`entry` = `{error_book_id, question_id, notes, ease, interval_days, repetitions, due_at, last_reviewed_at, question: to_dict}`。题目已被删的条目在 `/due` 里被过滤掉。

`sm2_schedule(rating, ease, interval_days, repetitions)` 是**纯函数**(不碰 db、不读时钟),因此可直接单测(`tests/test_review_api.py`)。它是 SM-2 的 **Anki 四按钮变体,不是原版论文**:常数取 Anki 默认档,ease 有 **3.0 上限**(原版无上限,不封顶会把连答 easy 的题推到几年后、等于永久踢出队列,对备考有害)。改常数前先读该函数的 docstring。

### 2.10 作答提交与采点(api/submissions.py,蓝图名 api_submissions,url_prefix='/api')

全部 `login_required`。**这是 V2 自动判题的落点,V2 开工前先读这一节。**

| 路由 | 方法 | 请求 | 响应 data |
|---|---|---|---|
| `/api/questions/<int:qid>/submissions` | POST | multipart 字段 `images`(1–4 张;扩展名=全站上传白名单**减去 pdf**) | `{submission: to_dict}`,**HTTP 201**;评分成功 message='评分完成',失败='评分失败'(仍是 success=true) |
| `/api/questions/<int:qid>/submissions` | GET | — | `{submissions: [to_dict...]}`,倒序 |
| `/api/submissions/<int:sid>` | GET | — | `{submission: to_dict}` |
| `/api/submissions/<int:sid>` | DELETE | — | message='已删除',连同已落盘的作答图一起清掉 |

`to_dict` = `{id, question_id, status, image_paths, image_urls, total_score, max_score, rubric_breakdown, transcription, feedback, grader, model, error, created_at, graded_at}`。`image_urls` 由文件名**现拼**(`/uploads/<name>`)而不入库 —— 上传目录换了历史记录不用迁。

流程与不变量:

- **先落库再评分**:提交与图片先 `commit`,再调 `grading.get_grader(config).grade(...)`;评分失败只把 `status` 置 `failed` 并记 `error`,提交本身留档。
- **评分是同步的**,占着请求线程。V2 若接入真实视觉模型、单次耗时上到几十秒,这里要改成异步任务 + 轮询,`status` 已经预留了 `pending`。
- **属主隔离**:`_owned_or_404` 把「不存在」与「是别人的」合并成同一结果,一律 404 —— 分开回 404/403 等于告诉攻击者哪些 id 存在。
- 判题引擎接口:`Grader.grade(*, question_text, reference_solution, rubric, image_paths) -> dict`,返回 `{total_score, max_score, breakdown, transcription, feedback, model}`;失败抛 `GradingError`。`rubric` 取自 `Question.solution_structured_dict`(采点四段),`reference_solution` 由中日双轨题解拼成。未配 `ANTHROPIC_API_KEY` 时 `get_grader` 返回 `StubGrader`(诚实占位,不发请求)。

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

`main-content` `content-area` `breadcrumb-container` `breadcrumb-custom` `breadcrumb-separator` `question-card` `question-card-view` `question-card-item` `question-table` `latex-content` `latex-preview` `difficulty-badge`(配 `difficulty-easy/medium/hard`,用 `difficultyBadge()` 生成) `batch-toolbar` `view-toggle` `view-toggle-btn` `selected` `flash-messages` `tag-badge` `bookmark-btn`(`bookmarked`) `context-menu`(`context-menu-item`) `stat-card`(`stat-value` `stat-label`) `image-preview-thumb` `question-detail-image`

页面级补充样式写在各自模板的 `{% block head %}` 内的小型 `<style>` 中(≤60 行),不修改公共 css。

## 5. 编码规范

- Python:每个接口用 try/except 包裹数据库写操作,异常时 `db.session.rollback()` 并返回统一错误格式;输入校验失败返回 400 + code='INVALID_INPUT'
- JS:原生 ES6+,不引入框架;函数注释;避免全局散落——每页用一个立即执行的模块模式或 `document.addEventListener('DOMContentLoaded', init)` 组织
- 所有面向用户的文案用中文
