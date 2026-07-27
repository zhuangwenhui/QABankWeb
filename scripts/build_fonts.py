"""字体子集化流水线:语料收集 → 合并兜底 → 子集 woff2 → @font-face/CSS → 覆盖校验/度量。

产物(static/fonts/*.subset.woff2、static/css/fonts.css)由本脚本 main() 生成,
但权威产物应以生产语料另行构建,不随本脚本入库。
"""
import collections, sqlite3, re, pathlib, subprocess, sys, unicodedata
ROOT = pathlib.Path(__file__).resolve().parents[1]

ASCII_PRINTABLE = set(chr(c) for c in range(0x20, 0x7f))
# CJK/全角标点(\u 转义,勿改成字面量)
# 、。「」『』・ー〜（）【】《》，．！？：；…
CJK_PUNCT = set(
    "、。「」『』・ー〜"
    "（）【】《》，．！？"
    "：；…　"
)

# fam, 文件前缀, 脚本(cn/jp), 层级(body 正文懒加载 / ui 界面预加载),
# [(font-weight, 源文件名, 输出后缀)], fallback local() 列表
FONT_TABLE = [
  ("LXGW WenKai", "lxgw-wenkai", "cn", "body",
     [("400","LXGWWenKai-Regular.ttf","regular"),("500 700","LXGWWenKai-Medium.ttf","medium")],
     ["Songti SC","STSong","serif"]),
  ("Klee One", "klee-one", "jp", "body",
     [("400","KleeOne-Regular.ttf","regular"),("500 700","KleeOne-SemiBold.ttf","semibold")],
     ["Hiragino Mincho ProN","Yu Mincho","serif"]),
  ("Noto Sans SC", "noto-sans-sc", "cn", "ui",
     [("400","NotoSansSC-Regular.ttf","regular"),("500","NotoSansSC-Medium.ttf","medium")],
     ["PingFang SC","Microsoft YaHei","sans-serif"]),
  ("Shippori Mincho", "shippori-mincho", "jp", "ui",
     [("400","ShipporiMincho-Regular.ttf","regular"),("700","ShipporiMincho-Bold.ttf","bold")],
     ["Hiragino Mincho ProN","Yu Mincho","serif"]),
]

# 正文语料字段(题面题解;按需容错,源库可能尚未落 solution_ja 列)
BODY_FIELDS = ("question_latex", "solution_latex", "solution_ja")
# 界面语料字段(元数据:来源/科目/标签/章节)
UI_FIELDS = ("source", "subject", "tags", "chapter")


def read_question_rows(db_path):
    con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
    try:
        have = {r[1] for r in con.execute("PRAGMA table_info(questions)")}
        want = BODY_FIELDS + UI_FIELDS
        cols = [c for c in want if c in have] or list(want)
        cur = con.execute(f"SELECT {', '.join(cols)} FROM questions")
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


# 平假名/片假名 ぀-ヿ、CJK 统一 一-鿿、半角/全角形 ＀-￯
CJK_SCAN = re.compile(r"[぀-ヿ一-鿿＀-￯]+")
def _scan_ui_strings():
    out = set()
    for base in ("templates", "static/js"):
        d = ROOT/base
        if not d.exists(): continue
        for p in d.rglob("*"):
            if p.suffix in (".html", ".js") and p.is_file():
                for m in CJK_SCAN.findall(p.read_text(encoding="utf-8", errors="ignore")):
                    out.update(m)
    return out


def extract_corpus(db_path, ui_strings=None):
    """返回 (body_corpus, ui_corpus):
       body = 题面题解字符;ui = 元数据列 ∪ 模板/JS 扫描 ∪ 额外 ui_strings。"""
    body = set(); ui = set()
    for row in read_question_rows(db_path):
        for field in BODY_FIELDS:
            if row.get(field):
                body.update(row[field])
        for field in UI_FIELDS:
            if row.get(field):
                ui.update(row[field])
    ui.update(_scan_ui_strings())
    for s in (ui_strings or []):
        ui.update(s)
    return body, ui


