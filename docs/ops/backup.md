# 备份与容灾 Runbook(Cloudflare R2 异地备份)

部署与日常运维见 [`deploy.md`](deploy.md);本文只讲数据:备份怎么做、异地怎么配、真出事怎么恢复。

## 0. 当前架构

| 层 | 位置 | 保留期 | 由谁产生 |
|---|---|---|---|
| 本地快照 | VPS `/srv/backups/question-bank` | 14 天 | `deploy/backup.sh`(cron 每日 04:30) |
| 异地副本 | Cloudflare R2 `r2:qb-backups` | 30 天 | 同上,推送后校验字节数 |

每次产两个文件:`db_<时间戳>.sqlite3`(SQLite `.backup` 一致性快照,WAL 下不能直接 `cp`)
与 `uploads_<时间戳>.tar.gz`(题图/作答图)。

**为什么必须有异地**:本地快照和生产库在同一块盘上,VPS 灭失(实例删除、磁盘损坏、机房事故、
误操作 `rm`)时两者一起没。异地副本是唯一能挺过"整机没了"的东西。

**容量与成本**:单日约 45 MB(db 7.5 MB + uploads 37 MB),异地保留 30 天约 1.3 GB。
R2 免费额度为 10 GB 存储 / 100 万次 A 类操作 / 1000 万次 B 类操作,**出口流量免费**——
本站用量在免费额度内,恢复时拉数据也不花钱。R2 需要账号绑定支付方式才能开通(免费额度内不扣费)。

---

## 1. 首次启用(一次性,约 10 分钟)

### 1.1 在 Cloudflare 控制台取凭证

1. 登录 Cloudflare Dashboard → 左侧 **R2 Object Storage**。首次进入需按提示开通(要求账号已绑定支付方式)。
2. **Create bucket**:名字填 `qb-backups`;Location hint 选 **Asia-Pacific (APAC)**(VPS 在东京,同区延迟最低)。
3. 回到 R2 页面 → 右侧 **Manage R2 API Tokens** → **Create API Token**:
   - Permissions:**Object Read & Write**(不要给 Admin,备份不需要建/删桶以外的权限)
   - Specify bucket:只勾 `qb-backups`(最小权限:令牌泄露也碰不到别的桶)
   - TTL:Forever
   - 令牌类型选 **Account API token**(账户级)而非 User API token:这是给 cron 用的服务凭证,
     不该把备份的存活绑在某个人的账户角色上 —— 用户身份变更会让 User token 连带失效。
4. 创建后页面**只显示一次** S3 客户端的两样,立刻记下:
   - **Access Key ID** → `R2_ACCESS_KEY_ID`
   - **Secret Access Key** → `R2_SECRET_ACCESS_KEY`
5. **Account ID 不在令牌里**,要另外找 —— 它在同页给出的 S3 endpoint
   `https://<Account ID>.r2.cloudflarestorage.com` 里(32 位十六进制),R2 概览页右侧
   和浏览器地址栏 `dash.cloudflare.com/<account_id>/r2/...` 也都有。
   下面的脚本对这一项很宽容:纯账户号、整条 endpoint、带桶路径的 endpoint 都认,
   也可以改用 `R2_ENDPOINT` 显式指定。

> 控制台文案可能随 Cloudflare 改版微调,认准"S3 兼容 API 令牌 + 单桶 Object Read & Write"即可。

### 1.2 在 VPS 上一键配置

```bash
ssh -i ~/.ssh/qbank_deploy deploy@161.34.33.67
```

```bash
read -rsp 'R2 Secret Access Key: ' R2_SECRET_ACCESS_KEY; echo
export R2_ACCOUNT_ID=<你的 Account ID>
export R2_ACCESS_KEY_ID=<你的 Access Key ID>
export R2_SECRET_ACCESS_KEY
/srv/question-bank/deploy/setup_offsite_r2.sh
```

`read -rsp` 让 Secret 不回显、不进 shell history;脚本也只从环境变量读,不放命令行(`ps` 看不到)。

脚本会依次:装 rclone(`~/bin/rclone`,deploy 无 sudo 故用官方静态二进制)→ 写
`~/.config/rclone/rclone.conf`(chmod 600)→ 建桶并做一次**写入/读回/删除**往返验证 →
把 `QB_OFFSITE_REMOTE` / `QB_OFFSITE_KEEP_DAYS` / `QB_RCLONE_BIN` 写进 crontab 顶部。
重复运行是幂等的(覆盖同名远端与同名变量行,不会叠加)。

> 为什么写 crontab 而不是 `/etc/question-bank.env`:那个文件是 `chmod 600 root:deploy`,
> deploy 用户读不到;而且 `. env` 不带 `export` 时变量传不给子进程。cron 的 `KEY=value`
> 才真正注入任务环境。这两个坑都实际踩过。

### 1.3 立即验一次

```bash
QB_OFFSITE_REMOTE=r2:qb-backups QB_RCLONE_BIN=$HOME/bin/rclone /srv/question-bank/deploy/backup.sh
/srv/question-bank/deploy/restore_drill.sh
```

