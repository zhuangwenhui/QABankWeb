import pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
def _read(p): return (ROOT/p).read_text(encoding="utf-8")

def test_style_css_prepends_ui_webfonts_and_blocks_synthesis():
    s = _read("static/css/style.css")
    assert "'Noto Sans SC'" in s or '"Noto Sans SC"' in s        # 中文界面黑体
    assert "'Shippori Mincho'" in s or '"Shippori Mincho"' in s  # 日文界面明朝
    assert "font-synthesis" in s                                  # 禁合成粗体

def test_detail_css_prepends_body_and_ui_webfonts():
    d = _read("static/css/question-detail.css")
    for fam in ("LXGW WenKai", "Klee One", "Noto Sans SC", "Shippori Mincho"):
        assert fam in d
    # 正文 web 字体必须排在系统字体之前(前置)。锚点用 "Source Han Serif SC":
    # 它只出现在 --font-zh-read 令牌里(在前置的文楷之后),不像 "Songti SC" 还
    # 被文件顶部讲历史的注释提前提及、会污染 str.index 的首次匹配。
    assert d.index("LXGW WenKai") < d.index("Source Han Serif SC")   # 中文正文文楷在系统宋/明前

def test_base_preloads_ui_fonts_and_links_fonts_css():
    b = _read("templates/base.html")
    assert "css/fonts.css" in b
    assert "noto-sans-sc-regular.subset.woff2" in b
    assert "shippori-mincho-regular.subset.woff2" in b
    assert b.count("rel=\"preload\"") + b.count("rel='preload'") >= 2
    assert "crossorigin" in b

def test_base_uses_mathjax_v4_newcm():
    b = _read("templates/base.html")
    assert "mathjax@4" in b and "mathjax@3" not in b
    assert "mathjax-newcm" in b
    assert "mtextInheritFont" in b


def test_latin_font_tokens_do_not_end_with_generic():
    """拉丁字体段不得以泛型(serif/sans-serif/monospace)结尾。

    字体栈里一旦出现泛型,它后面的族就永远轮不到 —— 泛型能覆盖所有码位,浏览器到那儿就停。
    `--font-read: <latin>, <zh>` 若 latin 段以 serif 收尾,实际就是 "…,Georgia,serif,LXGW WenKai",
    汉字直接落到系统宋体,自托管的文楷/Klee/思源黑**全程没被用过**。这条 bug 从 v1.1.0
    排版改造起一直存在,2026-07-26 才被发现。泛型只允许出现在最终组合栈的末尾。
    """
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    generic = ('serif', 'sans-serif', 'monospace', 'system-ui', 'cursive', 'fantasy')
    bad = []
    for css in ('static/css/question-detail.css', 'static/css/style.css'):
        text = (root / css).read_text(encoding='utf-8')
        for m in re.finditer(r'(--[\w-]*latin[\w-]*)\s*:\s*([^;]+);', text):
            name, value = m.group(1), m.group(2).strip()
            last = value.split(',')[-1].strip().strip('"\'')
            if last in generic:
                bad.append(f'{css} {name} 以泛型 {last} 结尾')
    assert not bad, '拉丁字体段以泛型结尾,其后的 CJK 字体将永远不被使用:' + '; '.join(bad)


def test_cjk_font_tokens_include_self_hosted_first():
    """中日正文/界面字体的第一位必须是自托管 web 字体,否则等于白下载。"""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    text = (root / 'static/css/question-detail.css').read_text(encoding='utf-8')
    want = {'--font-zh-read': 'LXGW WenKai', '--font-ja-read': 'Klee One',
            '--font-zh-ui': 'Noto Sans SC', '--font-ja-ui': 'Shippori Mincho'}
    for token, family in want.items():
        m = re.search(re.escape(token) + r'\s*:\s*([^;]+);', text)
        assert m, f'缺字体令牌 {token}'
        first = m.group(1).split(',')[0].strip().strip('"\'')
        assert first == family, f'{token} 首位应为自托管的 {family},实为 {first}'