def _is_control(ch):
    # C0 控制符/DEL/C1(\n \t 等)无字形,永不进覆盖要求,否则语料含换行即误判缺字
    cp = ord(ch)
    return cp < 0x20 or 0x7f <= cp < 0xa0


def _is_gated_glyph(ch):
    """只有"中日文字体该管的文本字形"才纳入覆盖门:CJK 汉字/假名/CJK 与全角标点/半角全角形。
       数学符号(∎∘≺⌊⌋⟂⟶… 多在 $...$ 内由 MathJax 渲染)、箭头、几何/技术符号、emoji
       (✅❌… 由系统 emoji 字体渲染)本就不由中日文字体覆盖,不作为构建阻塞。"""
    # Unicode 里未分配的码点(如 U+3040)任何字体都不会有字形。JS 正则 `[぀-ゟ]`
    # 这类**字符类端点**一旦混进语料,就会被当成必须覆盖的字,构建必然卡死
    # (2026-07-27 实际踩到)。
    if unicodedata.category(ch) == "Cn":
        return False
    cp = ord(ch)
    return (0x3000 <= cp <= 0x30ff or   # CJK 符号/标点 + 平/片假名
            0x3400 <= cp <= 0x4dbf or   # CJK 扩展 A
            0x4e00 <= cp <= 0x9fff or   # CJK 统一表意
            0xf900 <= cp <= 0xfaff or   # CJK 兼容表意
            0xff00 <= cp <= 0xffef or   # 半角/全角形
            0x20000 <= cp <= 0x2fa1f)   # CJK 扩展 B..兼容补充


def charset_for_font(tier, script, body_corpus, ui_corpus, cn_fallback, jp_fallback):
    """按层级组字集:
       body = body_corpus ∪ 脚本大兜底 ∪ ASCII ∪ 标点(懒加载,体积可接受);
       ui   = ui_corpus ∪ ASCII ∪ 标点(极小闭集,不加大兜底,因为要预加载)。"""
    base = ASCII_PRINTABLE | CJK_PUNCT
    if tier == "ui":
        base |= set(ui_corpus)
    else:
        base |= set(body_corpus)
        base |= (cn_fallback if script == "cn" else jp_fallback)
    return {c for c in base if not _is_control(c)}


# 正文字体要驮上 GB2312/JIS X0208 的大兜底,一张就是 1.7–2.4 MB。而一页真正用到的
# 汉字不过一千多个,没有理由让浏览器整张下完。按词频排序切片、每片标上 unicode-range,
# 浏览器就只取含有本页字符的那几片(与 Google Fonts 的做法相同)。
BODY_SLICE_SIZE = 500


def slice_charset(chars, freq, size=BODY_SLICE_SIZE):
    """把字集按「出现频次从高到低」排好,每 size 个字切一片。

    越靠前的片装的越是各页都要的字,实际落下来的片数因此更少。
    freq 里没有的字(只存在于兜底集的生僻字)排到最后,通常根本不会被取。

    排序键用的是频次的**位长**(即以 2 为底的粗档),不是频次本身:新题一进来,
    每个常用字的计数都会动一点,若按精确频次排,相邻两字随时会互换、连带整片
    重新洗牌,于是每次刷新字体都产生几十个文件的 diff。按粗档排,只有跨越 2 的幂
    时才会移位,刷新基本不动既有片。同档之内按码点排,保证结果可复现。
    """
    ordered = sorted(chars, key=lambda c: (-freq.get(c, 0).bit_length(), ord(c)))
    return [set(ordered[i:i + size]) for i in range(0, len(ordered), size)]


