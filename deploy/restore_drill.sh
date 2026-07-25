#!/usr/bin/env bash
# 恢复演练:备份只有被恢复过才算数。
#
# 从异地(或本地)取最新一份快照,在临时目录里验证它真的能用:
#   SQLite 完整性检查 → 关键表行数 → uploads 归档可解 → 与生产实况比对。
# 全程只读生产库,不改任何生产数据,结束即自清理。
#
# 用法(VPS 上以 deploy 用户运行):
#   ./restore_drill.sh              # 演练异地副本(读 crontab 注入的 QB_OFFSITE_REMOTE)
#   QB_DRILL_SOURCE=local ./restore_drill.sh   # 只演练本机 /srv/backups 的副本
set -euo pipefail
cd /

APP_DIR="/srv/question-bank"
BACKUP_DIR="/srv/backups/question-bank"
LIVE_DB="$APP_DIR/instance/question_bank.db"
SOURCE="${QB_DRILL_SOURCE:-remote}"
TABLES=(users questions error_book question_progress question_lists question_notes
        question_bookmarks tags question_tags answer_submissions feedback)

# 异地配置的真源头是 crontab 顶部的 KEY=value(见 setup_offsite_r2.sh)。cron 会自动注入,
# 但交互 shell 不会 —— 让脚本自己去读,省得每次手动 export(`VAR=x cmd1 && cmd2` 只对 cmd1
# 生效这种坑,不该让使用者去记)。
from_crontab() {
    crontab -l 2>/dev/null | sed -n "s/^$1=//p" | awk 'NR==1'
}

find_rclone() {
    local v
    if [ -n "${QB_RCLONE_BIN:-}" ]; then echo "$QB_RCLONE_BIN"; return; fi
    v="$(from_crontab QB_RCLONE_BIN)"
    if [ -n "$v" ]; then echo "$v"
    elif [ -x "${HOME:-/home/deploy}/bin/rclone" ]; then echo "${HOME:-/home/deploy}/bin/rclone"
    else command -v rclone 2>/dev/null || true; fi
}

WORK="$(mktemp -d -t qb-drill-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT   # 演练产物一律不留,避免占满 19G 盘

echo "=== 恢复演练 $(date -Is) ==="

# --- 取最新快照 -------------------------------------------------------------
if [ "$SOURCE" = "local" ]; then
    # 一律用 awk 取首行而非 `| head -1`:`set -o pipefail` 下 head 提前关管道会让上游收到
    # SIGPIPE,整条流水线以 141 退出并中断脚本(这个坑真的踩过,且因输出量小而时灵时不灵)
    db_src="$(ls -1t "$BACKUP_DIR"/db_*.sqlite3 2>/dev/null | awk 'NR==1')"
    up_src="$(ls -1t "$BACKUP_DIR"/uploads_*.tar.gz 2>/dev/null | awk 'NR==1')"
    if [ -z "$db_src" ] || [ -z "$up_src" ]; then
        echo "✗ 本机 $BACKUP_DIR 里没有快照" >&2; exit 2
    fi
    echo "来源:本机 $BACKUP_DIR"
    cp "$db_src" "$WORK/db.sqlite3"
    cp "$up_src" "$WORK/uploads.tar.gz"
    db_name="$(basename "$db_src")"; up_name="$(basename "$up_src")"
else
    # 用 `-` 而非 `:-`:显式传空值表示"本次不走异地",不该被 crontab 里的配置盖回来
    remote="${QB_OFFSITE_REMOTE-$(from_crontab QB_OFFSITE_REMOTE)}"
    if [ -z "$remote" ]; then
        echo "✗ 没有异地远端:环境变量 QB_OFFSITE_REMOTE 未设,crontab 顶部也没有。" >&2
        echo "  先跑 deploy/setup_offsite_r2.sh 启用异地备份,或用 QB_DRILL_SOURCE=local 只演练本机副本。" >&2
        exit 2
    fi
    remote="${remote%/}"
    RC="$(find_rclone)"
    if [ -z "$RC" ]; then echo "✗ 未找到 rclone" >&2; exit 2; fi
    echo "来源:异地 $remote"
    # lsf 按名排序;时间戳文件名是 db_YYYYmmdd_HHMMSS,字典序即时间序
    db_name="$("$RC" lsf "$remote" --include 'db_*.sqlite3' --stats 0 | sort | tail -1)"
    up_name="$("$RC" lsf "$remote" --include 'uploads_*.tar.gz' --stats 0 | sort | tail -1)"
    if [ -z "$db_name" ] || [ -z "$up_name" ]; then
        echo "✗ 异地没有可用快照(db='$db_name' uploads='$up_name')" >&2; exit 2
    fi
    "$RC" copyto --stats 0 "$remote/$db_name" "$WORK/db.sqlite3"
    "$RC" copyto --stats 0 "$remote/$up_name" "$WORK/uploads.tar.gz"
