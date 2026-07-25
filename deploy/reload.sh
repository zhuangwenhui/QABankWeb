#!/usr/bin/env bash
# 让新拉下来的代码真正生效(deploy 用户无 sudo,用 gunicorn 主进程的 SIGHUP 优雅重载)。
#
# 为什么需要它:`git pull` 只换磁盘上的文件,跑着的 gunicorn 仍是旧代码,连模板都缓存在内存里
# (生产 debug=False,Jinja 不自动重载)。2026-07-25 排查数学渲染故障时才发现线上进程是 7 月 21 日
# 启动的 —— 此后几次发布全都没生效。部署流程里 pull 之后必须跑这个。
set -euo pipefail

pid="$(pgrep -o -u "$(id -un)" -f 'gunicorn.*app:app' || true)"
if [ -z "$pid" ]; then
    echo "✗ 没找到 gunicorn 主进程(服务没跑?用 systemctl 起)" >&2
    exit 2
fi

before="$(ps -o lstart= -p "$pid")"
kill -HUP "$pid"
sleep 6

code="$(curl -s -o /dev/null -w '%{http_code}' -H 'X-Forwarded-Proto: https' \
        http://127.0.0.1:8000/healthz || echo 000)"
if [ "$code" != "200" ]; then
    echo "✗ 重载后 /healthz 返回 $code —— 立刻查 journalctl -u question-bank" >&2
    exit 3
fi

echo "[reload] 主进程 $pid(启动于$before)已优雅重载,healthz 200"
echo "[reload] 校验新代码是否真的上线:curl -s https://co-enquestionbank.cc/login | grep -o 'style.css?v=[0-9]*'"
