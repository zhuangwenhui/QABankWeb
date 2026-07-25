#!/usr/bin/env python3
"""端到端护栏:带网络延迟打开题目详情页,确认题解里的数学真的排版成、没有残留 LaTeX 源码。

为什么必须带延迟:题解正文是页面载入后由 API 取回再注入的。零延迟(localhost)时它能赶在
MathJax 开场自动排版之前落地而侥幸正常;只要有真实网络延迟,就必须依赖我们自己的显式排版
调用 —— 2026-07-25 的线上故障正是这条路径挂死,而所有本地检查都通过。故本脚本强制注入延迟。

用法:
    python scripts/e2e_math_render.py                 # 自建临时库+起应用,自测(CI 用)
    python scripts/e2e_math_render.py --url URL       # 测已有地址(需免登录或已登录会话)
    python scripts/e2e_math_render.py --latency 800

依赖:google-chrome(headless)+ websocket-client。缺任一则跳过并以 0 退出(不阻断 CI)。
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_BLOCK = """## 第 {i} 节 思路

核心公式 $\\dfrac{{2}}{{\\pi}}\\int_0^\\infty\\dfrac{{t\\sin t}}{{t^2+b^2}}\\,dt=e^{{-b}}$,对 $b$ 求导即得,
其中 $J_{{i}}:=e^{{-1}}$ 且 $\\det(t^2E+A^2)=(t^2+1)^2$。

:::note 一眼看穿
分母恰好是 $(t^2+1)^2$,这不是巧合。另有 $\\boldsymbol{{v}}\\cdot\\boldsymbol{{w}}$ 与 $\\text{{定義}}$。
:::

### {i}.1 立底公式

$$H_{{{i}}}(b)=\\int_0^\\infty\\frac{{t\\sin t}}{{t^2+b^2}}\\,dt=\\frac{{\\pi}}{{2}}e^{{-b}},\\quad
A^2=\\begin{{pmatrix}}-1&2\\\\-2&3\\end{{pmatrix}}.$$