fi
echo "快照:$db_name / $up_name"

fail=0

# --- 1. 数据库完整性 --------------------------------------------------------
integrity="$(sqlite3 "$WORK/db.sqlite3" 'PRAGMA integrity_check;' 2>&1 | awk 'NR==1')"
if [ "$integrity" = "ok" ]; then
    echo "✓ SQLite 完整性检查:ok"
else
    echo "✗ SQLite 完整性检查:$integrity" >&2; fail=1
fi

# --- 2. 关键表行数,并与生产实况比对 ----------------------------------------
# 备份必然比生产旧,行数只会 ≤ 生产;出现 > 或 0 才是异常(恢复了别人的库/截断)
echo "表行数(备份 → 生产):"
for t in "${TABLES[@]}"; do
    b="$(sqlite3 "$WORK/db.sqlite3" "SELECT COUNT(*) FROM $t;" 2>/dev/null || echo NA)"
    l="$(sqlite3 -readonly "$LIVE_DB" "SELECT COUNT(*) FROM $t;" 2>/dev/null || echo NA)"
    mark="  "
    if [ "$b" = "NA" ]; then
        mark="✗ "; fail=1
    elif [ "$l" != "NA" ] && [ "$b" -gt "$l" ] 2>/dev/null; then
        mark="✗ "; fail=1   # 备份比生产还多 = 这不是本站的库
    fi
    printf '  %s%-22s %8s → %8s\n' "$mark" "$t" "$b" "$l"
done

# 题目为 0 说明快照是空壳,别等真出事才发现
q_backup="$(sqlite3 "$WORK/db.sqlite3" 'SELECT COUNT(*) FROM questions;' 2>/dev/null || echo 0)"
if [ "$q_backup" -lt 1 ] 2>/dev/null; then
    echo "✗ 备份库里 0 道题 —— 快照无效" >&2; fail=1
fi

# --- 3. uploads 归档可解 ----------------------------------------------------
if tar -tzf "$WORK/uploads.tar.gz" > "$WORK/list.txt" 2>"$WORK/tarerr.txt"; then
    n_backup="$(grep -c -v '/$' "$WORK/list.txt" || true)"
    n_live="$(find "$APP_DIR/uploads" -type f | wc -l)"
    echo "✓ uploads 归档可解:$n_backup 个文件(生产现有 $n_live)"
    if [ "$n_backup" -lt 1 ]; then
        echo "✗ 归档里没有文件" >&2; fail=1
    fi
    # 真解一个出来,证明不只是目录表可读、内容也没坏
    first="$(awk '!/\/$/ && !seen {print; seen=1}' "$WORK/list.txt")"
    if [ -n "$first" ] && tar -xzf "$WORK/uploads.tar.gz" -C "$WORK" "$first" 2>/dev/null \
       && [ -s "$WORK/$first" ]; then
        echo "✓ 抽样解压成功:$first ($(stat -c %s "$WORK/$first")B)"
    else
        echo "✗ 抽样解压失败:$first" >&2; fail=1
    fi
else
    echo "✗ uploads 归档损坏:$(head -1 "$WORK/tarerr.txt")" >&2; fail=1
fi

# --- 结论 -------------------------------------------------------------------
echo
if [ "$fail" -eq 0 ]; then
    echo "=== 演练通过:$db_name 可用于恢复 ==="
else
    echo "=== 演练失败:上述 ✗ 项需排查,当前容灾不可信 ===" >&2
fi
exit "$fail"
