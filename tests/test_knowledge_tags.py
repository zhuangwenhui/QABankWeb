"""内容发现 · 规范化知识点标签(独立于 Question.tags 的自由 JSON 标签)。

覆盖:
- GET /api/questions?knowledgeTags=... 的 any(默认)/ all(tagMode)两种命中语义;
- 仅在 knowledgeTags 非空时才 join,空参数不影响原有计数/分页;
- GET /api/questions/tag_facets 按 category 分组、每标签带被引用题数。

用例:题1=[线性代数, 特征值](category 知识点)、题2=[线性代数]、题3=[概率]。
"""
from models import Question, Tag, QuestionTag, db


def _seed(app):
    """建 3 题并挂知识点标签,返回 (q1, q2, q3) 的 id。"""
    with app.app_context():
        q1 = Question(subject='线性代数', difficulty='中等', question_latex='a')
        q2 = Question(subject='线性代数', difficulty='中等', question_latex='b')
        q3 = Question(subject='概率统计', difficulty='中等', question_latex='c')
        db.session.add_all([q1, q2, q3])
        db.session.commit()

        t_la = Tag(name='线性代数', category='知识点')
        t_ev = Tag(name='特征值', category='知识点')
        t_pr = Tag(name='概率', category='概率论')
        db.session.add_all([t_la, t_ev, t_pr])
        db.session.commit()

        db.session.add_all([
            QuestionTag(question_id=q1.id, tag_id=t_la.id),
            QuestionTag(question_id=q1.id, tag_id=t_ev.id),
            QuestionTag(question_id=q2.id, tag_id=t_la.id),
            QuestionTag(question_id=q3.id, tag_id=t_pr.id),
        ])
        db.session.commit()
        return q1.id, q2.id, q3.id


def _ids(client, query):
    r = client.get('/api/questions' + query)
    assert r.status_code == 200, r.get_data(as_text=True)
    return {q['id'] for q in r.get_json()['data']['questions']}


def test_knowledge_tags_any_mode(app, client, login):
    """默认 any:命中任一标签即入选。线性代数 → 题1、题2。"""
    login('student', 'StudentPass123456')
    q1, q2, q3 = _seed(app)
    assert _ids(client, '?knowledgeTags=线性代数') == {q1, q2}


def test_knowledge_tags_all_mode(app, client, login):
    """tagMode=all:须同时命中全部标签。线性代数+特征值 → 仅题1。"""
    login('student', 'StudentPass123456')
    q1, q2, q3 = _seed(app)
    assert _ids(client, '?knowledgeTags=线性代数,特征值&tagMode=all') == {q1}


def test_knowledge_tags_any_multiple(app, client, login):
    """any 多标签取并集且去重(题1 同时挂两标签不应重复计入)。"""
    login('student', 'StudentPass123456')
    q1, q2, q3 = _seed(app)
    r = client.get('/api/questions?knowledgeTags=线性代数,概率')
    data = r.get_json()['data']
    assert {q['id'] for q in data['questions']} == {q1, q2, q3}
    assert data['total'] == 3  # distinct,题1不因两标签重复计数


def test_knowledge_tags_empty_noop(app, client, login):
    """空 knowledgeTags 不 join、不影响原查询:返回全部 3 题。"""
    login('student', 'StudentPass123456')
    q1, q2, q3 = _seed(app)
    assert _ids(client, '') == {q1, q2, q3}
    assert _ids(client, '?knowledgeTags=') == {q1, q2, q3}


def test_knowledge_tags_all_unmatched(app, client, login):
    """all 模式下某标签无题命中 → 结果为空。"""
    login('student', 'StudentPass123456')
    _seed(app)
    assert _ids(client, '?knowledgeTags=线性代数,不存在的标签&tagMode=all') == set()


def test_tag_facets(app, client, login):
    """tag_facets 按 category 分组,每标签带被引用题数。"""
    login('student', 'StudentPass123456')
    _seed(app)
    r = client.get('/api/questions/tag_facets')
    assert r.status_code == 200
    cats = r.get_json()['data']['categories']
    # 展平成 {(category, name): count} 便于断言
    flat = {}
    for c in cats:
        for t in c['tags']:
            flat[(c['category'], t['name'])] = t['count']
    assert flat[('知识点', '线性代数')] == 2
    assert flat[('知识点', '特征值')] == 1
    assert flat[('概率论', '概率')] == 1
    # category 分组齐全
    assert {c['category'] for c in cats} == {'知识点', '概率论'}


def test_tag_facets_empty(app, client, login):
    """空标签库:categories 为空数组。"""
    login('student', 'StudentPass123456')
    r = client.get('/api/questions/tag_facets')
    assert r.status_code == 200
    assert r.get_json()['data']['categories'] == []
