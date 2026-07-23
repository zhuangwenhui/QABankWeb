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


def test_extract_corpus_splits_body_and_ui(monkeypatch):
    """extract_corpus 返回 (body, ui):body=题面题解,ui=元数据列。"""
    rows = [
        {
            "question_latex": r"求矩阵 $A$ 的特征值",
            "solution_latex": r"特征多项式 $\det(A-\lambda I)=0$ 的根即为特征值",
            "solution_ja": "行列の固有値を求めよ。カタカナ表記も確認する",
            "source": "京都大学 院試",
            "subject": "線形代数",
            "tags": "特征值;対角化",
            "chapter": "第三章",
        },
    ]
    monkeypatch.setattr(bf, "read_question_rows", lambda db_path: rows)
    body, ui = bf.extract_corpus("ignored.db")
    # 正文:题面/题解的中日文字
    for ch in "求矩阵特征值多项式根":
        assert ch in body, ch
    for ch in "行列固有値表記確認のをめよカタナ":
        assert ch in body, ch
    # 界面:元数据列(校名/科目/标签/章节)的字
    for ch in "京都大学院試":
        assert ch in ui, ch
    for ch in "線形代数対角化第三章":
        assert ch in ui, ch
    # 分层隔离:题解专有字不得混进 ui;元数据专有字不得混进 body
    assert "矩" not in ui and "阵" not in ui
    assert "線" not in body and "章" not in body


def test_extract_corpus_ui_includes_extra_ui_strings(monkeypatch):
    monkeypatch.setattr(bf, "read_question_rows", lambda db_path: [])
    body, ui = bf.extract_corpus("ignored.db", ui_strings=["設定を保存"])
    for ch in "設定を保存":
        assert ch in ui, ch


def test_charset_for_font_body_keeps_big_fallback():
    body = set("Xy")
    ui = set("按钮")
    cn_fb = set("中国汉")
    jp_fb = set("あアが")
    cn = bf.charset_for_font("body", "cn", body, ui, cn_fb, jp_fb)
    assert {"中", "国", "汉"} <= cn                 # body cn 保留中文大兜底
    assert {"0", "9", "A", "z"} <= cn               # ASCII 恒在
    assert "あ" not in cn                            # 日文兜底不得泄漏进 cn
    assert "按" not in cn                            # body 不含 ui 语料
    jp = bf.charset_for_font("body", "jp", body, ui, cn_fb, jp_fb)
    assert {"あ", "ア", "が"} <= jp                 # body jp 保留日文大兜底
    assert "0" in jp
    assert "中" not in jp


def test_charset_for_font_ui_is_minimal_closed_set():
    body = set("题面正文")
    ui = set("科目按钮")
    cn_fb = set("中国汉" * 1)          # 假装的大兜底
    jp_fb = set("あアが")
    ui_set = bf.charset_for_font("ui", "cn", body, ui, cn_fb, jp_fb)
    assert {"科", "目", "按", "钮"} <= ui_set        # ui 语料进入
    assert {"0", "9", "A"} <= ui_set                 # ASCII 恒在
    # 关键:ui 字体不加大兜底,不含正文语料
    assert not (cn_fb & ui_set), "ui 字体不得含大兜底字表"
    assert "题" not in ui_set and "正" not in ui_set  # ui 不含 body 语料


def test_charset_for_font_excludes_control_chars():
    # 语料含换行/制表(LaTeX 常见),控制符无字形必须被排除,否则覆盖校验误判
    body = set("A中\n\t\r")
    cn = bf.charset_for_font("body", "cn", body, set(), set("国"), set("あ"))
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
