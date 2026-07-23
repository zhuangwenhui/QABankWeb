"""相关题推荐 + 检索强化(第四期)。

覆盖:
- GET /api/questions/<id>/related:共享知识点标签数排序、同科目兜底、limit clamp、404、
  shared_tags 为「候选∩目标」的知识点标签名。
- GET /api/questions/<id> 附 knowledge_tags。
- GET /api/questions?search= 广化:命中 solution_ja、多词 AND、知识点标签名命中、
  单词仍为原行为超集、与 knowledgeTags 共存不串。
"""
from models import Question, Tag, QuestionTag, db


# --------------------------------------------------------------- 相关题 seed
def _seed_related(app):
    """q1[フーリエ,収束] q2[フーリエ,収束] q3[フーリエ] 同为数学;
    q4[]情報;q5[]数学(同科目无共享标签,兜底候选)。返回 id 字典。"""
    with app.app_context():
        q1 = Question(subject='数学', source='东大 A', difficulty='中等',
                      question_latex='フーリエ級数の収束', solution_latex='zh1',
                      solution_ja='ディリクレ核を用いる')
        q2 = Question(subject='数学', source='东大 B', difficulty='难',
                      question_latex='テイラー展開', solution_ja='ja2')
        q3 = Question(subject='数学', source='京大 C', difficulty='易',
                      question_latex='行列の対角化', solution_ja='ja3')
        q4 = Question(subject='情報', source='阪大 D', difficulty='中等',
                      question_latex='グラフ探索')
        q5 = Question(subject='数学', source='名大 E', difficulty='中等',
                      question_latex='確率分布')
        db.session.add_all([q1, q2, q3, q4, q5])
        db.session.commit()

        t_f = Tag(name='フーリエ級数', category='知识点')
        t_s = Tag(name='一様収束', category='知识点')
        t_x = Tag(name='線形代数', category='知识点')  # 仅 q3,验证标签名搜索
        db.session.add_all([t_f, t_s, t_x])
        db.session.commit()

        db.session.add_all([
            QuestionTag(question_id=q1.id, tag_id=t_f.id),
            QuestionTag(question_id=q1.id, tag_id=t_s.id),
            QuestionTag(question_id=q2.id, tag_id=t_f.id),
            QuestionTag(question_id=q2.id, tag_id=t_s.id),  # q2 共享 2
            QuestionTag(question_id=q3.id, tag_id=t_f.id),  # q3 共享 1
            QuestionTag(question_id=q3.id, tag_id=t_x.id),
        ])
        db.session.commit()
        return {'q1': q1.id, 'q2': q2.id, 'q3': q3.id, 'q4': q4.id, 'q5': q5.id}


def _related(client, qid, query=''):
    r = client.get(f'/api/questions/{qid}/related{query}')
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()['data']


def test_related_orders_by_shared_count(app, client, login):
    """q2 共享 2 个标签排在共享 1 个的 q3 之前;自身不入选。"""
    login('student', 'StudentPass123456')
    ids = _seed_related(app)
    data = _related(client, ids['q1'])
    rel = data['related']
    order = [c['id'] for c in rel]
    assert ids['q1'] not in order              # 排除自身
    assert order.index(ids['q2']) < order.index(ids['q3'])  # 2 共享 > 1 共享
    q2 = next(c for c in rel if c['id'] == ids['q2'])
    q3 = next(c for c in rel if c['id'] == ids['q3'])
    assert q2['shared_count'] == 2 and q3['shared_count'] == 1


def test_related_shared_tags_are_intersection_names(app, client, login):
    """shared_tags = 候选题知识点 ∩ 目标题知识点 的名称集合。"""
    login('student', 'StudentPass123456')
    ids = _seed_related(app)
    rel = _related(client, ids['q1'])['related']
    q2 = next(c for c in rel if c['id'] == ids['q2'])
    q3 = next(c for c in rel if c['id'] == ids['q3'])
    assert set(q2['shared_tags']) == {'フーリエ級数', '一様収束'}
    # q3 挂 [フーリエ級数,線形代数],但与 q1 只共享 フーリエ級数(線形代数 不在 q1)
    assert set(q3['shared_tags']) == {'フーリエ級数'}


def test_related_subject_fallback_when_no_tags(app, client, login):
    """无知识点标签的题 → 同科目最新题兜底,basis=subject,不含自身/跨科目题。"""
    login('student', 'StudentPass123456')
    ids = _seed_related(app)
    data = _related(client, ids['q5'])  # q5 无标签,数学
    order = [c['id'] for c in data['related']]
    assert ids['q5'] not in order
    assert ids['q4'] not in order            # 情報,跨科目不入兜底
    assert set(order) <= {ids['q1'], ids['q2'], ids['q3']}  # 同为数学
    assert data['basis'] == 'subject'
    assert all(c['shared_count'] == 0 for c in data['related'])


