"""学习闭环 · 掌握状态 API(set/check_batch/summary/calendar)。

覆盖:正常路径、none 删行、题目不存在 404、跨用户隔离、未登录鉴权。
"""
from datetime import date

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


# ---------------------------------------------------------------- set / check_batch

def test_set_and_check_batch(app, client, login):
    login('student', 'StudentPass123456')
    q1 = _seed_question(app)
    q2 = _seed_question(app)
    assert _set(client, q1, 'done').status_code == 200
    assert _set(client, q2, 'mastered').status_code == 200

    token = get_csrf(client)
    r = client.post('/api/progress/check_batch',
                    json={'question_ids': [q1, q2, 999999]},
                    headers={'X-CSRFToken': token})
    assert r.status_code == 200
    statuses = r.get_json()['data']['statuses']
    assert statuses[str(q1)] == 'done'
    assert statuses[str(q2)] == 'mastered'
    assert str(999999) not in statuses  # 未做的题不出现


def test_set_upsert_overwrites_status(app, client, login):
    login('student', 'StudentPass123456')
    q1 = _seed_question(app)
    _set(client, q1, 'done')
    _set(client, q1, 'mastered')  # 再设为 mastered:更新而非新增
    token = get_csrf(client)
    r = client.post('/api/progress/check_batch', json={'question_ids': [q1]},
                    headers={'X-CSRFToken': token})
    assert r.get_json()['data']['statuses'][str(q1)] == 'mastered'


def test_set_none_deletes_row(app, client, login):
    login('student', 'StudentPass123456')
    q1 = _seed_question(app)
    _set(client, q1, 'done')
    assert _set(client, q1, 'none').status_code == 200
    token = get_csrf(client)
    r = client.post('/api/progress/check_batch', json={'question_ids': [q1]},
                    headers={'X-CSRFToken': token})
    assert str(q1) not in r.get_json()['data']['statuses']  # 回到未做


def test_set_404_when_question_missing(app, client, login):
    login('student', 'StudentPass123456')
    r = _set(client, 999999, 'done')
    assert r.status_code == 404


def test_set_rejects_bad_status(app, client, login):
    login('student', 'StudentPass123456')
    q1 = _seed_question(app)
    r = _set(client, q1, 'unknown')
    assert r.status_code == 400


# ---------------------------------------------------------------- summary

def test_summary_counts_by_group(app, client, login):
    login('student', 'StudentPass123456')
    q1 = _seed_question(app, subject='微积分', difficulty='中等')
    q2 = _seed_question(app, subject='微积分', difficulty='中等')
    _seed_question(app, subject='微积分', difficulty='中等')  # 第三题未做
    _set(client, q1, 'done')
    _set(client, q2, 'mastered')

    d = client.get('/api/progress/summary').get_json()['data']
    # overall:题库 3 题,已做 2(done+mastered),已掌握 1
    assert d['overall'] == {'total': 3, 'done': 2, 'mastered': 1}
    assert d['by_difficulty']['中等'] == {'total': 3, 'done': 2, 'mastered': 1}
    assert d['by_subject']['微积分'] == {'total': 3, 'done': 2, 'mastered': 1}
    # 未涉及的难度也列出,total 反映题库(此处为 0)
    assert d['by_difficulty']['困难'] == {'total': 0, 'done': 0, 'mastered': 0}


# ---------------------------------------------------------------- calendar

def test_calendar_fills_missing_days(app, client, login):
    login('student', 'StudentPass123456')
    q1 = _seed_question(app)
    q2 = _seed_question(app)
    _set(client, q1, 'done')
    _set(client, q2, 'done')

    r = client.get('/api/progress/calendar?days=30')
    cal = r.get_json()['data']['calendar']
    assert len(cal) == 30
    assert cal[-1]['date'] == date.today().isoformat()
    assert cal[-1]['count'] == 2   # 今日 2 条进度
    assert cal[0]['count'] == 0    # 缺日补 0


# ---------------------------------------------------------------- 越权隔离

def test_progress_isolated_between_users(app, client, login):
    login('student', 'StudentPass123456')
    q1 = _seed_question(app)
    _set(client, q1, 'mastered')

    # 切到 admin:看不到 student 的进度,summary/check_batch 均为自身空
    client.get('/logout')
    login('admin', 'AdminPass123456')
    token = get_csrf(client)
    r = client.post('/api/progress/check_batch', json={'question_ids': [q1]},
                    headers={'X-CSRFToken': token})
    assert str(q1) not in r.get_json()['data']['statuses']
    d = client.get('/api/progress/summary').get_json()['data']
    assert d['overall']['done'] == 0
    assert d['overall']['mastered'] == 0


# ---------------------------------------------------------------- 鉴权

def test_progress_requires_login(client):
    assert client.get('/api/progress/summary').status_code == 401
    assert client.get('/api/progress/calendar').status_code == 401
    # 带合法 CSRF 的未登录 POST 仍应 401(而非 CSRF 400)
    token = get_csrf(client)
    r = client.post('/api/progress/set', json={'question_id': 1, 'status': 'done'},
                    headers={'X-CSRFToken': token})
    assert r.status_code == 401
