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

# (可选)异地备份:配置 rclone 远端后取消注释
# rclone copy "$BACKUP_DIR" remote:qb-backups/ --max-age 48h

echo "[backup] 完成: db_$STAMP.sqlite3 + uploads_$STAMP.tar.gz"
