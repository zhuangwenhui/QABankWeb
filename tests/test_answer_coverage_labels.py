"""小问编号的等价写法。

盘查只在"题面里有、题解里一次都没出现"时才报。它认得的写法太窄就会一路误报:
2026-07-27 中文轨的 35 处"未答"逐条查下来**一处真漏答都没有** —— 全是写法不同
(`问2`、`小问4`、`(1a)`、`**2)**`)。误报多了这条盘查就没人看了,所以把这些等价写法
钉在这里。

反面同样要钉住:`### 1 求行列式` 这种**标题序号**不能算,它是解题步骤的序号,
与小问并非一一对应;认了以后盘查就永远全绿,等于没有。
"""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'audit_answer_coverage', ROOT / 'scripts/audit_answer_coverage.py')
cov = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cov)


@pytest.mark.parametrize('text', [
    '于是 (2) 得证。',
    '于是 [2] 得证。',
    '設問2 の答えは 3 である。',
    '問2 の答えは 3 である。',
    '**问2** 的答案是 3。',
    '### 6 差不封闭(小问2)',
    '第 2 问的答案是 3。',
    '### 2a 频域微分',          # (2a)(2b) 合写,覆盖 (2)
    '- **2)** 边界填 $1$。',    # 结构位置上的 2)
])
def test_equivalent_labels_count_as_answered(text):
    assert cov.has_num(2, text), text


@pytest.mark.parametrize('text', [
    '### 2 相加消一阶项',        # 步骤序号,不是小问编号
    '取 $x_2$ 与 $y_2$ 代入。',
    '共 $\\binom{7}{3}=35$ 种。',
])
def test_step_numbers_do_not_count(text):
    assert not cov.has_num(2, text), text


def test_stem_own_number_is_not_a_subquestion():
    """开头的「問9.」是这道大题在原卷里的编号,题解不会去"答第 9 问"。"""
    nums, _ = cov.stem_labels('問9. 次の問いに答えよ。\n(1) 示せ。\n(2) 求めよ。')
    assert nums == [1, 2]
