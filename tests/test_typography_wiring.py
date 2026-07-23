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
