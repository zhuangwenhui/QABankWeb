#!/usr/bin/env bash
# 每日备份:SQLite 安全快照 + uploads 打包;保留 14 天。
set -euo pipefail

# 与调用方 cwd 解耦:find 结束时要求能返回初始目录,
# 若从 deploy 无权进入的目录(如他人 home)调用会报错中断
cd /

APP_DIR="/srv/question-bank"
BACKUP_DIR="/srv/backups/question-bank"
STAMP="$(date +%Y%m%d_%H%M%S)"
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"

# WAL 模式下必须用 .backup 而非直接 cp,保证一致性快照
sqlite3 "$APP_DIR/instance/question_bank.db" \
    ".backup '$BACKUP_DIR/db_$STAMP.sqlite3'"

tar -czf "$BACKUP_DIR/uploads_$STAMP.tar.gz" -C "$APP_DIR" uploads

find "$BACKUP_DIR" -type f -mtime +"$KEEP_DAYS" -delete

# 异地备份(rank1,强烈建议):同盘同机的本地快照是数据的唯一单点,VPS 灭失即全丢。
# 设环境变量 QB_OFFSITE_REMOTE 即启用(免改脚本):
#   rclone 远端(B2/R2/S3 等):QB_OFFSITE_REMOTE="remote:qb-backups"
#   或 scp 目标:            QB_OFFSITE_REMOTE="scp:user@host:/backups/qb"
offsite_ok=1
if [ -n "${QB_OFFSITE_REMOTE:-}" ]; then
    case "$QB_OFFSITE_REMOTE" in
        scp:*)
            dest="${QB_OFFSITE_REMOTE#scp:}"
            if scp -q "$BACKUP_DIR/db_$STAMP.sqlite3" "$BACKUP_DIR/uploads_$STAMP.tar.gz" "$dest/"; then
                echo "[backup] 异地(scp)已推送 → $dest"
            else
                echo "[backup] ⚠ 异地(scp)推送失败 → $dest(本地备份仍在,请排查)" >&2
                offsite_ok=0
            fi
            ;;
        *)
            if rclone copy "$BACKUP_DIR" "$QB_OFFSITE_REMOTE" --max-age 48h; then
                echo "[backup] 异地(rclone)已同步 → $QB_OFFSITE_REMOTE"
            else
                echo "[backup] ⚠ 异地(rclone)同步失败 → $QB_OFFSITE_REMOTE(本地备份仍在,请排查)" >&2
                offsite_ok=0
            fi
            ;;
    esac
else
    echo "[backup] ⚠ 未设 QB_OFFSITE_REMOTE:备份仅在本机 $BACKUP_DIR,无异地副本(数据单点风险)!" >&2
fi

echo "[backup] 完成: db_$STAMP.sqlite3 + uploads_$STAMP.tar.gz"
# 异地推送失败以非零退出,让 cron(MAILTO)与监控看得见,不静默吞掉损坏的容灾
[ "$offsite_ok" -eq 1 ] || exit 3