def unicode_range(chars):
    """码点集合 → CSS 的 unicode-range 值(连续的部分合并成区间)。"""
    cps = sorted(ord(c) for c in chars)
    if not cps:
        return ""
    parts, start, prev = [], cps[0], cps[0]
    for cp in cps[1:]:
        if cp == prev + 1:
            prev = cp
            continue
        parts.append(f"U+{start:X}" if start == prev else f"U+{start:X}-{prev:X}")
        start = prev = cp
    parts.append(f"U+{start:X}" if start == prev else f"U+{start:X}-{prev:X}")
    return ",".join(parts)


def subset_font(src, chars, out, flavor="woff2"):
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    unicodes = ",".join(f"U+{ord(c):04X}" for c in sorted(chars))
    cmd = [sys.executable, "-m", "fontTools.subset", str(src),
           f"--unicodes={unicodes}", "--layout-features=*", "--no-hinting",
           f"--output-file={out}"]
    if flavor:
        cmd.append(f"--flavor={flavor}")
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def font_codepoints(src):
    """源/子集字体的 cmap 码点集(该字体实际能编码的字形)。"""
    from fontTools.ttLib import TTFont
    return set(TTFont(src).getBestCmap())


def select_subset(charset, font_cps):
    """只保留该字体真有的字形——字体永远不会被要求编码它没有的字。"""
    return {c for c in charset if ord(c) in font_cps}


def verify_coverage(cmap_codepoints, required):
    return {c for c in required if ord(c) not in cmap_codepoints}


def global_missing(corpus, covered_codepoints):
    """全局覆盖门:仅对中日文字体该管的文本字形(CJK/假名/全角)把关——
       某字若在任何已建字体里都无字形则算缺失;数学/符号/emoji/控制符不纳入。"""
    return {c for c in corpus if _is_gated_glyph(c) and ord(c) not in covered_codepoints}


def fallback_metrics(src):
    from fontTools.ttLib import TTFont
    f = TTFont(src); upm = f["head"].unitsPerEm; os2 = f["OS/2"]
    asc = os2.sTypoAscender/upm; desc = abs(os2.sTypoDescender)/upm
    return {"ascent": f"{asc*100:.1f}%", "descent": f"{desc*100:.1f}%", "size_adjust": "100%"}


