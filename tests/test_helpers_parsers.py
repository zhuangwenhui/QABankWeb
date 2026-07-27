"""api/_helpers.py 的两个 ID 解析器 —— 纯函数单测,不起 app、不连库。

这两个函数是 V1 收尾时从 7 份拷贝合并出来的(questions / error_book / progress / lists /
review 各有一套,四点语义还互相冲突)。合并前每份拷贝都记得写 `isinstance(item, bool)`;
合并后只剩一处会记得,所以这里把每条边界都钉死。

八个批量端点的入参全过这两个函数,而那些端点的写路径没有任何端点测试 —— 这份单测是
它们唯一的自动化护栏。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from api._helpers import MAX_BATCH_SIZE, parse_id_list, parse_question_id


# ------------------------------------------------------------------ parse_id_list

@pytest.mark.parametrize('value, expected', [
    ([], []),                          # 空列表**不**在解析器里判,交调用点决定答什么
    ([1], [1]),
    ([3, 1, 2], [3, 1, 2]),            # 保序
    ([2, 2, 1, 2], [2, 1]),            # 去重且保留首次出现的位置
    (['3', 4], [3, 4]),                # 数字字符串按 int 收
    ([1] * MAX_BATCH_SIZE, [1]),       # 恰好在上限:通过(去重后只剩 1 个)
])
def test_parse_id_list_accepts(value, expected):
    assert parse_id_list(value) == expected


@pytest.mark.parametrize('value, reason', [
    (None,            '不是数组'),
    ('123',           '字符串不算数组(否则会被按字符逐个吃掉)'),
    ({'a': 1},        '字典不算数组'),
    (123,             '裸整数不算数组'),
    ([0],             '0 不是正整数'),
    ([-1],            '负数不是正整数'),
    ([1, -2, 3],      '有一个非正就整体拒绝,不静默丢弃'),
    (['abc'],         '非数字字符串'),
    ([None],          'None 元素'),
    ([[1]],           '嵌套数组'),
    ([1] * (MAX_BATCH_SIZE + 1), '超出批量上限'),
])
def test_parse_id_list_rejects(value, reason):
    with pytest.raises(ValueError):
        parse_id_list(value)


@pytest.mark.parametrize('value', [[True], [False], [1, True], [True, 2]])
def test_parse_id_list_rejects_bool(value):
    """bool 是 int 的子类,不显式拦就会静静地变成题号 1 / 0。

    这是全函数最容易在重构中丢掉的一行,单独立一条。
    """
    with pytest.raises(ValueError):
        parse_id_list(value)


def test_parse_id_list_truncates_float():
    """同 parse_question_id:int(1.5) 不抛异常,小数被截断。既存行为,原样保留。"""
    assert parse_id_list([1.5, 2.9]) == [1, 2]


def test_parse_id_list_message_carries_field_name():
    """错误文案要带字段名 —— 它经 _err() 原样返回前端,由 showToast 直接显示给用户。"""
    with pytest.raises(ValueError, match='ids'):
        parse_id_list([0], 'ids')
    with pytest.raises(ValueError, match='question_ids'):
        parse_id_list([0])


def test_parse_id_list_max_size_is_overridable():
    assert parse_id_list([1, 2], max_size=2) == [1, 2]
    with pytest.raises(ValueError):
        parse_id_list([1, 2, 3], max_size=2)


# -------------------------------------------------------------- parse_question_id

@pytest.mark.parametrize('data, expected', [
    ({'question_id': 7},     7),
    ({'question_id': '7'},   7),       # 数字字符串按 int 收
    ({'question_id': 0},     None),
    ({'question_id': -1},    None),
    ({'question_id': None},  None),
    ({'question_id': 'abc'}, None),
    ({},                     None),    # 字段缺失
])
def test_parse_question_id(data, expected):
    assert parse_question_id(data) == expected


@pytest.mark.parametrize('raw, expected', [(1.5, 1), (2.9, 2), ('3', 3)])
def test_parse_question_id_truncates_float(raw, expected):
    """小数被 int() 静默截断 —— 这是合并前七份拷贝共有的既存行为,V1 收尾时原样保留。

    (合并的授权范围是"失败方式/空列表/非正数/批量上限"四点,截断不在其中;
     改它属于新增行为变更,留给 V2.0 连同入参校验一起收。)
    """
    assert parse_question_id({'question_id': raw}) == expected


@pytest.mark.parametrize('raw', [True, False])
def test_parse_question_id_rejects_bool(raw):
    """同上:{"question_id": true} 不能变成题号 1。"""
    assert parse_question_id({'question_id': raw}) is None


def test_parse_question_id_custom_field():
    assert parse_question_id({'qid': 5}, 'qid') == 5
    assert parse_question_id({'qid': 5}) is None      # 默认字段名取不到
