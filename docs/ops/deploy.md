# 部署 Runbook(WebARENA Indigo / Ubuntu 24.04)

本 runbook 面向题库系统的生产部署与日常运维,配套资产见 [`deploy/`](../../deploy/) 目录:
`question-bank.service`(systemd unit)、`nginx.conf.example`(反向代理)、
`question-bank.env.example`(环境变量模板)、`backup.sh` + `crontab.example`(备份)。
以下命令均假设部署路径为 `/srv/question-bank`,应用以 `deploy` 系统用户运行,监听 `127.0.0.1:8000`。

---

## 1. 初始化服务器

```bash
# 建 deploy 用户(无密码登录,仅 SSH key)
sudo adduser --disabled-password --gecos "" deploy
sudo mkdir -p /home/deploy/.ssh
sudo cp ~/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys   # 换成实际公钥
sudo chown -R deploy:deploy /home/deploy/.ssh
sudo chmod 700 /home/deploy/.ssh
sudo chmod 600 /home/deploy/.ssh/authorized_keys

# 禁 root 密码登录 + 禁密码登录(仅 key)
sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart sshd

# 防火墙:仅放行 22/80/443
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status

# 基础依赖
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx python3-venv python3-pip sqlite3 git

# LaTeX(PDF 真编译;体积约 2GB,视磁盘容量评估)
sudo apt install -y texlive-xetex texlive-lang-chinese fonts-noto-cjk
xelatex --version   # 确认可执行
```

### 1.1 swap(1GB 内存机型必做)

xelatex 编译峰值可达数百 MB,1GB 内存实例(如 WebARENA Indigo 1GB)无 swap 时
编译期间可能触发 OOM 杀掉 gunicorn。建 2GB swap 文件:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab   # 开机自动挂载
free -h   # 确认 Swap 一行为 2.0Gi
sudo sysctl vm.swappiness=10
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swappiness.conf   # 仅内存吃紧才用 swap
```

---

## 2. 部署应用

```bash
# 以 deploy 用户操作
sudo -u deploy -H bash -c '
  sudo mkdir -p /srv/question-bank && sudo chown deploy:deploy /srv/question-bank
  git clone <repo-url> /srv/question-bank
  cd /srv/question-bank
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
'
```

### 2.1 环境变量文件

```bash
sudo cp /srv/question-bank/deploy/question-bank.env.example /etc/question-bank.env
sudo vi /etc/question-bank.env   # 把 SECRET_KEY=CHANGEME 换成下面生成的强随机值

# 生成强随机 SECRET_KEY(64 hex 字符 = 32 字节熵)
python3 -c "import secrets; print(secrets.token_hex(32))"

sudo chmod 600 /etc/question-bank.env
sudo chown root:deploy /etc/question-bank.env
```

`/etc/question-bank.env` 至少应包含:

```
APP_ENV=production
SECRET_KEY=<上面生成的强随机值,不要留 CHANGEME>
USE_X_ACCEL=1
```

> ⚠️ **不要**把 `ADMIN_INITIAL_PASSWORD` 长期写在这个文件里——它只在下面「创建管理员」这一步临时需要,用完即删(见 2.3)。

### 2.2 初始化数据库

```bash
cd /srv/question-bank
APP_ENV=production SECRET_KEY=$(grep ^SECRET_KEY /etc/question-bank.env | cut -d= -f2) \
  .venv/bin/flask --app app db upgrade
```

### 2.3 创建管理员账号

```bash
cd /srv/question-bank
env ADMIN_INITIAL_PASSWORD='<临时强密码>' \
  APP_ENV=production SECRET_KEY=$(grep ^SECRET_KEY /etc/question-bank.env | cut -d= -f2) \
  .venv/bin/flask --app app create-admin <用户名>
