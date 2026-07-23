"""个人学习工具:私人笔记 + 收藏书签。"""
from conftest import get_csrf
from models import Question, db


def _seed(app, n=3):
    with app.app_context():
        qs = [Question(subject='数学', difficulty='中等', question_latex='q%d' % i) for i in range(n)]
        db.session.add_all(qs)
        db.session.commit()
        return [q.id for q in qs]


def _hdr(client):
    return {'X-CSRFToken': get_csrf(client)}


# ---------------------------------------------------------------- 笔记
def test_note_upsert_and_get(app, client, login):
    login('student', 'StudentPass123456')
    qid = _seed(app)[0]
    assert client.get(f'/api/questions/{qid}/note').get_json()['data']['content'] == ''
    r = client.put(f'/api/questions/{qid}/note', json={'content': '我的思路:分部积分'}, headers=_hdr(client))
    assert r.status_code == 200
    assert client.get(f'/api/questions/{qid}/note').get_json()['data']['content'] == '我的思路:分部积分'
    # 再 PUT 覆盖
    client.put(f'/api/questions/{qid}/note', json={'content': '改进版'}, headers=_hdr(client))
    assert client.get(f'/api/questions/{qid}/note').get_json()['data']['content'] == '改进版'


def test_note_question_404(app, client, login):
    login('student', 'StudentPass123456')
    _seed(app)
    r = client.put('/api/questions/999999/note', json={'content': 'x'}, headers=_hdr(client))
    assert r.status_code == 404


def test_note_too_long(app, client, login):
    login('student', 'StudentPass123456')
    qid = _seed(app)[0]
    r = client.put(f'/api/questions/{qid}/note', json={'content': 'x' * 20001}, headers=_hdr(client))
    assert r.status_code == 400


def test_note_owner_isolation(app, client, login):
    login('student', 'StudentPass123456')
    qid = _seed(app)[0]
    client.put(f'/api/questions/{qid}/note', json={'content': 'student 私密'}, headers=_hdr(client))
    client.get('/logout')
    login('admin', 'AdminPass123456')
    assert client.get(f'/api/questions/{qid}/note').get_json()['data']['content'] == ''


# ---------------------------------------------------------------- 收藏
def test_bookmark_toggle(app, client, login):
    login('student', 'StudentPass123456')
    qid = _seed(app)[0]
    assert client.get(f'/api/questions/{qid}/bookmark').get_json()['data']['bookmarked'] is False
    r = client.post(f'/api/questions/{qid}/bookmark', headers=_hdr(client))
    assert r.get_json()['data']['bookmarked'] is True
    assert client.get(f'/api/questions/{qid}/bookmark').get_json()['data']['bookmarked'] is True
    # 再 toggle 取消
    assert client.post(f'/api/questions/{qid}/bookmark', headers=_hdr(client)).get_json()['data']['bookmarked'] is False


def test_bookmark_404(app, client, login):
    login('student', 'StudentPass123456')
    _seed(app)
    assert client.post('/api/questions/999999/bookmark', headers=_hdr(client)).status_code == 404


def test_bookmarks_list_and_filter(app, client, login):
    login('student', 'StudentPass123456')
    q1, q2, q3 = _seed(app, 3)
    client.post(f'/api/questions/{q1}/bookmark', headers=_hdr(client))
    client.post(f'/api/questions/{q3}/bookmark', headers=_hdr(client))
    ids = client.get('/api/bookmarks').get_json()['data']['question_ids']
    assert set(ids) == {q1, q3}
    # 列表页 bookmarked=1 只回收藏
    r = client.get('/api/questions?bookmarked=1')
    got = {q['id'] for q in r.get_json()['data']['questions']}
    assert got == {q1, q3}


def test_bookmark_owner_isolation(app, client, login):
    login('student', 'StudentPass123456')
    qid = _seed(app)[0]
    client.post(f'/api/questions/{qid}/bookmark', headers=_hdr(client))
    client.get('/logout')
    login('admin', 'AdminPass123456')
    assert client.get('/api/bookmarks').get_json()['data']['question_ids'] == []
    assert client.get(f'/api/questions/{qid}/bookmark').get_json()['data']['bookmarked'] is False
