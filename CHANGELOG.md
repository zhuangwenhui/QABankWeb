# CHANGELOG

语义化版本;每次生产部署打轻量 tag(`git tag -a vX.Y.Z`)。回滚见 `docs/ops/deploy.md` 的回滚一节。
「当前生产跑哪版」= 最近一个已部署 tag(部署时 `git checkout vX.Y.Z`)。

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
