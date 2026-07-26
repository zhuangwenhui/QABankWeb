# CHANGELOG

语义化版本;每次生产部署打轻量 tag(`git tag -a vX.Y.Z`)。回滚见 `docs/ops/deploy.md` 的回滚一节。
「当前生产跑哪版」= 最近一个已部署 tag(部署时 `git checkout vX.Y.Z`)。

## [v1.13.0] 排版闸门修复 + 题解语言双轨全量整改(2026-07-26)

**排版**
- **MathJax v4 的 a11y 渲染动作把排版闸门堵死** —— 详情弹窗公式不排版的真因,此前三轮
  都判错了方向。`typesetPromise → document.whenReady(() => renderPromise())`,而
  `renderPromise` 要 `await actionPromises()`;v4 默认注册的 enrich / attachSpeech /
  explorable 三个动作把 SRE 放进 Web Worker 跑,Worker 要从 cdn.jsdelivr.net 拉规则,
  被本站 CSP 的 `connect-src 'self'` 挡住后**永远不回话**。`whenReady` 是滚动闸门:
  一次不 settle,此后每次排版都卡在闸门前连跑都跑不到。首渲的 DOM 更新在挂起前已完成,
  所以页面"看着是好的",故障要等第二批内容注入才现形。摘掉这三个动作即解;代价是失去
  公式的读屏朗读。实测详情页首渲 226 个公式后再排一次同样 HUNG,列表页卡片视图 314 个
  公式一直落在闸门后(而巡检脚本把按钮 id 写错成 `btnCardView`,该分支从没被真正查过)。
- **代码段与转义的 `\$` 会把整段正文吞进"公式"**:`protectMath` 抽数学前没挡开代码段,
  也没排除转义,于是 `` `)$` `` 里的美元号跟后面真正的公式配上对,中间正文碎成一行一个字
  (id=266)。定界符两侧加 `(?<!\\)`,代码段先换占位符再放回。
- 护栏:e2e 增加"再排一次必须 settle"(只看首屏永远发现不了闸门被堵),`--jam` 改为
  反向对照;巡检对弹窗改为同时断言 `mjx-container > 0`;五条源码级 pytest。

**题解语言(中文轨 / 日文轨,全 358 道逐题过,不抽样)**
- 新增 `scripts/audit_language.py`(机器可判定的盘查,跨语言字符用 GB2312 / Shift_JIS
  判定,不引第三方库)、`fix_language.py`(机械修正)、`apply_language_patches.py`
  (逐题补丁落库 + 校验)、`sync_solution_columns.py`(只动题解四列的定向同步)。
- **日文轨的四个结构小标题整套是中文**,323 道无一例外:問題重述 / 思路 / 分步推導 /
  関連題目,外加 2405 处「第N步」(「步」不是日文用字)。已改为 問題文 / 方針 /
  詳細な導出 / 関連問題 / 第N段階。
- **中文轨混入日文汉字 147 道(108 种字)、日语术语 77 处、假名 65 道**:極大値、棄却域、
  設問、直交、繰り返し期待値の法則…… id=300 甚至整段是日文。
- **句読点体例**:中文轨 8783 处半角标点夹在汉字之间;日文轨 24826 处半角 `,` `.` 被当作
  句読点。日文的 `、。` 与 `，．` 是两套都对的体例,故按每篇多数派统一,只有半角一律纠正。
  采点结构化与渐进提示两个 JSON 字段同样处理(另 10223 处)。
- 逐题评审共 3337 条替换补丁。补丁是 (old,new) 精确替换而非整篇重写,落库前机械校验:
  old 必须恰好出现一次、除非显式声明否则数学片段逐字不变、标题与容器条数不得变化。
  17 条触及数学区域的补丁逐条人工复核后放行。
- 盘查命中从 353 道降到 108 道;剩余绝大多数经确认是误报(`\to Q \to R` 是算法结点不是
  数集、ア/イ/ウ 是原题选项编号)。

## [v1.12.1] 字体栈与弹窗可读性(2026-07-26)
- **自托管的中日字体从来没被用上**(v1.1.0 排版改造起):`--font-latin-read/ui` 以泛型
  `serif`/`sans-serif` **结尾**,而组合栈是 `<latin>, <cjk>` —— 泛型覆盖所有码位,浏览器到那儿就停,
  其后的 LXGW WenKai / Klee One / Noto Sans SC **永远轮不到**,汉字一路落到系统宋体。
  去掉拉丁段的尾部泛型(泛型只保留在最终栈末尾)。实测中文轨现为 LXGW WenKai、日文轨为 Klee One,
  `document.fonts` 确认二者真被加载使用。
