"""学习闭环 · 复习队列 API + SM-2 间隔调度。

覆盖:sm2_schedule 纯函数(连击递增/ease 边界/interval 递增/again 归零/非法评级),
以及 due/rate/stats 流程(加入错题→到期→rate good→推后→不再到期)。
"""
import pytest

from conftest import get_csrf
from api.review import sm2_schedule
from models import Question, db


def _seed_question(app, subject='微积分', difficulty='中等'):
    """直接落库一道题,返回其 id(学生态无法走建题 API,故用 db 直插)。"""
    with app.app_context():
        q = Question(subject=subject, difficulty=difficulty, question_latex='x')
        db.session.add(q)
        db.session.commit()
        return q.id


def _add_to_error_book(client, qid):
    token = get_csrf(client)
    return client.post('/api/error_book/add', json={'question_id': qid},
                       headers={'X-CSRFToken': token})


# ---------------------------------------------------------------- SM-2 纯函数

def test_sm2_good_progression():
    """good 连击:首答=1天/reps1,次答=6天/reps2,再答=interval*ease。"""
    ease, iv, reps = sm2_schedule('good', None, None, None)
    assert (iv, reps) == (1, 1)
    assert ease == 2.5
    ease, iv, reps = sm2_schedule('good', 2.5, 1, 1)
    assert (iv, reps) == (6, 2)
    ease, iv, reps = sm2_schedule('good', 2.5, 6, 2)
    assert iv == round(6 * 2.5)  # 15
    assert reps == 3
    assert ease == 2.5  # good 不改 ease


def test_sm2_good_interval_strictly_increasing():
    """good 连续复习,间隔严格递增。"""
    _, i0, _ = sm2_schedule('good', 2.5, 0, 0)
    _, i1, _ = sm2_schedule('good', 2.5, i0, 1)
    _, i2, _ = sm2_schedule('good', 2.5, i1, 2)
    _, i3, _ = sm2_schedule('good', 2.5, i2, 3)
    assert i0 < i1 < i2 < i3


def test_sm2_again_resets():
    """again:连击与间隔归零、当日再来,ease 下调 0.20。"""
    ease, iv, reps = sm2_schedule('again', 2.5, 15, 3)
    assert (iv, reps) == (0, 0)
    assert ease == pytest.approx(2.30)


def test_sm2_ease_lower_bound():
    """ease 下限 1.3:again/hard 不会把 ease 压到 1.3 以下。"""
    ease, _, _ = sm2_schedule('again', 1.3, 5, 2)
    assert ease == 1.3  # max(1.3, 1.10)
    ease, _, _ = sm2_schedule('hard', 1.4, 5, 2)
    assert ease == 1.3  # max(1.3, 1.25)


def test_sm2_easy_increases_but_caps_at_3():
    """easy:ease 上调 0.15 且不超过 3.0;间隔更激进。"""
    ease, iv, reps = sm2_schedule('easy', 2.5, 6, 2)
    assert ease == pytest.approx(2.65)
    assert iv == round(6 * 2.5 * 1.3)  # 20
    assert reps == 3
    ease, _, _ = sm2_schedule('easy', 2.95, 6, 2)
    assert ease == 3.0  # min(3.0, 3.10)


def test_sm2_hard_shrinks_and_increments():
    """hard:ease 略降,连击仍 +1,间隔前两次固定 1/3。"""
    ease, iv, reps = sm2_schedule('hard', 2.5, 6, 2)
    assert ease == pytest.approx(2.35)
    assert iv == max(1, round(6 * 1.2))  # 7
    assert reps == 3
    assert sm2_schedule('hard', 2.5, 0, 0)[1] == 1
    assert sm2_schedule('hard', 2.5, 1, 1)[1] == 3


def test_sm2_bad_rating_raises():
    with pytest.raises(ValueError):
        sm2_schedule('perfect', 2.5, 1, 1)


# ---------------------------------------------------------------- due/rate/stats 流程

def test_review_flow_due_rate_pushes_out(app, client, login):
    """加入错题→在 due 中→rate good→due_at 推后→不再在 due。"""
    login('student', 'StudentPass123456')
    qid = _seed_question(app)
    assert _add_to_error_book(client, qid).status_code == 200

    # 未排期(due_at NULL)即立即到期
    r = client.get('/api/review/due')
    assert r.status_code == 200
    entries = r.get_json()['data']['entries']
    assert qid in [e['question_id'] for e in entries]
    # 到期项带 error_book_id 与题目
    row = next(e for e in entries if e['question_id'] == qid)
    assert 'error_book_id' in row
    assert row['question']['id'] == qid

    # rate good:首答 → 间隔 1 天、reps 1
    token = get_csrf(client)
    r = client.post('/api/review/rate', json={'question_id': qid, 'rating': 'good'},
                    headers={'X-CSRFToken': token})
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()['data']
    assert data['interval_days'] == 1
    assert data['repetitions'] == 1
    assert data['due_at'] is not None

    # 推后到明天 → 不再在到期队列
    r = client.get('/api/review/due')
    assert qid not in [e['question_id'] for e in r.get_json()['data']['entries']]


def test_review_stats_shifts_after_rating(app, client, login):
    """rate 前 due_today 计入(NULL);rate good 后转入 upcoming_7d。"""
    login('student', 'StudentPass123456')
    qid = _seed_question(app)
    _add_to_error_book(client, qid)

    r = client.get('/api/review/stats')
    d = r.get_json()['data']
    assert d['due_today'] == 1
    assert d['total_in_review'] == 1

    token = get_csrf(client)
    client.post('/api/review/rate', json={'question_id': qid, 'rating': 'good'},
                headers={'X-CSRFToken': token})
    d = client.get('/api/review/stats').get_json()['data']
    assert d['due_today'] == 0
    assert d['upcoming_7d'] == 1
    assert d['total_in_review'] == 1


def test_rate_404_when_not_in_error_book(app, client, login):
    login('student', 'StudentPass123456')
    qid = _seed_question(app)  # 未加入错题本
    token = get_csrf(client)
    r = client.post('/api/review/rate', json={'question_id': qid, 'rating': 'good'},
                    headers={'X-CSRFToken': token})
    assert r.status_code == 404


def test_rate_rejects_bad_rating(app, client, login):
    login('student', 'StudentPass123456')
    qid = _seed_question(app)
    _add_to_error_book(client, qid)
    token = get_csrf(client)
    r = client.post('/api/review/rate', json={'question_id': qid, 'rating': 'perfect'},
                    headers={'X-CSRFToken': token})
    assert r.status_code == 400


def test_review_isolated_between_users(app, client, login):
    """一个用户的错题不进入另一个用户的复习队列。"""
    login('student', 'StudentPass123456')
    qid = _seed_question(app)
    _add_to_error_book(client, qid)

    client.get('/logout')
    login('admin', 'AdminPass123456')
    r = client.get('/api/review/due')
    assert qid not in [e['question_id'] for e in r.get_json()['data']['entries']]
    assert client.get('/api/review/stats').get_json()['data']['total_in_review'] == 0


def test_review_requires_login(client):
    assert client.get('/api/review/due').status_code == 401
    assert client.get('/api/review/stats').status_code == 401