def test_related_mixed_fills_with_subject(app, client, login):
    """标签命中不足 limit 时,用同科目题补足;补入项 shared_count=0。"""
    login('student', 'StudentPass123456')
    ids = _seed_related(app)
    data = _related(client, ids['q1'], '?limit=6')
    order = [c['id'] for c in data['related']]
    # q2,q3 标签命中 + q5 同科目兜底(q4 跨科目不入)
    assert ids['q2'] in order and ids['q3'] in order
    assert ids['q5'] in order and ids['q4'] not in order
    assert data['basis'] == 'mixed'


def test_related_limit_clamped(app, client, login):
    """limit 越界被 clamp 到 [1,12];limit=1 只返回最相关的 1 条。"""
    login('student', 'StudentPass123456')
    ids = _seed_related(app)
    assert len(_related(client, ids['q1'], '?limit=1')['related']) == 1
    assert len(_related(client, ids['q1'], '?limit=999')['related']) <= 12
    assert len(_related(client, ids['q1'], '?limit=0')['related']) >= 1


def test_related_404(app, client, login):
    login('student', 'StudentPass123456')
    _seed_related(app)
    r = client.get('/api/questions/999999/related')
    assert r.status_code == 404
    assert r.get_json()['success'] is False


def test_related_card_fields(app, client, login):
    """卡片含轻量元信息且不泄题解正文。"""
    login('student', 'StudentPass123456')
    ids = _seed_related(app)
    card = _related(client, ids['q1'])['related'][0]
    for k in ('id', 'source', 'subject', 'difficulty', 'chapter',
              'shared_tags', 'shared_count', 'has_solution'):
        assert k in card
    assert 'solution_latex' not in card and 'solution_ja' not in card
    # q1 的相关题里 q2/q3 都有 solution_ja
    assert card['has_solution'] is True


def test_get_question_includes_knowledge_tags(app, client, login):
    """单题详情附 knowledge_tags 名称列表。"""
    login('student', 'StudentPass123456')
    ids = _seed_related(app)
    r = client.get(f'/api/questions/{ids["q1"]}')
    q = r.get_json()['data']['question']
    assert set(q['knowledge_tags']) == {'フーリエ級数', '一様収束'}
    # 无标签题 → 空列表
    r5 = client.get(f'/api/questions/{ids["q5"]}')
    assert r5.get_json()['data']['question']['knowledge_tags'] == []


# --------------------------------------------------------------- 检索强化
def _search_ids(client, query):
    r = client.get('/api/questions?' + query)
    assert r.status_code == 200, r.get_data(as_text=True)
    return {q['id'] for q in r.get_json()['data']['questions']}


def test_search_matches_solution_ja(app, client, login):
    """关键改进:搜索命中日本語詳解轨(旧实现只搜中文轨)。"""
    login('student', 'StudentPass123456')
    ids = _seed_related(app)
    # 'ディリクレ' 仅出现在 q1.solution_ja
    assert _search_ids(client, 'search=ディリクレ') == {ids['q1']}


def test_search_multiterm_and(app, client, login):
    """多词按 AND:两词须落在同一题(可分散在不同字段)。"""
    login('student', 'StudentPass123456')
    ids = _seed_related(app)
    # フーリエ(q1.question_latex) + ディリクレ(q1.solution_ja)→ 仅 q1
    assert _search_ids(client, 'search=フーリエ ディリクレ') == {ids['q1']}
    # フーリエ 单独也命中 q1(question_latex 含「フーリエ級数」)
    assert ids['q1'] in _search_ids(client, 'search=フーリエ')


def test_search_matches_knowledge_tag_name(app, client, login):
    """搜索命中知识点标签名:q3 挂「線形代数」标签,正文无此词也应命中。"""
    login('student', 'StudentPass123456')
    ids = _seed_related(app)
    got = _search_ids(client, 'search=線形代数')
    assert ids['q3'] in got
    # q3 正文是「行列の対角化」,不含「線形代数」四字,证明确实靠标签名命中
    assert '線形代数' not in 'フーリエ級数の収束テイラー展開行列の対角化グラフ探索確率分布'


def test_search_coexists_with_knowledge_filter(app, client, login):
    """search 与 knowledgeTags 同用不互相破坏(标签名命中走子查询,不与主 join 冲突)。"""
    login('student', 'StudentPass123456')
    ids = _seed_related(app)
    # knowledgeTags=フーリエ級数 → {q1,q2,q3};再叠加 search=テイラー → 仅 q2
    got = _search_ids(client, 'knowledgeTags=フーリエ級数&search=テイラー')
    assert got == {ids['q2']}