- 第一项 $\\tfrac12 e^{{-1}}$ 与 **粗体** 说明
- 第二项 $\\sqrt{{2}}$
"""

# 故障只在公式量大的真实页面上复现(小页面 MathJax 不会卡),所以样本必须够重:
# ~30 段 × 每段 8 个公式 ≈ 240 个,与线上一道大题的量级相当。
SAMPLE_MD = "\n".join(_BLOCK.format(i=i) for i in range(1, 31))


def find_chrome():
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    return None


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_app(tmpdir):
    """起一个免登录的本地实例,库里只有一道含数学的题。"""
    runner = os.path.join(tmpdir, "runner.py")
    db_path = os.path.join(tmpdir, "e2e.db")
    port = free_port()
    with open(runner, "w", encoding="utf-8") as fh:
        fh.write(f'''
import sys
sys.path.insert(0, {ROOT!r})
from flask import g
from app import create_app
from models import db, User, Question
import config as config_module

cfg = type("Cfg", (config_module.Config,), {{
    "SQLALCHEMY_DATABASE_URI": "sqlite:///{db_path}",
    "SECRET_KEY": "e2e-math-render",
    "WTF_CSRF_ENABLED": False,
    "UPLOAD_FOLDER": {os.path.join(tmpdir, "uploads")!r},
    "GENERATED_PDF_FOLDER": {os.path.join(tmpdir, "generated")!r},
}})
app = create_app(cfg)

@app.before_request
def _force_admin():
    if g.get("user") is None:
        g.user = User.query.filter_by(role="admin").first()

with app.app_context():
    db.create_all()
    if not User.query.first():
        u = User(username="e2e", role="admin")
        u.set_password("E2ePass123456")
        db.session.add(u)
    if not Question.query.first():
        db.session.add(Question(
            subject="数学",
            chapter="微积分",
            source="E2E 数学渲染护栏",
            question_latex={SAMPLE_MD!r},
            solution_latex={SAMPLE_MD!r},
            solution_ja={SAMPLE_MD!r},
        ))
    db.session.commit()

app.run(host="127.0.0.1", port={port}, debug=False, use_reloader=False)
''')
    proc = subprocess.Popen([sys.executable, runner],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    base = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=2)
            return proc, base + "/questions/1"
        except Exception:
            if proc.poll() is not None:
                err = proc.stderr.read().decode("utf-8", "replace")[-1500:]
                raise SystemExit(f"✗ 应用启动失败:\n{err}")
            time.sleep(0.5)
    proc.terminate()
    raise SystemExit("✗ 应用未在 40s 内就绪")


# 故障注入:把 typesetPromise 换成"永不 settle",精确复刻 2026-07-25 线上观测到的行为。
# 合成内容触发不了 MathJax 那个库级挂起,所以护栏不去碰运气复现,而是直接注入故障 ——
# 只依赖 Promise 版 API 的实现必挂,有同步兜底的实现必过。
JAM_SCRIPT = r"""
(function () {
  var done = false;
  var iv = setInterval(function () {
    if (done) return;
    if (window.MathJax && typeof window.MathJax.typesetPromise === 'function') {
      done = true;
      clearInterval(iv);
      window.MathJax.typesetPromise = function () { return new Promise(function () {}); };
      if (window.MathJax.startup) {
        window.MathJax.startup.promise = Promise.resolve();
      }
    }
  }, 10);
  setTimeout(function () { clearInterval(iv); }, 30000);
})();
"""


API_HOLD_SECONDS = 6   # 题解 API 至少压这么久,确保落在 MathJax 开场排版之后


def check(url, latency, wait, chrome, jam=False):
    import websocket

    port = free_port()
    profile = tempfile.mkdtemp(prefix="e2e-chrome-")
    browser = subprocess.Popen(
        [chrome, "--headless", "--disable-gpu", "--no-sandbox",
         f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(80):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list"))
                pages = [t for t in tabs if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ws_url:
            raise SystemExit("✗ 连不上 Chrome CDP")

        ws = websocket.create_connection(ws_url, timeout=120)
        mid = [0]

        def send(method, params=None):
            mid[0] += 1
            ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == mid[0]:
                    return msg

        def ev(expr):
            r = send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            return r.get("result", {}).get("result", {}).get("value")

        send("Runtime.enable")
        send("Page.enable")
        send("Network.enable")
        if jam:
            send("Page.addScriptToEvaluateOnNewDocument", {"source": JAM_SCRIPT})
        send("Network.emulateNetworkConditions", {
            "offline": False, "latency": latency,
            "downloadThroughput": 400 * 1024, "uploadThroughput": 200 * 1024})
        # 关键:把题解 API 压到 MathJax 开场自动排版之后才放行。
        # 否则内容会赶在开场排版前落地被顺带排掉,护栏就永远绿 —— 那正是这个 bug 当初
        # 躲过所有本地检查的原因(localhost 零延迟时内容总能抢跑)。
        send("Fetch.enable", {"patterns": [{"urlPattern": "*/api/questions/*"}]})
        send("Page.navigate", {"url": url})

        deadline = time.time() + wait
        ws.settimeout(0.5)
        while time.time() < deadline:
            try:
                msg = json.loads(ws.recv())
            except Exception:
                continue
            if msg.get("method") == "Fetch.requestPaused":
                time.sleep(API_HOLD_SECONDS)
                mid[0] += 1
                ws.send(json.dumps({"id": mid[0], "method": "Fetch.continueRequest",
                                    "params": {"requestId": msg["params"]["requestId"]}}))
        ws.settimeout(120)

        mjx = ev("document.querySelectorAll('mjx-container').length") or 0
        raw = ev(r"(document.body.innerText.match(/\$[^$\n]{2,120}\$/g)||[]).length") or 0
        sample = ev(r"JSON.stringify((document.body.innerText.match(/\$[^$\n]{2,120}\$/g)||[]).slice(0,3))")
        ws.close()
        return mjx, raw, sample
    finally:
        browser.terminate()
        try:
            browser.wait(timeout=10)
        except Exception:
            browser.kill()
        shutil.rmtree(profile, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="已有的题目详情页地址;缺省则自建临时实例")
    ap.add_argument("--latency", type=float, default=400, help="注入的网络延迟(ms)")
    ap.add_argument("--wait", type=float, default=20, help="页面等待秒数")
    ap.add_argument("--jam", action="store_true",
                    help="故障注入:让 typesetPromise 永不 settle(复刻线上故障)")
    ap.add_argument("--both", action="store_true", help="正常与故障注入两种模式都跑")
    args = ap.parse_args()

    chrome = find_chrome()
    if not chrome:
        print("· 跳过:未找到 Chrome")
        return 0
    try:
        import websocket  # noqa: F401
    except ImportError:
        print("· 跳过:未装 websocket-client(pip install websocket-client)")
        return 0

    proc = tmpdir = None
    url = args.url
    try:
        if not url:
            tmpdir = tempfile.mkdtemp(prefix="e2e-math-")
            proc, url = start_app(tmpdir)
        modes = [False, True] if args.both else [args.jam]
        rc = 0
        for jam in modes:
            tag = "故障注入(typesetPromise 永不 settle)" if jam else "常规"
            print(f"[{tag}] {url}(延迟 {args.latency:.0f}ms,等待 {args.wait:.0f}s)")
            mjx, raw, sample = check(url, args.latency, args.wait, chrome, jam=jam)
            print(f"  已排版公式 mjx-container = {mjx}")
            print(f"  残留未排版 $…$ 段数 = {raw}  {sample if raw else ''}")
            if raw > 0:
                print("  ✗ 失败:页面上有未排版的 LaTeX 源码 —— 动态注入内容的排版链路断了")
                rc = 1
            elif mjx < 1:
                print("  ✗ 失败:一个公式都没排版出来")
                rc = 1
            else:
                print("  ✓ 通过:动态注入的题解数学全部排版成功")
        return rc
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