前者应输出 `异地(rclone)已推送并校验`,后者应以 `演练通过` 结束(退出码 0)。

---

## 2. 日常验证

```bash
tail -20 /srv/backups/question-bank/backup.log          # 昨夜是否成功
QB_OFFSITE_REMOTE=r2:qb-backups QB_RCLONE_BIN=$HOME/bin/rclone \
  $HOME/bin/rclone lsl r2:qb-backups | tail -6          # 异地最近几份
```

`backup.sh` 在异地推送失败时**以退出码 3 结束**,cron 的 MAILTO 与
[`alert_heartbeat.sh`](../../deploy/alert_heartbeat.sh) 能看见,不会静默吞掉坏掉的容灾。

**每季度跑一次 `restore_drill.sh`**。备份只有被恢复过才算数——它从异地拉最新快照到临时目录,
做 SQLite `PRAGMA integrity_check`、关键表行数与生产比对、uploads 归档解包抽样,
全程只读生产库、结束即自清理。

---

## 3. 真出事了:恢复流程

### 3.1 数据坏了但 VPS 还在

```bash
sudo systemctl stop question-bank
# 先留一份"恢复前现场",以防判断有误还能回退
cp /srv/question-bank/instance/question_bank.db /tmp/question_bank.db.before-restore

# 选一份快照(本地有就用本地,快)
ls -1t /srv/backups/question-bank/db_*.sqlite3 | head -5
cp /srv/backups/question-bank/db_<时间戳>.sqlite3 /srv/question-bank/instance/question_bank.db
tar -xzf /srv/backups/question-bank/uploads_<时间戳>.tar.gz -C /srv/question-bank

sudo systemctl start question-bank
curl -s -H 'X-Forwarded-Proto: https' http://127.0.0.1:8000/healthz
```

> WAL 注意:覆盖 `question_bank.db` 前服务必须已停;残留的 `-wal`/`-shm` 会让新库读到旧事务,
> 停服后若仍在请一并删除。

### 3.2 整台 VPS 没了(异地副本上场)

1. 按 [`deploy.md`](deploy.md) §1–§3 在新机上重建:系统依赖、代码、venv、systemd、nginx、TLS。
2. 在新机上装 rclone 并用同一套 R2 凭证配好远端(重跑 `setup_offsite_r2.sh` 即可)。
3. 拉最新快照:

```bash
$HOME/bin/rclone lsf r2:qb-backups --include 'db_*.sqlite3' | sort | tail -1   # 记下文件名
$HOME/bin/rclone copyto r2:qb-backups/db_<时间戳>.sqlite3 /srv/question-bank/instance/question_bank.db
$HOME/bin/rclone copyto r2:qb-backups/uploads_<时间戳>.tar.gz /tmp/uploads.tar.gz
tar -xzf /tmp/uploads.tar.gz -C /srv/question-bank
```

4. 起服务 → 抽查:登录、题目数、错题本、图片能显示。
5. DNS:Cloudflare 里把 `co-enquestionbank.cc` 的 A 记录指向新 IP(仍保持 DNS only 灰云)。

**RPO/RTO**:备份每日 04:30,最坏丢失约 24 小时数据(RPO ≤ 24h);
整机重建按 runbook 约 1–2 小时(RTO)。要压 RPO 就把 cron 改成每 6 小时一次——
单次增量只有几十 MB,R2 免费额度扛得住。

---

## 4. 故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| `未找到 rclone` | cron 的精简 PATH 找不到 `~/bin` | crontab 顶部确认有 `QB_RCLONE_BIN=/home/deploy/bin/rclone` |
| `异地校验失败:… 远端 缺失B` | 推送看似成功但对象不可读(权限/桶名错) | 手跑 `rclone lsl r2:qb-backups` 看真实报错 |
| `SignatureDoesNotMatch` | Secret 抄错,或 endpoint 里 Account ID 不对 | 重跑 `setup_offsite_r2.sh` |
| `AccessDenied` | 令牌权限是 Object Read only,或没勾中这个桶 | 控制台重建令牌为 Object Read & Write |
| 异地文件越堆越多 | `QB_OFFSITE_KEEP_DAYS` 没注入 | 检查 crontab 顶部变量;也可在 R2 控制台加对象生命周期规则兜底 |

## 5. 已知取舍

- **uploads 每天整包重推**:归档内容常常逐日不变,却仍上传 37 MB/天。省流量的做法是
  改 `rclone sync` 镜像 `uploads/` 目录(只传新增文件),代价是失去"某一天的点位快照"语义。
  当前用量离免费额度还很远,先要恢复语义的简单可靠,不做这个优化。
- **异地副本未加密**:R2 侧有服务端静态加密、桶为私有且需 API 密钥。没上 `rclone crypt`
  是因为对单人运维而言"口令丢了 = 备份全废"的风险高于"R2 被读"的风险。
  若日后有多人/合规要求,再加 crypt 远端并把口令单独离线保管。
