"""SPEC.md §2 与实际路由表的一致性护栏。

写错的文档比没有文档更坏 —— 后来人照着它做出错误假设,而代码不会因此变红。
这里把两件事钉死:

  · 每条 /api 路由都必须在 SPEC §2 里出现(漏写会被发现);
  · SPEC §2 里写到的 /api 路由都必须真实存在(删了接口忘了删文档会被发现)。

只比对**路由是否被提及**,不比对请求/响应字段 —— 那部分靠人读代码写,机器验不了,
但至少能保证"有没有这条路由"这一层不会悄悄漂移。
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _spec_section_2():
    """取 SPEC.md 的 §2 全文(到 §3 为止)。"""
    text = (ROOT / 'SPEC.md').read_text(encoding='utf-8')
    start = text.index('## 2. 接口契约')
    end = text.index('## 3. 页面契约')
    return text[start:end]


def _api_rules(app):
    return [r for r in app.url_map.iter_rules() if r.rule.startswith('/api')]


def _rule_to_pattern(rule):
    """把 `/api/x/<int:qid>` 变成能匹配文档写法的正则。

    文档里参数段原样写作 `<int:qid>`,但也允许写成别的占位;这里统一放宽成
    「一段非斜杠内容」,避免文档为了通过测试被迫抄写 Flask 的类型标注。
    """
    tmp = re.sub(r'<[^>]*>', '\x00', rule)
    return re.escape(tmp).replace('\x00', r'[^/\s`|]+')


def test_every_api_route_is_documented(app):
    spec = _spec_section_2()
    missing = []
    for rule in sorted(_api_rules(app), key=lambda r: r.rule):
        if not re.search(_rule_to_pattern(rule.rule), spec):
            methods = ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
            missing.append(f'{methods:12s} {rule.rule}')
    assert not missing, (
        'SPEC.md §2 没有记录这些路由(新增接口时请同步补写):\n  '
        + '\n  '.join(missing))


def test_spec_documents_no_dead_routes(app):
    """SPEC §2 里出现的 /api 路径必须真的存在。"""
    spec = _spec_section_2()
    live = {r.rule for r in _api_rules(app)}
    live_patterns = [re.compile('^' + _rule_to_pattern(r) + '$') for r in live]

    # 只取表格里反引号包起来的路径,避开正文中的散文引用
    documented = set(re.findall(r'`(/api/[^`\s]*)`', spec))
    dead = [p for p in sorted(documented)
            if not any(pat.match(p) for pat in live_patterns)]
    assert not dead, (
        'SPEC.md §2 写了这些路由,但 url_map 里没有(接口删改后请同步):\n  '
        + '\n  '.join(dead))


@pytest.mark.parametrize('heading', [
    '### 2.6 题单模块',
    '### 2.7 个人学习工具',
    '### 2.8 学习进度',
    '### 2.9 复习队列',
    '### 2.10 作答提交与采点',
])
def test_late_modules_have_a_section(heading):
    """这五节是 2026-07-28 才补的;删掉任何一节都要立刻发现。

    尤其 §2.10 —— V2 自动判题的契约就写在那儿。
    """
    assert heading in _spec_section_2(), f'SPEC.md §2 里少了「{heading}」'
