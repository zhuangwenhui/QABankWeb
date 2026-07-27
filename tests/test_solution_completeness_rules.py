"""題解完整性盘查の判定境界。

2026-07-27 の見直し前は 358 題中 349 題に信号が立っていた。中身を見ると:

  · 「結尾无收束」307 件 —— 本库の体例は `:::conclusion` の**後ろ**に `## 関連問題` を置く。
    末尾 260 字だけを見る判定では結論が窓の外に出てしまう。
  · 「以标点悬空结尾」71 件 —— 容器の閉じ `:::` の `:` を句読点と数えていた。
  · 「题面缺失」126 件 —— 転載できない題は日文轨の `## 問題文` に再掲する体例なのに、
    そこを見ていなかった。
  · 「未覆盖小问」—— 冒頭の「問9.」(大問自身の番号)や文中の「条件 (i)–(iii)」まで
    小問として数えていた。

信号が 9 割方外れる盘查は読まれなくなる。だから境界をここに固定する。
"""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'audit_solution_completeness', ROOT / 'scripts/audit_solution_completeness.py')
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

CONCLUDED = (
    '## 詳細な導出\n\n本文である。\n\n'
    ':::conclusion\n$$x=1.$$\n:::\n\n'
    '## 関連問題\n\n- ' + 'これは発展的な話題であり本題の答ではない。' * 12 + '\n'
)


def flags(qlatex='題面である。', slatex='', sja='', qimg=''):
    return cs.audit((1, '数学', 'テスト', qlatex, qimg, slatex, sja, '', ''))


def test_conclusion_before_related_section_counts_as_closed():
    """`:::conclusion` の後ろに長い「関連問題」が続いても、収束していないとは言わない。"""
    assert not any('收束' in f for f in flags(sja=CONCLUDED))


def test_summary_section_after_conclusion_also_counts():
    """`## まとめ` のように結論の後ろに結果一覧を置く体例も収束済みとみなす。"""
    doc = CONCLUDED.replace('## 関連問題', '## まとめ')
    assert not any('收束' in f for f in flags(sja=doc))


def test_container_close_is_not_dangling_punctuation():
    """末尾の `:::` は容器の閉じであって、文が途中で切れた印ではない。"""
    assert not any('悬空' in f for f in flags(sja=CONCLUDED))


def test_truly_truncated_solution_is_still_reported():
    """本当に句読点で切れている題解は今までどおり報告する。"""
    assert any('悬空' in f for f in flags(sja='## 詳細な導出\n\nしたがって次が成り立つ、'))


def test_restated_stem_in_ja_track_is_not_a_missing_stem():
    """転載できない題は日文轨の `## 問題文` に再掲する。それがあれば題面は欠けていない。"""
    notice = '(出典:某大学 2020。原題面は転載条件により掲載しません。公式アーカイブ:https://example.invalid/a.pdf)'
    restated = ('## 問題文\n\n放物線 $x+y^2-4=0$ 上に点 $(x_1,y_1)$ を、'
                '放物線 $x-y^2+4=0$ 上に点 $(x_2,y_2)$ をとる。極値を求めよ。\n\n'
                '## 方針\n\n本文。\n')
    assert not any('题面缺失' in f for f in flags(qlatex=notice, sja=restated + CONCLUDED))
    assert any('题面缺失' in f for f in flags(qlatex=notice, sja=CONCLUDED))


def test_own_question_number_is_not_a_subquestion():
    """冒頭の「問9.」は大問が原卷でもつ番号。題解が「第 9 問に答える」ことはない。"""
    assert cs.subquestions('問9. 次の問いに答えよ。\n(1) 示せ。\n(2) 求めよ。') == {'(1)', '(2)'}


def test_number_inside_a_word_is_not_a_subquestion():
    """「第1問 2次元平面において」の「問 2」を小問と読んではいけない。"""
    assert '問2' not in cs.subquestions('第1問 2次元平面において、直線を考える。')


def test_inline_enumeration_is_not_a_subquestion():
    """文中の「条件 (i)–(iii) を満たす」は設問ではなく仮定の列挙である。"""
    stem = '木は次の条件 (i)–(iii) を満たすと仮定する:(i) 各頂点が値をもつ。(ii) 葉の深さが等しい。'
    assert not {'(i)', '(ii)', '(iii)'} & cs.subquestions(stem)


def test_structural_subquestions_are_still_found():
    """行頭に立っている本物の小問は今までどおり拾う。"""
    assert cs.subquestions('以下に答えよ。\n\n(1) 示せ。\n(2) 求めよ。\n(3) 論ぜよ。') \
        == {'(1)', '(2)', '(3)'}
