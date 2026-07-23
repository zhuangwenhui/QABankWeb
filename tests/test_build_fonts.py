import subprocess, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

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
