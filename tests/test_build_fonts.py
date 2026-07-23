import subprocess, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

import pytest

# scripts/ 无 __init__.py;用命名空间包方式导入 build_fonts
sys.path.insert(0, str(ROOT))
try:
    import scripts.build_fonts as bf
except Exception:  # pragma: no cover - 退化路径
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_fonts as bf


def test_gen_charsets_produces_expected_sets(tmp_path):
    cn = tmp_path / "cn.txt"; jp = tmp_path / "jp.txt"
    subprocess.run([sys.executable, str(ROOT/"scripts/gen_charsets.py"),
                    "--cn", str(cn), "--jp", str(jp)], check=True)
    cn_txt = cn.read_text(encoding="utf-8"); jp_txt = jp.read_text(encoding="utf-8")
    assert "中" in cn_txt and "国" in cn_txt          # GB2312 常用汉字
    assert 3000 <= len(set(cn_txt)) <= 8000            # GB2312 一二级 ~6763
    assert "あ" in jp_txt and "ア" in jp_txt          # 假名(hiragana/katakana)
    assert "漢" in jp_txt                              # JIS 汉字
    assert 3000 <= len(set(jp_txt)) <= 8000


def test_extract_corpus_gathers_cjk(monkeypatch):
    """monkeypatch read_question_rows 返回含中日文的行,断言这些字都进 corpus。"""
    rows = [
        {
            "question_latex": r"求矩阵 $A$ 的特征值",
            "solution_latex": r"特征多项式 $\det(A-\lambda I)=0$ 的根即为特征值",
            "solution_ja": "行列の固有値を求めよ。カタカナ表記も確認する",
        },
    ]
    monkeypatch.setattr(bf, "read_question_rows", lambda db_path: rows)
    corpus = bf.extract_corpus("ignored.db")
    # 中文题面/题解
    for ch in "求矩阵特征值多项式根":
        assert ch in corpus, ch
    # 日文汉字
    for ch in "行列固有値表記確認":
        assert ch in corpus, ch
    # 平假名
    for ch in "のをめよもする":
        assert ch in corpus, ch
    # 片假名
    for ch in "カタナ":
        assert ch in corpus, ch


def test_extract_corpus_includes_extra_ui_strings(monkeypatch):
    monkeypatch.setattr(bf, "read_question_rows", lambda db_path: [])
    corpus = bf.extract_corpus("ignored.db", ui_strings=["設定を保存"])
    for ch in "設定を保存":
        assert ch in corpus, ch


def test_charset_for_font_merges_fallback_and_ascii():
    corpus = set("Xy")
    cn_fb = set("中国汉")
    jp_fb = set("あアが")
    cn = bf.charset_for_font("cn", corpus, cn_fb, jp_fb)
    assert {"中", "国", "汉"} <= cn                 # 中文兜底进入 cn 字体
    assert {"0", "9", "A", "z"} <= cn               # ASCII 数字/字母恒在
    assert "あ" not in cn                            # 日文兜底不得泄漏进 cn
    jp = bf.charset_for_font("jp", corpus, cn_fb, jp_fb)
    assert {"あ", "ア", "が"} <= jp                 # 日文兜底进入 jp 字体
    assert "0" in jp                                 # ASCII 数字恒在
    assert "中" not in jp                            # 中文兜底不得泄漏进 jp


def test_charset_for_font_excludes_control_chars():
    # 语料含换行/制表(LaTeX 常见),控制符无字形必须被排除,否则覆盖校验误判
    corpus = set("A中\n\t\r")
    cn = bf.charset_for_font("cn", corpus, set("国"), set("あ"))
    assert "A" in cn and "中" in cn
    assert "\n" not in cn and "\t" not in cn and "\r" not in cn


def test_subset_font_shrinks_and_covers(tmp_path):
    src = ROOT / "fonts_src" / "KleeOne-Regular.ttf"
    if not src.exists():
        pytest.skip("源字体缺失")
    chars = set("あいうえおアイウ日本語問題0123456789ABC")
    out = tmp_path / "klee.subset.woff2"
    bf.subset_font(src, chars, out)
    assert out.exists()
    assert out.stat().st_size < src.stat().st_size
    from fontTools.ttLib import TTFont
    cmap = set(TTFont(str(out)).getBestCmap())
    for ch in chars:
        assert ord(ch) in cmap, ch


def test_emit_fontface_css_structure():
    css = bf.emit_fontface_css()
    assert "font-family:'LXGW WenKai'" in css
    assert "font-display:swap" in css
    # 文楷 500 700 权重必须用 medium 文件
    assert ("url('/static/fonts/lxgw-wenkai-medium.subset.woff2') "
            "format('woff2');font-weight:500 700") in css
    # 四个字体族 + 对应 fallback 面
    for fam in ("LXGW WenKai", "Klee One", "Noto Sans SC", "Shippori Mincho"):
        assert f"font-family:'{fam}'" in css
        assert f"font-family:'{fam} Fallback'" in css
    assert "local('Songti SC')" in css


def test_emit_fontface_css_applies_metrics():
    metrics = {"LXGW WenKai": {"ascent": "92.0%", "descent": "23.0%", "size_adjust": "100%"}}
    css = bf.emit_fontface_css(metrics)
    assert "ascent-override:92.0%" in css
    assert "descent-override:23.0%" in css


def test_select_subset_drops_glyphs_font_lacks():
    # 字体只被要求编码它 cmap 里真有的字形;缺的字被剔除,不再触发致命失败
    charset = set("A中あ")
    font_cps = {ord("A"), ord("中")}      # 假 cmap:没有 'あ'
    picked = bf.select_subset(charset, font_cps)
    assert picked == {"A", "中"}
    assert "あ" not in picked


def test_global_missing_passes_when_union_covers_corpus():
    # 并集覆盖全语料(含跨脚本:中文由某字体、日文由另一字体覆盖)→ 无缺失
    corpus = set("A中あ")
    covered = {ord("A"), ord("中"), ord("あ")}
    assert bf.global_missing(corpus, covered) == set()


def test_global_missing_detects_uncovered_corpus_char():
    # 语料里 'あ' 不在任何 cmap → 检出;控制符 '\n' 不计
    corpus = set("A中あ\n")
    covered = {ord("A"), ord("中")}
    assert bf.global_missing(corpus, covered) == {"あ"}


def test_verify_coverage_reports_missing():
    cmap = {ord("a"), ord("b")}
    missing = bf.verify_coverage(cmap, set("abc"))
    assert missing == {"c"}
    assert bf.verify_coverage({ord("a"), ord("b"), ord("c")}, set("abc")) == set()


def test_fallback_metrics_percent():
    src = ROOT / "fonts_src" / "NotoSansSC-Regular.ttf"
    if not src.exists():
        pytest.skip("源字体缺失")
    m = bf.fallback_metrics(str(src))
    assert m["ascent"].endswith("%")
    assert m["descent"].endswith("%")
    assert m["size_adjust"].endswith("%")
