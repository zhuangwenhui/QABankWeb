"""学习闭环 · 列表页掌握状态筛选(GET /api/questions?masteryStatus=)。

覆盖:new(无进度行)/ done(含 mastered)/ mastered 三档,以当前用户的
question_progress outer join 过滤。用例:题1=done、题2=mastered、题3=未做。
"""
from conftest import get_csrf
from models import Question, db


def _seed_question(app, subject='微积分', difficulty='中等'):
    with app.app_context():
        q = Question(subject=subject, difficulty=difficulty, question_latex='x')
        db.session.add(q)
        db.session.commit()
        return q.id


def _set(client, qid, status):
    token = get_csrf(client)
    return client.post('/api/progress/set', json={'question_id': qid, 'status': status},
                       headers={'X-CSRFToken': token})


def _list_ids(client, mastery):
    r = client.get('/api/questions?masteryStatus=' + mastery)
    assert r.status_code == 200
    return {q['id'] for q in r.get_json()['data']['questions']}


def test_mastery_status_filter(app, client, login):
    login('student', 'StudentPass123456')
    q1 = _seed_question(app)
    q2 = _seed_question(app)
    q3 = _seed_question(app)
    assert _set(client, q1, 'done').status_code == 200
    assert _set(client, q2, 'mastered').status_code == 200
    # q3 保持未做

    assert _list_ids(client, 'new') == {q3}
    assert _list_ids(client, 'done') == {q1, q2}
    assert _list_ids(client, 'mastered') == {q2}


def test_mastery_status_is_per_user(app, client, login):
    """掌握状态按当前用户隔离:student 的进度不应影响 admin 的筛选。"""
    login('student', 'StudentPass123456')
    q1 = _seed_question(app)
    q2 = _seed_question(app)
    _set(client, q1, 'done')
    _set(client, q2, 'mastered')

    client.get('/logout')  # 已登录时 /login 会重定向,须先退出才能切换用户
    login('admin', 'AdminPass123456')
    # admin 无任何进度:new 应返回全部两题,done/mastered 均为空
    assert _list_ids(client, 'new') == {q1, q2}
    assert _list_ids(client, 'done') == set()
    assert _list_ids(client, 'mastered') == set()