```

- 用 `env VAR=... command` 一次性传参而非 `export`,避免密码留在 shell history 或被同机同 uid 进程经 `/proc/<pid>/environ` 读取。
- 非 TTY 环境(如 `docker exec` 无 `-it`、CI 脚本)必须走 `ADMIN_INITIAL_PASSWORD`;否则 `create-admin` 用 `getpass` 交互读密码会读到空输入,直接中止、不建号(失败安全设计,但要知晓这个前提)。
- 首次登录会被强制要求改密,详见 [launch-checklist.md](launch-checklist.md)。

### 2.4 systemd 部署顺序(务必按此顺序,否则启动失败)

> ⚠️ **顺序警告**:`question-bank.service` 里 `EnvironmentFile=/etc/question-bank.env`,如果这个文件还不存在或权限不对,`systemctl enable --now` 会直接启动失败(unit 报 `Failed to load environment files`)。**必须先完成 2.1(建好 /etc/question-bank.env、填真 SECRET_KEY、chmod 600、chown root:deploy),再执行下面的 enable --now**。

```bash
sudo cp /srv/question-bank/deploy/question-bank.service /etc/systemd/system/question-bank.service
sudo systemctl daemon-reload
sudo systemctl enable --now question-bank
sudo systemctl status question-bank
```

### 2.5 验证

```bash
curl -s -H 'X-Forwarded-Proto: https' http://127.0.0.1:8000/healthz
# 期望输出: {"status":"ok"}
```

> 注:`-H 'X-Forwarded-Proto: https'` 不可省。生产模式强制 HTTPS(Talisman force_https),
> 直连 gunicorn 的裸 HTTP 请求会收到 302 重定向页;带上此头即模拟经过 Nginx 的真实链路
> (ProxyFix 信任一跳该头)。经 Nginx 的正常流量由 proxy_params 自动携带,无此问题。

若失败,先看日志排障:

```bash
sudo journalctl -u question-bank -n 100 --no-pager
```

---

## 3. Nginx + TLS

> ⚠️ **鸡生蛋问题**:模板 443 块的 `ssl_certificate` 是注释状态(证书尚不存在),而 nginx
> 对 `listen 443 ssl` 缺证书会直接 `nginx -t` 失败;certbot 验证域名又需要 nginx 先活着。
> 所以流程是:临时 80 端口配置 → webroot 模式取证书 → 再启用正式配置。

```bash
# 3.0 准备正式配置(先不启用)
sudo cp /srv/question-bank/deploy/nginx.conf.example /etc/nginx/sites-available/question-bank
sudo sed -i 's/example\.com/<域名>/g' /etc/nginx/sites-available/question-bank
sudo rm -f /etc/nginx/sites-enabled/default
sudo mkdir -p /var/www/certbot

# 3.0.1 临时最小配置:只开 80 口,专供 ACME 验证
sudo tee /etc/nginx/sites-available/acme-temp >/dev/null <<'EOF'
server {
    listen 80;
    server_name <域名>;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}
EOF
sudo ln -s /etc/nginx/sites-available/acme-temp /etc/nginx/sites-enabled/acme-temp
sudo nginx -t && sudo systemctl reload nginx
```

> ⚠️ **校验 `/etc/nginx/proxy_params` 含 `proxy_set_header X-Forwarded-Proto $scheme;`**:

```bash
grep -n 'X-Forwarded-Proto' /etc/nginx/proxy_params
```

Ubuntu 默认安装的 `nginx-common` 自带的 `/etc/nginx/proxy_params` 已含此行,一般无需改动。但如果是精简安装或自建的 `proxy_params`(缺失此文件或此行),应用侧 `ProxyFix` 就读不到真实协议,Flask-Talisman 的 `force_https` 会把已经是 HTTPS 的请求误判为 HTTP 再次 302 重定向,造成**无限重定向循环**。若发现该行缺失:

```bash
echo 'proxy_set_header X-Forwarded-Proto $scheme;' | sudo tee -a /etc/nginx/proxy_params
sudo nginx -t && sudo systemctl reload nginx
```

### 3.1 签发证书并启用正式配置

```bash
# webroot 模式只取证书(不让 certbot 改写我们的 nginx 配置),并登记续期后自动 reload
sudo certbot certonly --webroot -w /var/www/certbot -d <域名> \
  --deploy-hook 'systemctl reload nginx'

# 取消正式配置里两行证书注释(路径 /etc/letsencrypt/live/<域名>/ 此时已真实存在)
sudo sed -i 's|^    # ssl_certificate|    ssl_certificate|' /etc/nginx/sites-available/question-bank

