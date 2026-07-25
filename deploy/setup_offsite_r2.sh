#!/usr/bin/env bash
# 一次性配置 Cloudflare R2 异地备份(在 VPS 上以 deploy 用户运行)。
#
# 做四件事:装 rclone(免 sudo)→ 写 rclone 远端配置 → 往返读写验证 → 把开关写进 crontab。
# 幂等:重复运行会覆盖同名远端与同名 cron 变量行,不会叠加。
#
# 用法(凭证只经环境变量传入,绝不写进仓库、不出现在 ps 的命令行里):
#   read -rsp 'R2 Secret Access Key: ' R2_SECRET_ACCESS_KEY; echo
#   export R2_ACCOUNT_ID=xxxxx R2_ACCESS_KEY_ID=xxxxx R2_SECRET_ACCESS_KEY
#   ./setup_offsite_r2.sh
#
# 可选环境变量:
#   R2_BUCKET(默认 qb-backups)、QB_RCLONE_REMOTE(远端名,默认 r2)
#   QB_OFFSITE_KEEP_DAYS(异地保留天数,默认 30)、QB_SETUP_NO_CRON=1(只配不动 crontab)
set -euo pipefail
umask 077   # 配置文件含密钥,全程 600

BUCKET="${R2_BUCKET:-qb-backups}"
REMOTE="${QB_RCLONE_REMOTE:-r2}"
KEEP_DAYS="${QB_OFFSITE_KEEP_DAYS:-30}"
RCLONE="$HOME/bin/rclone"
CONF="$HOME/.config/rclone/rclone.conf"
BACKUP_SH="/srv/question-bank/deploy/backup.sh"

for v in R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY; do
    if [ -z "${!v:-}" ]; then
        echo "✗ 缺少环境变量 $v(取值步骤见 docs/ops/backup.md §2)" >&2
        exit 2
    fi
done

# --- 1. rclone(deploy 无 sudo,用官方静态二进制装进 ~/bin)-------------------
if [ ! -x "$RCLONE" ]; then
    echo "[1/4] 安装 rclone → $RCLONE"
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    curl -fsSL -o "$tmp/rclone.zip" https://downloads.rclone.org/rclone-current-linux-amd64.zip
    unzip -q "$tmp/rclone.zip" -d "$tmp"
    mkdir -p "$HOME/bin"
    install -m 0755 "$tmp"/rclone-*-linux-amd64/rclone "$RCLONE"
    rm -rf "$tmp"; trap - EXIT
else
    echo "[1/4] rclone 已就位:$("$RCLONE" version | head -1)"
fi

# --- 2. 写远端配置 ----------------------------------------------------------
# 手写 INI 而非 `rclone config create`:后者要把密钥放进命令行,ps 可见。
echo "[2/4] 写入远端 [$REMOTE] → $CONF"
mkdir -p "$(dirname "$CONF")"
tmpconf="$(mktemp)"
if [ -f "$CONF" ]; then
    cp -p "$CONF" "$CONF.bak"
    # 剔除已存在的同名段,避免重复运行叠加出两个 [r2]
    awk -v sec="[$REMOTE]" '$0 == sec {skip=1; next} /^\[/ {skip=0} !skip {print}' \
        "$CONF" > "$tmpconf"
fi
{
    echo "[$REMOTE]"
    echo "type = s3"
    echo "provider = Cloudflare"
    echo "access_key_id = $R2_ACCESS_KEY_ID"
    echo "secret_access_key = $R2_SECRET_ACCESS_KEY"
    echo "endpoint = https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    echo "acl = private"
    # R2 令牌常只授单桶权限,没有 HeadBucket;不关掉每次操作都会先探桶而失败
    echo "no_check_bucket = true"
} >> "$tmpconf"
mv "$tmpconf" "$CONF"
chmod 600 "$CONF"

