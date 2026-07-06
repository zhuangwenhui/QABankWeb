# 上线前检查清单(全部打勾方可对外)

- [ ] /etc/question-bank.env 已设强随机 SECRET_KEY(≥64 hex),文件 600 权限
- [ ] APP_ENV=production;`systemctl show question-bank -p Environment` 无 FLASK_DEBUG
- [ ] curl -sI https://<域名>/login:含 Content-Security-Policy(带 nonce)、
      X-Frame-Options=SAMEORIGIN、X-Content-Type-Options=nosniff、Strict-Transport-Security
- [ ] SSL Labs(https://www.ssllabs.com/ssltest/)评级 ≥ A
- [ ] 数据库中不存在可登录的 admin/admin123、student/student123(seed 未在生产运行过)
- [ ] create-admin 创建的管理员首登被强制改密,改密后正常使用
- [ ] 管理员建号 → 新用户初始密码登录 → 强制改密 → 正常使用,全流程通过
- [ ] create-admin 引导后 `unset ADMIN_INITIAL_PASSWORD`(环境变量可被同机同 uid 进程经 /proc/<pid>/environ 读取,亦可能进 shell history);推荐用一次性 `env ADMIN_INITIAL_PASSWORD=… flask --app app create-admin <name>` 而非 export(Task12 评审)
- [ ] 非 TTY 环境(docker exec 无 -it / CI)跑 create-admin 必须走 `ADMIN_INITIAL_PASSWORD`,否则 getpass 读空 → 中止不建号(Task12 评审:失败安全,但需知晓)
- [ ] 运维须知(告知管理员):**勿从面板重置自己的密码**——会立即触发强制改密把自己弹出面板;忘记密码用 `create-admin`(同名报"已存在",需先在库中处理)或用另一管理员重置。破窗恢复路径 = create-admin CLI(Task12 评审)
- [ ] 未登录访问 /questions 302、/api/questions 401;学生访问 /api/overview/stats 403
- [ ] 无 X-CSRFToken 的 POST 被 400 拒绝
- [ ] 上传 21MB 文件被 413 拒绝;上传 .exe 被 400 拒绝
- [ ] PDF 生成:真实编译产出 PDF(服务器已装 xelatex)
- [ ] PDF 并发限制:同时发 3 个 generate_pdf 请求(3 个终端或 `seq 3 | xargs -P3 -I{} curl ...`),
      至少 1 个返回 429 且其余正常完成(注:2 worker 部署下全局并发上限为 2,串行连点两次不会触发 429)
- [ ] 他人 /generated 链接 404(用两个账号互测)
- [ ] **X-Accel 生产冒烟(Task15 评审,启用 USE_X_ACCEL=1 前必过)**:
  - [ ] `curl -sI https://<域名>/generated/<真实uuid>.pdf`(已登录 cookie):最终 `Content-Type: application/pdf`、`Content-Length` 为真实大小(非 0)、`Accept-Ranges: bytes` 存在(验证 CT 归属 + Nginx 覆盖 Content-Length + Range 支持)
  - [ ] 外部直接 `curl -sI https://<域名>/_protected_uploads/<任意名>` → **404**(确认 internal location 不可外部直达,否则绕过登录鉴权泄露文件)
  - [ ] 大文件 Range 续传可用(`curl -r 0-1023` 返回 206)
  - [ ] ⚠️ Nginx internal location + staging 冒烟未通过前,**不要**设 USE_X_ACCEL=1 对外(否则文件 404 或泄露)
- [ ] (UX 债,Task15 评审,非阻塞)PDF 下载文件名当前为 `{uuid}.pdf`——如需友好名(如"错题本_日期.pdf"),应用侧 X-Accel 补发 `Content-Disposition: attachment; filename=...`(Nginx 会透传)、开发侧 send_from_directory 加 as_attachment/download_name;由产品决定优先级
- [ ] backup.sh 手动执行成功;**恢复演练完成一次**;cron 已配置
- [ ] journalctl 可见 JSON 请求日志与 login_success 审计事件
- [ ] UptimeRobot 拨测 /healthz 正常报警链路(手动停服务验证一次告警)
- [ ] 浏览器控制台无 CSP 拦截报错(题目管理/错题本/反馈/总览/改密各页走查)。CSP 具体必测项(Task 7 评审给出):
  - [ ] 含公式题目页:Network 面板确认 `input/tex/extensions/boldsymbol.js` 从 jsdelivr 200 加载,Console 无 CSP `Refused to load/connect`,`\boldsymbol{}` 渲染为粗体
  - [ ] 新建/编辑 Modal:CodeMirror + stex 高亮正常(cdnjs 两 script 200),其注入的内联 style 不被 style-src 拦(已放 unsafe-inline,真机确认)
  - [ ] Bootstrap dropdown/tooltip 注入的内联 style 无 style-src 报错
  - [ ] 真浏览器触发一次 500:error.html 完整渲染、MathJax 脚本 nonce 生效(补足 test client 未覆盖的真机一环)
  - [ ] 生产 https:`curl -sI https://域名/login` 有 HSTS 且 CSP 含 `'nonce-...'`;`curl -sI http://域名/login` 302→https;确认 Nginx 转 `X-Forwarded-Proto=https`(否则 /api/* 客户端会吃到 302)
  - [ ] data: 图片(若用)在 img-src data: 下正常;上传图走 'self' 放行
- [ ] (强烈建议,非阻塞)上线首版考虑先 `content_security_policy_report_only=True` + `report_uri`,收集一轮真机违规再切正式 enforce(避免无浏览器环境下推断放行的组件在真机被静默拦截)
- [ ] 用户管理 UI 真机点验(Task13 评审):慢速网络下建号连续开关两 Modal ×10,确认 body 无残留 `modal-open`/`padding-right`(滚动锁不卡);停用他人有二次确认、停用自己 400 toast、网络断开错误 toast;初始密码 Modal 复制在 HTTPS 下走 clipboard、HTTP 下降级为手动选中
- [ ] a11y 收尾(Task13 评审,非阻塞):createUserModal/initialPwModal 补 `aria-labelledby` 指向标题、`role="dialog"`/`aria-modal`,btn-close 补 `aria-label="关闭"`