# 撤下临时配置,启用正式配置
sudo rm /etc/nginx/sites-enabled/acme-temp
sudo ln -s /etc/nginx/sites-available/question-bank /etc/nginx/sites-enabled/question-bank
sudo nginx -t && sudo systemctl reload nginx
```

- 不用 `certbot --nginx` 插件:它会往我们精心分 location 的配置里自动插行(证书、跳转),
  与模板的 80→443 跳转/PDF 超时 location 叠加后行为难以预期;webroot 模式零改写、可预期。
- 续期:`certonly --webroot` 会把 webroot 参数写进 `/etc/letsencrypt/renewal/<域名>.conf`,
  systemd 的 certbot.timer 自动续期走正式配置 80 块里的 `/.well-known/acme-challenge/`
  (模板已有该 location),`--deploy-hook` 保证续完自动 reload nginx。
- 验证自动续期:

```bash
sudo certbot renew --dry-run
```

### 3.2 超时排序校验(务必核对,顺序错会导致大试卷生成被 504 掐断)

PDF 生成走同步阻塞、最坏情况(两遍 xelatex 编译)约 120 秒。三层超时必须满足:

```
PDF 编译最坏耗时 120s  <  gunicorn --timeout 130s  <  nginx PDF location 超时 140s
```

- gunicorn 侧:`deploy/question-bank.service` 里已配 `--timeout 130`,已经部署的可以确认一下:

```bash
sudo systemctl cat question-bank | grep -- '--timeout'
```

- nginx 侧:`deploy/nginx.conf.example` 的 `/api/error_book/generate_pdf` location 已配 `proxy_read_timeout 140s; proxy_send_timeout 140s;`,确认已生效:

```bash
sudo nginx -T 2>/dev/null | grep -A5 'generate_pdf'
```

若任一层超时小于等于上一层,大试卷生成请求会被提前掐断返回 502/504,即使 LaTeX 编译本可以在限内完成。

---

## 4. 备份与恢复

### 4.1 配置定时备份

```bash
chmod +x /srv/question-bank/deploy/backup.sh
sudo mkdir -p /srv/backups/question-bank
sudo chown deploy:deploy /srv/backups/question-bank

# 以 deploy 用户配置 crontab
sudo -u deploy crontab -e
# 粘贴 deploy/crontab.example 的内容:
# 30 4 * * * /srv/question-bank/deploy/backup.sh >> /srv/backups/question-bank/backup.log 2>&1
```

### 4.2 手动执行一次验证

```bash
sudo -u deploy /srv/question-bank/deploy/backup.sh
ls -la /srv/backups/question-bank/
```

期望看到 `db_<timestamp>.sqlite3` 与 `uploads_<timestamp>.tar.gz` 两个新文件,以及脚本输出的 `[backup] 完成: ...`。

### 4.3 备份可观测性(定期抽查,防止静默失败)

`backup.sh` 仅 `set -euo pipefail`,失败时非零退出但**不会主动告警**——磁盘写满、`sqlite3 .backup` 失败等情况只会体现为 cron 静默不出新文件。建议:

```bash
# 定期人工/脚本抽查最近一次备份日志与产物时间
tail -20 /srv/backups/question-bank/backup.log
find /srv/backups/question-bank -name 'db_*.sqlite3' -mtime -1   # 应能看到 24 小时内的文件
```

有条件的话可以把 crontab 那行的 `backup.sh` 换成包一层失败告警的脚本(例如失败时 `curl` 一个 Healthchecks.io/UptimeRobot 心跳 URL),本 runbook 不强制要求,但强烈建议在没有告警前每周至少人工抽查一次。

### 4.4(可选)异地备份

配置好 `rclone` 远端(OneDrive / Google Drive / S3 均可)后:

```bash
rclone config   # 交互式配置远端,记下远端名,下面假设叫 remote
```

在 `backup.sh` 末尾追加一行(脚本里已经预留了注释位置):

```bash
rclone copy "$BACKUP_DIR" remote:qb-backups/ --max-age 48h
```

### 4.5 恢复演练(上线前必做一次,之后建议每季度重演一次)

```bash
# 1. 停服务
sudo systemctl stop question-bank

