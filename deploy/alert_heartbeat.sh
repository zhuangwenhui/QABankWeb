#!/usr/bin/env bash
# 错误告警心跳(rank15):存活 ping + 发现错误则 ping /fail。
#
# UptimeRobot 拨 /healthz 只能判整站生死;整站没挂但 500 飙升 / 未捕获异常 / 暴力登录锁定,
# 它一律看不见。本脚本扫近期日志,只报两三类真痛点(未捕获异常 / ERROR / 登录锁定),
# 定时随 cron 跑,命中即 ping 一个免费心跳(如 Healthchecks.io)。不上 APM,防告警疲劳。
#
# 启用:设 QB_HEARTBEAT_URL(Healthchecks.io 的 ping URL 或同类)。未设则跳过。
#   健康 → GET  $QB_HEARTBEAT_URL
#   异常 → GET  $QB_HEARTBEAT_URL/fail(附错误计数)
set -uo pipefail

URL="${QB_HEARTBEAT_URL:-}"
if [ -z "$URL" ]; then
    echo "[alert] 未设 QB_HEARTBEAT_URL,告警未启用,跳过。"
    exit 0
fi

# 日志源:优先文件(gunicorn error log),否则从 journald 取近窗口。
LOG="${QB_ERROR_LOG:-/srv/backups/question-bank/app.log}"
WINDOW="${QB_ALERT_TAIL:-300}"   # 检查日志末尾 N 行

if [ -f "$LOG" ]; then
    lines="$(tail -n "$WINDOW" "$LOG" 2>/dev/null || true)"
else
    # 无文件日志时尝试 journald(需 systemd-journal 组;失败则空)
    lines="$(journalctl -u question-bank --since '15 min ago' --no-pager 2>/dev/null | tail -n "$WINDOW" || true)"
fi

# 只报真痛点:结构化 ERROR / Python Traceback / 登录锁定(通用,不含判题特定逻辑)
problems="$(printf '%s\n' "$lines" | grep -cE '"level":[[:space:]]*"ERROR"|Traceback \(most recent|login_locked|login_lockout' || true)"
problems="${problems:-0}"

if [ "$problems" -gt 0 ]; then
    curl -fsS -m 10 --data-raw "errors=$problems" "${URL%/}/fail" >/dev/null 2>&1 || true
    echo "[alert] 近 $WINDOW 行检出 $problems 条错误信号 → 已 ping /fail"
    exit 0
fi

curl -fsS -m 10 "$URL" >/dev/null 2>&1 || true
echo "[alert] 正常 → 已 ping 存活"