# --- 3. 往返验证:写探针 → 读回比对 → 删探针 -------------------------------
# 这一步是唯一的真凭据:配置写对了不等于远端能用。任何一环失败都必须在改 crontab 之前中止,
# 否则留下一个"看起来启用了、实际每晚静默失败"的异地备份 —— 比没有更危险。
echo "[3/4] 往返验证 $REMOTE:$BUCKET"
# 超时刻意收紧:每日备份可以慢慢重试网络抖动,首次配置则应该几十秒内告诉你凭证对不对。
# (用宽松的 --timeout 5m --retries 3 时,凭证抄错会静静卡十几分钟才报错。)
RC=("$RCLONE" --contimeout 20s --timeout 60s --retries 1 --low-level-retries 2 --stats 0)

probe="$(mktemp)"; got="$(mktemp)"
cleanup_probe() { rm -f "$probe" "$got"; }
trap cleanup_probe EXIT

# 桶一般已在控制台建好;单桶 Object Read & Write 令牌没有 CreateBucket 权限,
# 这里失败不代表配置有问题,交由下面的探针来定论
"${RC[@]}" mkdir "$REMOTE:$BUCKET" 2>/dev/null || true

echo "question-bank offsite canary $(date -Is) $$" > "$probe"
if ! "${RC[@]}" copyto "$probe" "$REMOTE:$BUCKET/.canary"; then
    echo "✗ 写入失败 —— 检查:桶名是否为 $BUCKET、令牌是否为 Object Read & Write 且勾中该桶、" >&2
    echo "  Account ID / Access Key / Secret 是否抄全。已中止(未改 crontab)。" >&2
    exit 4
fi
if ! "${RC[@]}" copyto "$REMOTE:$BUCKET/.canary" "$got"; then
    echo "✗ 读回失败 —— 令牌可能只有写权限。已中止(未改 crontab)。" >&2
    exit 4
fi
if ! cmp -s "$probe" "$got"; then
    echo "✗ 往返内容不一致 —— 远端不可信,已中止(未改 crontab)。" >&2
    exit 4
fi
if ! "${RC[@]}" deletefile "$REMOTE:$BUCKET/.canary"; then
    echo "✗ 删除失败 —— 没有删除权限则保留期清理会每晚失败。已中止(未改 crontab)。" >&2
    exit 4
fi
cleanup_probe; trap - EXIT
echo "    ✓ 写入 / 读回 / 删除 均成功"

# --- 4. 写 crontab 顶部的开关变量 -------------------------------------------
# 写 crontab 而非 /etc/question-bank.env:后者是 chmod 600 root:deploy,deploy 读不到;
# 且 `. env` 不带 export 时变量根本传不给子进程。cron 的 KEY=value 才真正注入任务环境。
if [ "${QB_SETUP_NO_CRON:-0}" = "1" ]; then
    echo "[4/4] 跳过 crontab(QB_SETUP_NO_CRON=1)。手动加到 crontab 顶部:"
    echo "    QB_OFFSITE_REMOTE=$REMOTE:$BUCKET"
    echo "    QB_OFFSITE_KEEP_DAYS=$KEEP_DAYS"
    echo "    QB_RCLONE_BIN=$RCLONE"
    exit 0
fi

echo "[4/4] 写入 crontab 环境变量"
current="$(crontab -l 2>/dev/null || true)"
[ -n "$current" ] && printf '%s\n' "$current" > "$HOME/crontab.bak.$(date +%Y%m%d_%H%M%S)"
{
    echo "QB_OFFSITE_REMOTE=$REMOTE:$BUCKET"
    echo "QB_OFFSITE_KEEP_DAYS=$KEEP_DAYS"
    echo "QB_RCLONE_BIN=$RCLONE"
    printf '%s\n' "$current" | grep -v -E '^(QB_OFFSITE_REMOTE|QB_OFFSITE_KEEP_DAYS|QB_RCLONE_BIN)=' || true
} | crontab -

echo
echo "✓ 异地备份已启用:$REMOTE:$BUCKET(异地保留 ${KEEP_DAYS} 天,本地 14 天)"
echo "  立即实跑一次:  QB_OFFSITE_REMOTE=$REMOTE:$BUCKET QB_RCLONE_BIN=$RCLONE $BACKUP_SH"
echo "  恢复演练:      /srv/question-bank/deploy/restore_drill.sh"