- **日文轨吃中文字形**:`font-family:var(--font-read)` 只写在父级 `.qd-solbody` 上,自定义属性
  在那里就被算成中文栈,子轨的 `:lang(ja)` 再也改不动。字体解析下沉到 `.qd-track` 各自元素。
- **详情弹窗深色模式白字白底**:上一版把弹窗内 `.qd-page` 的背景抹成透明,而深色模式下它的
  字色是浅的 —— 整段落在 Bootstrap 白色弹窗上看不见。恢复其自有背景,明/暗对比度实测 16.0:1 / 15.3:1。
- **巡检加对比度检查**:`audit_render.py` 新增 `--scheme light|dark`,对正文容器算前景/背景
  对比度,低于 4.5:1 即报 —— 「文字消失」这类问题以后不靠肉眼。两种配色下 8/8 页干净。
- 护栏:拉丁字体段不得以泛型结尾、CJK 字体首位必须是自托管 web 字体,进 pytest。

## [v1.12.0] 删除题目修复 + 卡片预览统一 + 截断图重裁(2026-07-26)
- **「删除题目」一直是坏的**:`Question` 只对 error_book 与 view_logs 声明了级联,之后新增的
  知识点标签(v1.3)、题单条目(v1.3)、做题进度(v1.2)、笔记/收藏(v1.6)、作答(v1.5)
  六张带 `question_id` 外键的表都没补 —— SQLite 抛 `FOREIGN KEY constraint failed`,端点 500。
  而每道题都有标签,**从 v1.3 起对任何一道题都删不掉**,今天要清两条脏数据时才撞见。补齐级联,
  并加护栏:任何带 `question_id` 外键的表没登记级联即测试失败(不用等有人删题才发现)。
- **卡片预览显示的是版权声明与一条 URL 而不是题目**:126 道转载题的 `question_latex` 本就只有
  那句声明,linkify 又把网址变成链接,与其它卡片风格割裂。新增 `QDRender.previewSource()`,
  有「問題重述」时优先用它并去掉裸 URL;题目管理/错题本/总览/题单详情四处统一走它。
- **截断图重裁**:`scripts/recrop_images.py` 把被 PDF 跨页切断的题面图裁到留白边界
  (45/47 张已处理,2 张被安全阀拦下);完整题面文字本就在 `question_latex` 里,不丢内容。
  可疑图 47 → 5 张。原图已备份。
- **清理**:删除 id=36/37 两条不是题目的个人笔记(出願要点、复习计划),题库 360 → 358 道,
  0 孤儿行;`SUBJECTS` 移除「备注」防止再被误选。

## [v1.11.0] 系统性渲染盘查 + 题面还原(2026-07-26)
不再等用户肉眼发现问题,把渲染、内容完整性、功能三条线过了一遍。

**渲染的真正根因**:全站每个页面都有一条未处理的 Promise 拒绝 ——
`Failed to construct 'Worker': blob:… denied by CSP`(MathJax v4 用 blob Worker 做无障碍)。
CSP 是 `default-src 'self'` 且无 `worker-src`,Worker 创建被拒后该 Promise 未处理地 reject,
连带 `startup.promise` 与 `typesetPromise` 永久挂起 —— 这才是题解退化成 LaTeX 源码的根因。
补 `worker-src/child-src 'self' blob:`。裸探针页没有 CSP,所以此前怎么测都正常。

**四处漏网一并接入共享管线**:错题本卡片与预览弹窗、总览最近题目、题单详情条目、
题目管理列表预览(此前只做 escapeHtml,显示裸 `##` / `**` / `:::`)。管线脚本抽成
`templates/_render_pipeline.html` 单一来源。预览格改为先截断再渲染(列表页排版量 1820→670)。

**题面还原(影响 126 道题,占 35%)**:这些题因转载条件不放原题面,`question_latex` 只是
一句声明,真正的题目写在题解开头的 `## 問題重述` 里 —— 学生想读题就得展开题解,等于先看答案。
新增 `QDRender.splitRestatement()`,详情页与复习页把重述还给题面区并从题解中去重。

**新增可复跑的审计**:`scripts/audit_render.py`(全站带延迟巡检,现 8/8 页干净)、
`audit_solution_completeness.py`(小问覆盖/截断迹象/双轨与结构完整性)、
`audit_images.py`(题面图 PDF 跨页截断检测)。

**盘查结论**:题解内容完整(题面文本与「問題重述」都含全部小问,题解逐问覆盖,0 道确认缺解);
题面图 47/196 张被 PDF 跨页截断 —— 只影响观感,正文在文字里是齐的;
功能闭环(检索/筛选/分页/进度/收藏/笔记/错题本/复习/题单/反馈/PDF 导出/判题占位)全部通过。