def emit_fontface_css(metrics=None, slices=None):
    """slices 形如 {(prefix, suf): [每片的字集]};没有就照旧写成单文件。"""
    metrics = metrics or {}
    slices = slices or {}
    lines = ["/* auto-generated by scripts/build_fonts.py -- do not edit */"]
    for fam, prefix, script, tier, weights, fbs in FONT_TABLE:
        for w, srcname, suf in weights:
            parts = slices.get((prefix, suf))
            if parts:
                for i, chars in enumerate(parts):
                    lines.append(
                        f"@font-face{{font-family:'{fam}';"
                        f"src:url('/static/fonts/{prefix}-{suf}.{i}.subset.woff2')"
                        f" format('woff2');font-weight:{w};font-display:swap;"
                        f"unicode-range:{unicode_range(chars)};}}")
                continue
            lines.append(f"@font-face{{font-family:'{fam}';"
                         f"src:url('/static/fonts/{prefix}-{suf}.subset.woff2') format('woff2');"
                         f"font-weight:{w};font-display:swap;}}")
        m = metrics.get(fam, {})
        adj = (f"size-adjust:{m.get('size_adjust','100%')};"
               f"ascent-override:{m.get('ascent','normal')};"
               f"descent-override:{m.get('descent','normal')};line-gap-override:0%;")
        local = ",".join(f"local('{x}')" for x in fbs)
        lines.append(f"@font-face{{font-family:'{fam} Fallback';src:{local};{adj}}}")
    return "\n".join(lines) + "\n"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT/"instance/question_bank.db"))
    ap.add_argument("--body-corpus", help="正文语料文件(生产构建用,避免拉整库到本地)")
    ap.add_argument("--ui-corpus", help="界面语料文件;仍会并入模板/JS 扫描")
    a = ap.parse_args()
    cn_fb = set((ROOT/"scripts/charset_cn.txt").read_text("utf-8"))
    jp_fb = set((ROOT/"scripts/charset_jp.txt").read_text("utf-8"))
    if a.body_corpus or a.ui_corpus:
        body_text = pathlib.Path(a.body_corpus).read_text("utf-8") if a.body_corpus else ""
        body_corpus = set(body_text)
        ui_corpus = set(pathlib.Path(a.ui_corpus).read_text("utf-8")) if a.ui_corpus else set()
        ui_corpus |= _scan_ui_strings()   # ui 语料仍并入模板/JS 中日文
    else:
        body_corpus, ui_corpus = extract_corpus(a.db)
        body_text = "".join((row.get(f) or "") for row in read_question_rows(a.db)
                            for f in BODY_FIELDS)
    freq = collections.Counter(body_text)
    metrics = {}
    tier_cmaps = {"body": [], "ui": []}
    slices = {}
    stale = list((ROOT/"static/fonts").glob("*.subset.woff2"))
    for fam, prefix, script, tier, weights, fbs in FONT_TABLE:
        charset = charset_for_font(tier, script, body_corpus, ui_corpus, cn_fb, jp_fb)
        for w, srcname, suf in weights:
            src = ROOT/f"fonts_src/{srcname}"
            # 只喂该字体真有的字形:日文字体缺的简体专用字、Shippori 缺的半角片假名等自然剔除
            to_subset = select_subset(charset, font_codepoints(src))
            if tier == "body":
                parts = slice_charset(to_subset, freq)
                slices[(prefix, suf)] = parts
                # 从 25 MB 的原本逐片切太慢,先做一个全字集的中间体再从它切,
                # 顺带也保证了每片都是中间体的子集。
                mid = ROOT/f"static/fonts/.{prefix}-{suf}.mid.ttf"
                subset_font(src, to_subset, mid, flavor=None)
                for i, chars in enumerate(parts):
                    out = ROOT/f"static/fonts/{prefix}-{suf}.{i}.subset.woff2"
                    subset_font(mid, chars, out)
                    tier_cmaps[tier].append(font_codepoints(out))
                mid.unlink()
            else:
                out = ROOT/f"static/fonts/{prefix}-{suf}.subset.woff2"
                subset_font(src, to_subset, out)
                tier_cmaps[tier].append(font_codepoints(out))
        metrics[fam] = fallback_metrics(ROOT/f"fonts_src/{weights[0][1]}")
    # 覆盖门按层分别查:各层语料须被该层已建字体的 cmap 并集覆盖(跨脚本由并集天然通过)
    for tier, corpus in (("body", body_corpus), ("ui", ui_corpus)):
        union = set().union(*tier_cmaps[tier]) if tier_cmaps[tier] else set()
        missing = global_missing(corpus, union)
        if missing:
            raise SystemExit(f"[{tier} missing glyphs] {''.join(sorted(missing))[:80]}")
    (ROOT/"static/css/fonts.css").write_text(emit_fontface_css(metrics, slices), "utf-8")
    # 改了切法之后上一轮的片若留着,就成了 CSS 再也不引用的孤儿文件
    built = {ROOT/f"static/fonts/{p}-{s}.{i}.subset.woff2"
             for (p, s), parts in slices.items() for i in range(len(parts))}
    built |= {ROOT/f"static/fonts/{p}-{s}.subset.woff2"
              for _f, p, _sc, tier, ws, _fb in FONT_TABLE if tier == "ui" for _w, _n, s in ws}
    for old in stale:
        if old not in built:
            old.unlink()
            print(f"removed stale {old.name}")
    total = sum(f.stat().st_size for f in (ROOT/"static/fonts").glob("*.subset.woff2"))
    print(f"build done  ({len(built)} files, {total/1048576:.1f} MB total)")


if __name__ == "__main__":
    main()
