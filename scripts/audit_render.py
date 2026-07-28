#!/usr/bin/env python3
"""全站渲染巡检:带网络延迟遍历每个会显示题目内容的页面与交互,报告

  · 裸 markdown 标记(## / ### / ** / :::)—— 说明该处没走 markdown 管线
  · 残留未排版的 $…$      —— 说明该处没排版数学
  · 控制台报错 / 失败请求

⚠️ 巡检的每个页面都带 @login_required。**未登录时浏览器会被 302 到 /login,扫到的是登录页**,
而登录页当然没有裸 markdown 也没有公式 —— 于是本脚本会一路打印「N/N 页干净」。
这个"通过"是假的,2026-07-27 就这么骗过一次。现在开局强制校验登录态,没登上直接退出。

用法(需要 Chrome + websocket-client):

    # 本机实例:自动签一个管理员会话(要求 --base 指向的实例与本仓库同 SECRET_KEY、同库)
    SECRET_KEY=<与被测实例相同> python scripts/audit_render.py \
        --base http://127.0.0.1:8098 --sign-session

    # 任意实例(含生产):自己拿一个已登录会话的 cookie 值传进来
    python scripts/audit_render.py --base https://example.com --session-cookie '<session cookie 值>'

注意本机实例默认配置每次重启都随机生成 SECRET_KEY,所以 --sign-session 必须显式用
同一个 SECRET_KEY 起服务,否则签出来的 cookie 对不上,依然登不上(会被开局校验拦下)。

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
import urllib.parse
import urllib.request

RAW_MD = re.compile(r'(?m)^\s*(?:#{2,4}\s|:::|\*\*\S)')

# 裸公式判据。原先只有下面第二行那条「配对且单行的 $…$」,于是对**落单的定界符**
# 结构性失明 —— 而落单恰恰是最常见的形态:预览截断把 $$…$$ 剖成两半时,留在页面上的
# 就是一个孤零零的 $$ 加一大段源码。2026-07-28 线上 33 道题这样露着,巡检报「裸公式=0」。
#
# 所以除了成对的 $…$,还得认:任何 $$(渲染完的页面上不该有)、\begin{}/\end{},
# 以及一批只可能来自 LaTeX 的宏。MathJax 排版成功后产出的是 SVG,这些字样不会留在
# innerText 里;它们一旦出现,就说明那段没排上。
RAW_MATH = re.compile(
    r'\$\$'
    r'|\$[^$\n]{2,120}\$'
    r'|\\(?:begin|end)\{'
    r'|\\(?:dfrac|tfrac|frac|partial|displaystyle|mathrm|mathbb|mathcal'
    r'|left|right|sum|prod|int|sqrt|leq|geq|neq|approx|cdot|times|infty'
    r'|alpha|beta|gamma|delta|lambda|sigma|theta|varphi|epsilon)\b'
)


def sign_admin_session():
    """用本仓库的应用配置签一个管理员会话 cookie 值。

    只在 --base 指向的实例与本仓库**同 SECRET_KEY、同库**时有效 —— 否则签名对不上,
    或者签出来的 user_id 在对面库里不存在。给远端实例巡检请改用 --session-cookie。
    """
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import config
    from app import create_app
    from models import User
    from flask.sessions import SecureCookieSessionInterface

    app = create_app(config.get_config())
    with app.app_context():
        user = (User.query.filter_by(role='admin', is_active=True).order_by(User.id).first()
                or User.query.order_by(User.id).first())
        if user is None:
            raise SystemExit('✗ 库里一个用户都没有,签不出会话 —— 先跑 seed.py 或建个账号')
        serializer = SecureCookieSessionInterface().get_signing_serializer(app)
        # csrf_token 只是占位:巡检全程只发 GET,不会触发 CSRF 校验
        return serializer.dumps({'user_id': user.id, 'csrf_token': 'x' * 32}), user.username


def assert_logged_in(br, base, wait):
    """开局校验:确认带着 cookie 真能进内容页,而不是被 302 到登录页。

    没有这道校验,未登录时整轮巡检扫的都是登录页,却会打印「N/N 页干净」——
    一个永远报绿、永远发现不了问题的巡检,比没有巡检更危险。
    """
    br.goto(base + "/questions", min(wait, 6))
    path = br.ev("location.pathname") or ""
    if path.rstrip('/') != "/questions":
        raise SystemExit(
            f"✗ 未登录:访问 /questions 被跳到 {path!r},巡检到的将是登录页而非内容页。\n"
            "  用 --sign-session(本机同 SECRET_KEY 同库)或 --session-cookie <值> 提供会话。\n"
            "  判据:被测实例的日志里应出现 \"path\": \"/questions\", \"status\": 200;\n"
            "        若全是 /login 200,就说明会话没生效。")
    print(f"· 登录态校验通过({path})")


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
            # --remote-allow-origins=* 不能省,理由同 scripts/e2e_math_render.py:
            # Chrome 111 起调试端口会校验 Origin,带该头的 WebSocket 握手一律 403,
            # 而 websocket-client 按 URL 自动发这个头。少了它在任何现代 Chrome 上都连不上。
            ["google-chrome", "--headless", "--disable-gpu", "--no-sandbox",
             "--remote-allow-origins=*",
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
        self.aborted = []   # 客户端取消的请求,单独记、不计入判定(见 _pump)
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
            err = p.get("errorText") or ""
            if url.startswith("data:"):
                return
            if err == "net::ERR_ABORTED":
                # ERR_ABORTED 按定义是**客户端主动取消**,不是服务端失败:页面切视图、
                # 用户翻页、或本脚本导航走人时,在途的 fetch 都会记这一条。实测服务端对
                # 这些请求全部回了 200,内容也正常渲染。
                # 曾经把它算进失败,于是题目管理页恒定报 ✗ —— 一个永远报错的巡检和一个
                # 永远报绿的巡检一样没用,人会学会无视它。故单独记录、不计入判定。
                self.aborted.append(f"{err} {url[:90]}")
            else:
                self.failed.append(f"{err} {url[:90]}")

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
        # 先跳 about:blank 停一拍,再清零,最后才导航到目标页。
        # 直接"清零→导航"会串页:上一页被导航挤掉时,它在途的 fetch 记 ERR_ABORTED,
        # 其 catch 分支还会打一条 console 告警,而这两件事都发生在清零**之后** ——
        # 于是上一页的动静被算到下一页头上。2026-07-28 题目管理页那次
        # 「加载定位筛选字典失败」正是这么来的:告警其实属于登录态校验那次导航。
        self.send("Page.navigate", {"url": "about:blank"})
        self.wait(1.0)
        self.console.clear()
        self.failed.clear()
        self.aborted.clear()
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
        "已取消": list(br.aborted),   # 仅供参考,不影响 ok
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
    if br.aborted:
        print(f"       (已取消 {len(br.aborted)} 个请求 —— 客户端主动取消,不计入判定)")
    # 扫完即清零。同一页里连着扫两次(如表格视图→卡片视图,中间不导航)时,
    # 若不清,第一次采到的告警会被第二次原样再报一遍 —— 一个事件报成两页出错。
    br.console.clear()
    br.failed.clear()
    br.aborted.clear()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8098")
    ap.add_argument("--latency", type=float, default=400)
    ap.add_argument("--qid", default="41")
    ap.add_argument("--wait", type=float, default=14)
    ap.add_argument("--scheme", choices=["light", "dark"], default="light",
                    help="模拟的配色方案;深色模式下最容易出现白字白底")
    ap.add_argument("--session-cookie", default="",
                    help="已登录会话的 cookie 值(适用于任意实例,含生产)")
    ap.add_argument("--sign-session", action="store_true",
                    help="用本仓库配置现签一个管理员会话(仅当被测实例与本仓库同 SECRET_KEY、同库)")
    args = ap.parse_args()

    if not args.session_cookie and not args.sign_session:
        raise SystemExit(
            "✗ 必须提供会话:巡检的页面都带 @login_required,没有会话只会扫到登录页,\n"
            "  而登录页天然「干净」—— 那样的通过是假的。\n"
            "  本机实例用 --sign-session,其他实例用 --session-cookie <值>。")

    if not shutil.which("google-chrome"):
        print("· 跳过:未找到 Chrome")
        return 0
    try:
        import websocket  # noqa: F401
    except ImportError:
        print("· 跳过:未装 websocket-client")
        return 0

    base = args.base.rstrip("/")
    cookie, who = args.session_cookie, "(外部传入)"
    if args.sign_session:
        cookie, who = sign_admin_session()

    br = Browser(args.latency)
    br.send("Emulation.setEmulatedMedia",
            {"features": [{"name": "prefers-color-scheme", "value": args.scheme}]})
    out = []
    try:
        print(f"=== 全站渲染巡检 base={base} 延迟={args.latency:.0f}ms 配色={args.scheme} ===")
        # cookie 的 domain 取 base 的主机名:CDP 的 setCookie 按 domain 匹配,写错了不报错、
        # 只是这个 cookie 永远不会被带上,表现就是"登录态校验没过"。
        host = urllib.parse.urlparse(base).hostname or "127.0.0.1"
        br.send("Network.setCookie",
                {"name": "session", "value": cookie, "domain": host, "path": "/"})
        print(f"· 会话身份:{who}")
        assert_logged_in(br, base, args.wait)

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

        list_href = ""
        for path, label in [(f"/questions/{args.qid}", "题目详情页"),
                            ("/error_book", "错题本"),
                            ("/overview", "总览"),
                            ("/review", "复习"),
                            ("/lists", "题单广场"),
                            ("/feedback", "意见反馈")]:
            br.goto(base + path, args.wait)
            scan(br, label, out)
            if path == "/lists":
                # 必须在**还停在题单广场时**取这个链接。原先它写在整个循环之后,
                # 那时浏览器早已导航到 /feedback,选择器自然永远落空 ——
                # 于是「题单详情」这一页从上线起就没被扫过,而本地题单一直是 0 个,
                # 没人觉得少了一页。
                list_href = br.ev(
                    """(function(){var a=document.querySelector('a[href^="/lists/"]');
                        return a?a.getAttribute('href'):'';})()""") or ""

        if list_href:
            br.goto(base + list_href, args.wait)
            scan(br, f"题单详情 {list_href}", out)
        else:
            print("  ⚠ 题单广场没有可进入的题单,跳过题单详情页(库里有题单时这不该发生)")
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
