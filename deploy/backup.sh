#!/usr/bin/env bash
# 每日备份:SQLite 安全快照 + uploads 打包;本地保留 14 天,异地保留 30 天。
set -euo pipefail

# 与调用方 cwd 解耦:find 结束时要求能返回初始目录,
# 若从 deploy 无权进入的目录(如他人 home)调用会报错中断
cd /

APP_DIR="/srv/question-bank"
BACKUP_DIR="/srv/backups/question-bank"
STAMP="$(date +%Y%m%d_%H%M%S)"
KEEP_DAYS=14
DB_NAME="db_$STAMP.sqlite3"
UP_NAME="uploads_$STAMP.tar.gz"

mkdir -p "$BACKUP_DIR"

# WAL 模式下必须用 .backup 而非直接 cp,保证一致性快照
sqlite3 "$APP_DIR/instance/question_bank.db" \
    ".backup '$BACKUP_DIR/$DB_NAME'"

tar -czf "$BACKUP_DIR/$UP_NAME" -C "$APP_DIR" uploads

find "$BACKUP_DIR" -type f -mtime +"$KEEP_DAYS" -delete

# ---------------------------------------------------------------------------
# 异地备份(rank1):同盘同机的本地快照是数据的唯一单点,VPS 灭失即全丢。
# 设环境变量 QB_OFFSITE_REMOTE 即启用(免改脚本):
#   rclone 远端(Cloudflare R2 / B2 / S3 等):QB_OFFSITE_REMOTE="r2:qb-backups"
#   或 scp 目标:                             QB_OFFSITE_REMOTE="scp:user@host:/backups/qb"
# 首次配置见 deploy/setup_offsite_r2.sh,恢复演练见 deploy/restore_drill.sh。
# ---------------------------------------------------------------------------
# 异地配置的真源头是 crontab 顶部的 KEY=value。cron 会自动注入,交互 shell 不会 ——
# 手动补跑一次备份时不该悄悄跳过异地,所以脚本自己去读。
# 用 `-` 而非 `:-`:显式传空值表示"本次不走异地",不该被 crontab 里的配置盖回来。
from_crontab() {
    crontab -l 2>/dev/null | sed -n "s/^$1=//p" | awk 'NR==1'
}
QB_OFFSITE_REMOTE="${QB_OFFSITE_REMOTE-$(from_crontab QB_OFFSITE_REMOTE)}"
OFFSITE_KEEP_DAYS="${QB_OFFSITE_KEEP_DAYS:-$(from_crontab QB_OFFSITE_KEEP_DAYS)}"
OFFSITE_KEEP_DAYS="${OFFSITE_KEEP_DAYS:-30}"

# deploy 用户无 sudo,rclone 装在 ~/bin;cron 的精简 PATH 找不到它,故显式解析
find_rclone() {
    if [ -z "${QB_RCLONE_BIN:-}" ]; then
        QB_RCLONE_BIN="$(from_crontab QB_RCLONE_BIN)"
    fi
    if [ -n "${QB_RCLONE_BIN:-}" ]; then
        # 显式指定却不可执行时直接报错,不静默回落到另一个二进制掩盖配置错误
        if [ -x "$QB_RCLONE_BIN" ]; then
            echo "$QB_RCLONE_BIN"
        else
            echo "[backup] ⚠ QB_RCLONE_BIN=$QB_RCLONE_BIN 不存在或不可执行" >&2
        fi
    elif [ -x "${HOME:-/home/deploy}/bin/rclone" ]; then
        echo "${HOME:-/home/deploy}/bin/rclone"
    else
        command -v rclone 2>/dev/null || true
    fi
}

# copy 退出 0 只说明"命令没报错",不等于对象真的可读。比对远端字节数才算落地。
# 用 `lsl 远端 --include /名字` 而非 `lsl 远端/名字`:前者是明确的列举+过滤,
# 不依赖各 backend 对"这是目录还是文件"的猜测。
verify_remote_file() {
    local rc="$1" remote="$2" name="$3" want got
    want="$(stat -c %s "$BACKUP_DIR/$name")"
    got="$("$rc" lsl "$remote" --include "/$name" --stats 0 2>/dev/null | awk 'NR==1 {print $1}')"
    if [ "$got" = "$want" ]; then
        return 0
    fi
    echo "[backup] ⚠ 异地校验失败:$name 本地 ${want}B / 远端 ${got:-缺失}B" >&2
    return 1
}

push_rclone() {
    local remote="${1%/}" rc
    rc="$(find_rclone)"
    if [ -z "$rc" ]; then
        echo "[backup] ⚠ 未找到 rclone:装到 ~/bin/rclone 或设 QB_RCLONE_BIN" >&2
        return 1
    fi

    local flags=(--retries 3 --low-level-retries 10 --contimeout 30s --timeout 5m --stats 0)
    [ -n "${QB_RCLONE_CONFIG:-}" ] && flags+=(--config "$QB_RCLONE_CONFIG")

    # 只推本次两个产物:比 `copy 整目录 --max-age 48h` 更确定
    # —— 补跑、时钟漂移、上一轮失败都不会漏推或重推整目录
    "$rc" copy "${flags[@]}" "$BACKUP_DIR/$DB_NAME" "$remote/" || return 1
    "$rc" copy "${flags[@]}" "$BACKUP_DIR/$UP_NAME" "$remote/" || return 1
    verify_remote_file "$rc" "$remote" "$DB_NAME" || return 1
    verify_remote_file "$rc" "$remote" "$UP_NAME" || return 1
    echo "[backup] 异地(rclone)已推送并校验 → $remote"

    # 远端保留期:本地 find -mtime 只清本地,远端不清会无界增长(R2 免费额度 10GB)。
    # --include 双保险:即使远端桶混有他用数据,也只可能删到本脚本自己的产物。
    if [ "$OFFSITE_KEEP_DAYS" -gt 0 ] 2>/dev/null; then
        if "$rc" delete "${flags[@]}" "$remote" \
                --min-age "${OFFSITE_KEEP_DAYS}d" \
                --include "db_*.sqlite3" --include "uploads_*.tar.gz"; then
            echo "[backup] 异地保留期清理完成(> ${OFFSITE_KEEP_DAYS} 天)"
        else
            echo "[backup] ⚠ 异地保留期清理失败(推送已成功,远端可能堆积)" >&2
            return 1
        fi
    fi
    return 0
}

push_scp() {
    local dest="$1"
    if scp -q "$BACKUP_DIR/$DB_NAME" "$BACKUP_DIR/$UP_NAME" "$dest/"; then
        echo "[backup] 异地(scp)已推送 → $dest"
        return 0
    fi
    echo "[backup] ⚠ 异地(scp)推送失败 → $dest(本地备份仍在,请排查)" >&2
    return 1
}

offsite_ok=1
if [ -n "${QB_OFFSITE_REMOTE:-}" ]; then
    case "$QB_OFFSITE_REMOTE" in
        scp:*) push_scp "${QB_OFFSITE_REMOTE#scp:}" || offsite_ok=0 ;;
        *)     push_rclone "$QB_OFFSITE_REMOTE"     || offsite_ok=0 ;;
    esac
else
    echo "[backup] ⚠ 未设 QB_OFFSITE_REMOTE:备份仅在本机 $BACKUP_DIR,无异地副本(数据单点风险)!" >&2
fi

echo "[backup] 完成: $DB_NAME + $UP_NAME"
# 异地推送失败以非零退出,让 cron(MAILTO)与监控看得见,不静默吞掉损坏的容灾
[ "$offsite_ok" -eq 1 ] || exit 3
