#!/usr/bin/env python3
"""全站渲染巡检:带网络延迟遍历每个会显示题目内容的页面与交互,报告

  · 裸 markdown 标记(## / ### / ** / :::)—— 说明该处没走 markdown 管线
  · 残留未排版的 $…$      —— 说明该处没排版数学
  · 控制台报错 / 失败请求

用法(需要 Chrome + websocket-client):
    python scripts/audit_render.py --base http://127.0.0.1:8098 --latency 400

设计要点:必须注入延迟。零延迟时内容会赶在 MathJax 开场自动排版之前落地而侥幸正常,
线上故障就是这样躲过所有本地检查的。
"""
import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

RAW_MD = re.compile(r'(?m)^\s*(?:#{2,4}\s|:::|\*\*\S)')
RAW_MATH = re.compile(r'\$[^$\n]{2,120}\$')


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Browser:
    def __init__(self, latency):
        import websocket
        self.port = free_port()
        self.profile = tempfile.mkdtemp(prefix="audit-chrome-")
        self.proc = subprocess.Popen(
            ["google-chrome", "--headless", "--disable-gpu", "--no-sandbox",
             f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile}",
             "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws_url = None
        for _ in range(80):
            try:
                tabs = json.load(urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json/list"))
                pages = [t for t in tabs if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ws_url:
            raise SystemExit("✗ 连不上 Chrome CDP")
        self.ws = websocket.create_connection(ws_url, timeout=120)
        self.mid = 0
        self.console = []
        self.failed = []
        self.sent = {}
        self.send("Runtime.enable")
        self.send("Page.enable")
        self.send("Network.enable")
        self.send("Network.emulateNetworkConditions", {
            "offline": False, "latency": latency,
            "downloadThroughput": 400 * 1024, "uploadThroughput": 200 * 1024})

    def _pump(self, msg):
        m, p = msg.get("method"), msg.get("params", {})
        if m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "warning"):
            txt = " ".join(str(a.get("value", a.get("description", "")))
                           for a in p.get("args", []))[:140]
            self.console.append(f"{p['type']}: {txt}")
        elif m == "Runtime.exceptionThrown":
            self.console.append("EXC: " + str(
                p["exceptionDetails"].get("text"))[:140])
        elif m == "Network.requestWillBeSent":
            self.sent[p["requestId"]] = p["request"]["url"]
        elif m == "Network.loadingFailed":
            url = self.sent.get(p["requestId"], "?")
            if not url.startswith("data:"):
                self.failed.append(f"{p.get('errorText')} {url[:90]}")

    def send(self, method, params=None):
        self.mid += 1
        self.ws.send(json.dumps({"id": self.mid, "method": method,
                                 "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.mid:
                return msg
            self._pump(msg)

    def ev(self, expr):
        r = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        return r.get("result", {}).get("result", {}).get("value")

    def wait(self, secs):
        end = time.time() + secs
        self.ws.settimeout(0.4)
        while time.time() < end:
            try:
                self._pump(json.loads(self.ws.recv()))
            except Exception:
                pass
        self.ws.settimeout(120)

    def goto(self, url, wait=14):
        self.console.clear()
        self.failed.clear()
        self.send("Page.navigate", {"url": url})
        self.wait(wait)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


CONTRAST_JS = r"""
(function () {
  function lum(c) {
    var m = (c || '').match(/[\d.]+/g); if (!m || m.length < 3) return null;
    var v = m.slice(0, 3).map(function (x) {
      x = x / 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  }
  function bgOf(el) {
    for (var n = el; n && n !== document.documentElement; n = n.parentElement) {
      var c = getComputedStyle(n).backgroundColor;
      if (c && !/rgba\(0, 0, 0, 0\)|transparent/.test(c)) return c;
    }
    return getComputedStyle(document.body).backgroundColor;
  }
  var bad = [];
  document.querySelectorAll('.solbody, .qd-track, .qd-prob, .latex-content').forEach(function (el) {
    if (!el.innerText || !el.innerText.trim() || el.offsetParent === null) return;
    var lf = lum(getComputedStyle(el).color), lb = lum(bgOf(el));
    if (lf === null || lb === null) return;
    var ratio = (Math.max(lf, lb) + 0.05) / (Math.min(lf, lb) + 0.05);
    if (ratio < 4.5) bad.push((el.id || el.className).toString().slice(0, 28) + ' ' + ratio.toFixed(1) + ':1');
  });
  return JSON.stringify(bad.slice(0, 6));
})()
"""


def scan(br, label, out):
    text = br.ev("document.body.innerText") or ""
    raw_md = len(RAW_MD.findall(text))
    raw_math = len(RAW_MATH.findall(text))
    mjx = br.ev("document.querySelectorAll('mjx-container').length") or 0
    # 对比度:深色模式下把浅色字放到白底容器上会整段"消失",肉眼之外没人会发现
    try:
        low_contrast = json.loads(br.ev(CONTRAST_JS) or '[]')
    except Exception:
        low_contrast = []
    bad = raw_md or raw_math or low_contrast or br.console or br.failed
    out.append({
        "页面": label, "裸markdown": raw_md, "裸公式": raw_math, "已排版": mjx,
        "低对比": low_contrast, "控制台": list(br.console), "失败请求": list(br.failed),
        "ok": not bad,
    })
    mark = "✓" if not bad else "✗"
    print(f"  {mark} {label:<34} 裸md={raw_md:<4} 裸公式={raw_math:<4} 已排版={mjx}")
    for c in low_contrast:
        print(f"       低对比度 {c}")
    for c in br.console[:4]:
        print(f"       控制台 {c}")
    for f in br.failed[:4]:
        print(f"       失败请求 {f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8098")
    ap.add_argument("--latency", type=float, default=400)
    ap.add_argument("--qid", default="41")
    ap.add_argument("--wait", type=float, default=14)
    ap.add_argument("--scheme", choices=["light", "dark"], default="light",
                    help="模拟的配色方案;深色模式下最容易出现白字白底")
    args = ap.parse_args()

    if not shutil.which("google-chrome"):
        print("· 跳过:未找到 Chrome")
        return 0
    try:
        import websocket  # noqa: F401
    except ImportError:
        print("· 跳过:未装 websocket-client")
        return 0

    base = args.base.rstrip("/")
    br = Browser(args.latency)
    br.send("Emulation.setEmulatedMedia",
            {"features": [{"name": "prefers-color-scheme", "value": args.scheme}]})
    out = []
    try:
        print(f"=== 全站渲染巡检 base={base} 延迟={args.latency:.0f}ms 配色={args.scheme} ===")

        br.goto(f"{base}/questions", args.wait)
        scan(br, "题目管理(表格视图)", out)

        # 卡片视图
        if br.ev("!!document.getElementById('btnViewCard')"):
            br.ev("document.getElementById('btnViewCard').click()")
            br.wait(8)
            scan(br, "题目管理(卡片视图)", out)

        # 详情弹窗(含展开解答)
        if br.ev("!!document.querySelector('.js-open-detail')"):
            br.ev("document.querySelector('.js-open-detail').click()")
            br.wait(4)
            br.ev("var b=document.getElementById('btnToggleSolution'); b&&b.click()")
            # 弹窗与整页共用同一条排版队列,排在列表页那一批之后,预算要给足
            br.wait(args.wait)
            text = br.ev("document.getElementById('detailModal').innerText") or ""
            # 光看"有没有裸 $"不够:弹窗里既可能一个公式都没排出、文本又恰好不含 $,
            # 于是整整一轮都在报绿。必须同时断言真的产出了 mjx-container。
            mjx = br.ev("document.querySelectorAll('#detailModal mjx-container').length") or 0
            raw_md, raw_math = len(RAW_MD.findall(text)), len(RAW_MATH.findall(text))
            bad = raw_md or raw_math or mjx == 0
            print(f"  {'✗' if bad else '✓'} 题目详情弹窗                        "
                  f"裸md={raw_md:<4} 裸公式={raw_math:<4} 已排版={mjx}")
            out.append({"页面": "题目详情弹窗", "裸markdown": raw_md, "裸公式": raw_math,
                        "已排版": mjx, "低对比": [], "控制台": [], "失败请求": [],
                        "ok": not bad})

        for path, label in [(f"/questions/{args.qid}", "题目详情页"),
                            ("/error_book", "错题本"),
                            ("/overview", "总览"),
                            ("/review", "复习"),
                            ("/lists", "题单广场"),
                            ("/feedback", "意见反馈")]:
            br.goto(base + path, args.wait)
            scan(br, label, out)

        # 题单详情(取广场第一个)
        href = br.ev("""(function(){var a=document.querySelector('a[href^="/lists/"]');
                        return a?a.getAttribute('href'):'';})()""")
        if href:
            br.goto(base + href, args.wait)
            scan(br, f"题单详情 {href}", out)
    finally:
        br.close()

    bad = [r for r in out if not r["ok"]]
    print(f"\n=== 结论:{len(out) - len(bad)}/{len(out)} 页干净 ===")
    for r in bad:
        print(f"  ✗ {r['页面']}: 裸md={r['裸markdown']} 裸公式={r['裸公式']}"
              f" 低对比={len(r.get('低对比') or [])}"
              f" 控制台={len(r['控制台'])} 失败请求={len(r['失败请求'])}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