## [v1.10.0] 修复题解数学退化成 LaTeX 源码(2026-07-26)
线上题解整篇显示为 `$…$` 源码(Mac/Windows 同现),本机怎么测都正常。
- **根因**:题解正文由 API 取回后注入,只能靠我们显式调用 MathJax 排版;而 MathJax 4.1.3 在
  详情页上 `startup.promise` 与 `typesetPromise` 都可能**永不 settle**(且不在等任何网络请求)。
  旧实现以 `startup.promise` 为闸门、只走 Promise 版 —— 注入的内容一次都排不上版。
  本机零延迟时内容能赶在 MathJax 开场自动排版之前落地被顺带排掉,故一直侥幸正常;
  **≥300ms 真实网络延迟必现**。
- **修法**:闸门改为"排版 API 可用";以同步 `MathJax.typeset` 为主,遇按需加载抛 retry 时
  用 `typesetPromise` 促发一次加载但不等其 settle,隔 0.9~1.5s 同步重试,至多 4 轮必收敛。
  `utils.typesetMath`(列表/总览页)同款处理。
- **验证**:500~800ms 延迟 + 生产数据,13 道题(含 549/614 个公式的最重两道)残留源码全 0;
  修复前同条件为 177~300 段。
- **护栏**:`scripts/e2e_math_render.py` —— 强制注入网络延迟、把题解 API 压到开场排版之后,
  另带故障注入模式;修复前必红、修复后必绿,已接入 CI。
- **同批两个真问题**:
  1. 静态资源加指纹(`?v=<mtime>`)—— nginx 发 `max-age=604800`,不加指纹时已中招的浏览器
     最长 7 天拿不到修复,光部署救不了。
  2. **`deploy/reload.sh`** —— 排查中发现线上 gunicorn 是 **7 月 21 日**启动的,此后几次发布
     (含 v1.7.0/v1.8.0)**代码从未生效**:`git pull` 只换磁盘文件,进程与 Jinja 模板缓存都是旧的。
     部署流程补上 SIGHUP 优雅重载与"新代码是否真的在跑"的校验。

## [v1.9.2] 异地备份启用,脚本自读 crontab 配置(2026-07-25)
**Cloudflare R2 异地备份已实际启用并验证**:推送 → 从 R2 拉回 → `integrity_check` +
与生产行数逐表比对 + 归档抽样解压,全绿。
- `backup.sh` / `restore_drill.sh` 改为在环境变量缺失时**自读 crontab 顶部的配置**。
  之前手动补跑要自己 `export`,而 `VAR=x cmd1 && cmd2` 只对 `cmd1` 生效 —— 实际就在这里绊了一次,
  演练误报"未设 QB_OFFSITE_REMOTE"。`-` 而非 `:-`,显式传空值仍表示"本次不走异地"。
- `setup_offsite_r2.sh` 的 endpoint 解析容错:纯账户号 / 整条 endpoint / 带桶路径都认,
  也可用 `R2_ENDPOINT`;格式可疑提前告警。R2 令牌只给 Access Key ID + Secret,账户号需另找,
  这一步实际最容易卡。
- 文档补令牌类型取舍:选 **Account API token** 而非 User API token,别把备份的存活绑在个人角色上。

## [v1.9.1] 修复 pipefail 下的 SIGPIPE(2026-07-25)
恢复演练在"抽样解压"一步间歇性以 141 退出:`| head -1` 读满即关管道,上游收 SIGPIPE,
`pipefail` 把 141 当流水线退出码,`set -e` 随即中断。输出行数少时常侥幸不触发,故时灵时不灵。
同一模式还潜伏在 `integrity_check` 取首行(库真损坏时输出多行,正是最需要它别炸的时候)、
本地快照选最新、`rclone version | head -1` 三处。全部改 awk,并加护栏禁止 pipefail 脚本再用 `| head`。

## [v1.9.0] 异地备份与容灾(2026-07-25)
本地快照与生产库同盘,VPS 灭失即全丢 —— 补上唯一能挺过整机故障的一层,落点选 Cloudflare R2
(10GB 免费额度覆盖 30 天保留量,**出口流量免费**故恢复不花钱,S3 兼容)。
- `backup.sh`:显式解析 rclone 路径(cron 精简 PATH 找不到 `~/bin`);只推本次两个产物而非整目录
  `--max-age`;**推送后回查远端字节数**才算落地;新增**异地保留期清理**(此前远端无界增长),
  `--include` 限定只删本脚本自己的产物。
