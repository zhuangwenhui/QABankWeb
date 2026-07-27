"""语言盘查的判定边界。

2026-07-27 复盘:上一轮 146 条"残留"里有 96 条是规则本身在乱报 —— 自动机的状态集 $Q$
被当成有理数集、`6!=720` 的阶乘被当成不等号、`\\texttt{if (x<=0)}` 里的 C 代码被当成
数学记法、填空题的「ア」被当成日文混入中文。规则报错报到不可信,真正的问题(落单的 $)
就是这样被一起忽略掉的。

所以每条收窄都要有正反两个用例钉住:该报的仍然报,不该报的不再报。
"""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


al = _load('audit_language', 'scripts/audit_language.py')


def rules(hits):
    return {h[0] for h in hits}


# ---------------------------------------------------------------- 数学记法

@pytest.mark.parametrize('math, expect', [
    (r'$6!=720$', False),                      # 阶乘后面跟等号
    (r'$(2m)!=2^m m!\,(2m-1)!!$', False),
    (r'$\|S_j\|\!-\!=t$', False),              # \! 是负细空格
    (r'$\texttt{if (x<=0) return x;}$', False),  # \texttt 里是 C 源码
    (r'$a <= b$', True),                       # 真的该写成 \le
    (r'$x != y$', True),
])
def test_ascii_rel_only_flags_real_relations(math, expect):
    assert ('math-ascii-rel' in rules(al.check_math(math, 'ja'))) is expect


@pytest.mark.parametrize('math, expect', [
    (r'$\mbox{\texttt{| Skip -> st}}$', False),   # OCaml 源码里的 ->
    (r'$A -> B$', True),
])
def test_ascii_arrow_skips_code(math, expect):
    assert ('math-ascii-arrow' in rules(al.check_math(math, 'ja'))) is expect


@pytest.mark.parametrize('math, expect', [
    (r'$\mbox{\texttt{type exp = EInt of int}}$', False),   # OCaml 的类型名
    (r'$(min,+)$', True),                                   # (min,+) 半环,该写 \min
])
def test_op_plain_skips_code(math, expect):
    assert ('math-op-plain' in rules(al.check_math(math, 'ja'))) is expect


@pytest.mark.parametrize('math, expect', [
    # \text{} 里嵌了花括号或内层 $ 时,老正则会失配并误报。内层 $ 只在行间公式里合法:
    # 行内 `$…\text{…$x$…}…$` 前端的 protectMath 会配错定界符,那属于另一类问题。
    (r'$$\frac{\#(\text{$A$ 中の $v$ の個数})}{m}$$', False),
    (r'$$\underbrace{\text{木の構築($n$ 回の挿入)}}_{T}$$', False),
    (r'$\xrightarrow{(ア)}q_2\ (\text{自己ループ})$', True),   # \xrightarrow 的实参裸着
    (r'$0 & (その他)$', True),
])
def test_raw_cjk_understands_nested_text(math, expect):
    assert ('math-raw-cjk' in rules(al.check_math(math, 'ja'))) is expect


def test_state_set_is_not_a_number_set():
    """自动机的 $Q$、可达集 $R(s)$、连通成分 $C_i$、非终端集 $N$ 都是裸大写字母,
    但没有一个是数集。全库 85 处命中里真阳性为 0,规则已撤掉。"""
    for math in (r'$\delta:Q\times\Sigma\to Q$', r'$t\in R(s;G)$',
                 r'$C_1\to C_2\to C_3$', r'$N_1\subseteq N_3$', r'$f\in C^1(\mathbb{R})$'):
        assert 'math-bare-set' not in rules(al.check_math(math, 'ja'))


# ---------------------------------------------------------------- 定界符

def test_stray_dollar_is_reported_per_occurrence():
    """落单的 $ 要逐处报,不能每篇只报第一条 —— 漏报的那几处正是线上坏页面。"""
    doc = '**(2)** $\\displaystyle\n\\begin{cases}0\\end{cases}$\n'
    assert len(al.check_delimiters(doc)) >= 1
    assert not al.check_delimiters('文字 $a$ と $$b$$ と \\$100 と `$5`。')


# ---------------------------------------------------------------- 假名与措辞

def test_single_kana_is_a_blank_label_not_japanese():
    """東京科学大学一系的填空题用「ア」「い」当空栏记号,是原卷编号,不是日文混入。"""
    assert 'zh-kana' not in rules(al.check_zh('故 (ア) 取 $a$,(イ) 取 $b$。'))
    assert 'zh-kana' in rules(al.check_zh('这里写着ただし,是真的日文词。'))


def test_yuen_is_japanese_not_chinese_conjunction():
    """「〜する所以である」的所以是日语名词(ゆえん);句首的「所以」才是中文接续词。"""
    assert 'ja-cn-word' not in rules(al.check_ja('これが (1) を伏線とした所以である。'))
    assert 'ja-cn-word' in rules(al.check_ja('$x>0$ である。所以、結論が従う。'))


def test_hangretsu_is_dropped_because_chinese_uses_it_too():
    """中文的「行列」(行与列)与日语的「行列」(=矩阵)同形,信号太弱,已从词表撤掉。"""
    assert 'zh-ja-word' not in rules(al.check_zh('行列式挑几乎全零的行列展开。'))


def test_latin_gloss_comma_is_not_a_japanese_comma():
    """「反復補題(ポンピング補題, pumping lemma)」里的半角逗号属于那段拉丁文。"""
    doc = '定義する。\n\n:::def 反復補題(ポンピング補題, pumping lemma)\n本文である。\n'
    assert 'ja-punct-mix' not in rules(al.check_ja(doc))
    assert 'ja-punct-ascii' not in rules(al.check_ja(doc))
    assert 'ja-punct-ascii' in rules(al.check_ja('これは正しい, しかし読点が半角である。'))


def test_table_rows_are_not_prose():
    """表格单元格是并列条目,里面分隔代码片段的半角逗号不是読点。"""
    doc = 'つぎの表を見る。\n\n| 式 | 表現 |\n|---|---|\n| $e$ | `op` は `+`, `-`, `and` |\n'
    assert 'ja-punct-ascii' not in rules(al.check_ja(doc))
    assert 'ja-punct-mix' not in rules(al.check_ja(doc))