# 2. 用最近一次快照覆盖数据库(先备份当前库以防万一)
cp /srv/question-bank/instance/question_bank.db /tmp/question_bank.db.before-restore
cp /srv/backups/question-bank/db_<最近时间戳>.sqlite3 /srv/question-bank/instance/question_bank.db

# 3. 解包 uploads
tar -xzf /srv/backups/question-bank/uploads_<最近时间戳>.tar.gz -C /srv/question-bank

# 4. 起服务
sudo systemctl start question-bank
sudo systemctl status question-bank

# 5. 抽查数据:登录、看题目列表数量、看错题本、确认时间戳与备份点一致
curl -s -H 'X-Forwarded-Proto: https' http://127.0.0.1:8000/healthz
```

---

## 5. 日常运维

### 5.1 部署更新

```bash
cd /srv/question-bank
sudo -u deploy git pull

# 若服务器已装 pip-tools:
sudo -u deploy .venv/bin/pip-sync requirements.txt
# 未装 pip-tools 时退化为(不会移除已卸载的依赖,仅补充/升级):
sudo -u deploy .venv/bin/pip install -r requirements.txt

APP_ENV=production SECRET_KEY=$(grep ^SECRET_KEY /etc/question-bank.env | cut -d= -f2) \
  sudo -u deploy /srv/question-bank/.venv/bin/flask --app app db upgrade

sudo systemctl restart question-bank
curl -s -H 'X-Forwarded-Proto: https' http://127.0.0.1:8000/healthz
```

### 5.2 回滚

每次生产部署都打了轻量语义 tag(见 `CHANGELOG.md`),回滚即 checkout 上一个稳定 tag:

```bash
cd /srv/question-bank
sudo -u deploy git fetch --tags
sudo -u deploy git tag --sort=-v:refname | head      # 列出发布 tag,挑上一个稳定版
sudo -u deploy git describe --tags                   # 确认"当前生产是哪个 tag/提交"
sudo -u deploy git checkout <上一个稳定 tag,如 v1.6.0>   # 对照 CHANGELOG.md 确认本次改了什么
sudo -u deploy .venv/bin/pip-sync requirements.txt   # 或 pip install -r requirements.txt
sudo systemctl restart question-bank
curl -s http://127.0.0.1:8000/healthz                # 健康门禁:回滚后必须 200
```

若本次发布包含数据库 schema 变更,仅回退代码不够,还需要处理数据库:

- 优先方案:用备份恢复(见 4.5)。**恢复前先手动跑一次 `backup.sh` 留一份"回滚前现场"**,以防回滚判断有误还能回退。
- 次选方案:`flask db downgrade <目标 revision>` 精确回退到目标 migration 版本(需确认该版本的 downgrade 脚本无损)。

```bash
sudo -u deploy /srv/question-bank/deploy/backup.sh   # 先留现场
APP_ENV=production SECRET_KEY=$(grep ^SECRET_KEY /etc/question-bank.env | cut -d= -f2) \
  sudo -u deploy /srv/question-bank/.venv/bin/flask --app app db downgrade <目标版本>
```

### 5.3 看日志

```bash
# 实时跟随
sudo journalctl -u question-bank -f

# 审计事件(登录成功/失败等,应用以 JSON 行输出,event 字段标注事件类型)
sudo journalctl -u question-bank | grep '"event"'

# 只看最近 100 行
sudo journalctl -u question-bank -n 100 --no-pager
```

### 5.4 拨测

在 [UptimeRobot](https://uptimerobot.com/)(或同类服务)配置一个 HTTP(s) Monitor:

- URL: `https://<域名>/healthz`
- 间隔:每 5 分钟
- 期望:200 且响应体含 `"status":"ok"`

上线前务必手动停一次服务(`sudo systemctl stop question-bank`)确认告警确实会触发,再 `start` 恢复。

---

## 附:最小手动启动命令(与 systemd unit 一致,仅用于临时排障)

```bash
cd /srv/question-bank
APP_ENV=production SECRET_KEY=<强随机> \
  .venv/bin/gunicorn -w 1 -k gthread --threads 8 --timeout 130 --graceful-timeout 30 \
  --error-logfile - -b 127.0.0.1:8000 app:app
```

正常运维请始终通过 `systemctl` 管理服务,不要长期用这条命令手动前台运行。