- `setup_offsite_r2.sh`:一次性配置(装 rclone → 写配置 → 往返验证 → 写 crontab)。凭证只走环境变量
  不进命令行;**往返验证失败即中止**,不留"看似启用实则每晚静默失败"的开关;幂等可重跑。
- `restore_drill.sh`:从异地拉最新快照做 `integrity_check`、与生产行数比对、归档抽样解压;
  只读生产库、结束自清理。**备份只有被恢复过才算数**,已进季度 cron。
- 文档 `docs/ops/backup.md`:凭证获取步骤、容量成本、整机重建流程、RPO/RTO 与排查表。
- CI 增 shellcheck + `bash -n`;`tests/test_backup_scripts.py` 钉死九条脚本不变量。
- **启用状态**:代码与 VPS 侧 rclone 已就绪,待填入 R2 凭证后跑一次 `setup_offsite_r2.sh` 即生效。

## [v1.8.0] 权限收紧(2026-07-24)
审计发现题库**内容管理**端点(create/update/delete_question、batch_delete/tags/source、upload/delete_image、
source_exists)此前仅 `@login_required`,任何登录学生都能管理共享题库 —— admin 与 student 在内容域权限**等价**,
双轨失效。修复:
- 后端:9 端点 `@login_required`→`@admin_required`(学生 **403**);GET 读、记录查看、自有错题本/进度/复习/笔记/收藏/判题不受影响。
- 前端:非管理员隐藏新建/编辑/删除/批量内容管理按钮与右键项(后端为真边界,前端仅避免学生见到会 403 的按钮)。
- 其余域经彻查**已严格双轨**:overview/反馈处理=admin;反馈列表/删除、题单(owner+is_official)、其余个人数据按属主隔离。

## [v1.7.0] 技术债加固(2026-07-24)
审计驱动的确定性优化(判题相关项按需暂缓)。
- **后端 DRY/正确性**:新增 `api/_helpers.py` 统一响应信封(消 `_err`/`_fail` 分裂)、LIKE 转义、
  **单一实现的题目全文搜索**——修复错题本搜索漂移(此前漏 `solution_ja` 与知识点标签命中);
  笔记/收藏 upsert 补 `IntegrityError` 幂等兜底(消并发 500);`view_logs` 保留期清理防无界增长。
- **前端**:抽 `static/js/qd_render.js` 消除详情页/复习页**双份渲染管线**(杜绝再次漂移);
  Bootstrap/FontAwesome/markdown-it/DOMPurify/CodeMirror **自托管**到 `static/vendor/`,cdnjs 全移除、
  CSP 收回 `'self'`;**MathJax 锁定 `4.1.3`**(禁浮动 `@4`);CodeMirror 按 `is_admin` 门控(学生不下发死重量)。
- **测试/CI**:测试哈希改 pbkdf2(单轮 ~43s→~11s);**迁移↔模型漂移守卫**;前端接线护栏;
  CI 增 `node --check` 与 `pip-audit`。
- **运维**:异地备份 env 驱动(`QB_OFFSITE_REMOTE`,未设则告警单点);错误告警心跳脚本(`QB_HEARTBEAT_URL`)。
- **文档**:补 README 事实修正/新蓝图、本 CHANGELOG、回滚 runbook。

## [v1.6.0] 个人学习工具
私人笔记(自动保存)+ 收藏书签 + 列表「只看收藏」筛选。

## [v1.5.0] 采点判题
手写作答照片上传 → 可插拔 LLM 阅卷(`ClaudeVisionGrader` / `StubGrader`)按采点逐项给分 + 作答转写 + 反馈。
未配 `ANTHROPIC_API_KEY` 时走诚实占位 stub。

## [v1.4.0] 相关题 + 检索强化
详情页相关题推荐(共享知识点标签排序);搜索覆盖双轨题解 + 多词 AND + 知识点标签名;详情↔列表标签联动。

## [v1.3.0] 内容发现
知识点标签(规范化 + 多维筛选 + facet);题单(官方 + 用户自建);渐进提示;采点四段结构化题解。

## [v1.2.0] 学习闭环
做题状态/掌握色块;SM-2 间隔复习 + `/review` 页;做题日历热力图;顶部进度面板。

## [v1.1.0] 字体排版
自托管中日 web 字体子集(文楷/Klee/思源黑/しっぽり明朝);MathJax v3→v4(New Computer Modern);`:lang()` 分区排版。

## [v1.0.0] 初始上线(2026-07-07)
双语题库、题目管理、错题本、PDF 导出、账号/反馈;生产化加固(CSP/CSRF/限流/Alembic 迁移)。
