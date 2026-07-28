"""错题本的批量与备注接口:add_batch / check_batch / remove / stats / update_notes。

这五个端点此前**零测试覆盖**,而它们是全站唯一会批量增删用户数据的地方。
V2.0 的自动判题要往这块的邻居表(answer_submissions)写数据,先把这层的行为钉住。

重点钉三件容易悄悄漂移的事:
  1. 属主隔离 —— 每个端点都只能看见/改动 g.user 自己的错题;
  2. 空列表的两种待遇 —— add_batch 报错、check_batch 回空结果(前者是误操作,
     后者是列表页渲染完回填书签的常态,报错会在控制台刷红);
  3. 计数语义 —— added/skipped/removed 各自数的是什么。
"""
from conftest import get_csrf
from models import ErrorBook, Question, User, db


def _seed(subjects=('微积分', '微积分', '线性代数')):
    """按给定科目序列建题,返回 id 列表(顺序与入参一致)。"""
    ids = []
    for i, subject in enumerate(subjects):
        q = Question(subject=subject, chapter='ch', difficulty='中等',
                     source=f'src{i}', question_latex=f'q{i}')
        db.session.add(q)
        db.session.flush()
        ids.append(q.id)
    db.session.commit()
    return ids


def _post(client, path, payload, token):
    return client.post(path, json=payload, headers={'X-CSRFToken': token})


def _other_user_entry(app, qid):
    """以 admin 的身份往错题本塞一条,用来验证 student 看不见、也动不了它。"""
    with app.app_context():
        admin = User.query.filter_by(username='admin').one()
        db.session.add(ErrorBook(user_id=admin.id, question_id=qid, notes='admin 的备注'))
        db.session.commit()


# --------------------------------------------------------------- add_batch
def test_add_batch_counts_added_and_skipped(app, client, login):
    with app.app_context():
        ids = _seed()
    login('student', 'StudentPass123456')
    token = get_csrf(client)

    # 混入一个不存在的题号:它应计入 skipped 而不是让整批失败
    r = _post(client, '/api/error_book/add_batch',
              {'question_ids': ids + [999999]}, token)
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()['data']
    assert data['added'] == 3 and data['skipped'] == 1
    assert r.get_json()['message'] == '已加入 3 题,跳过 1 题'


def test_add_batch_is_idempotent(app, client, login):
    with app.app_context():
        ids = _seed()
    login('student', 'StudentPass123456')
    token = get_csrf(client)

    _post(client, '/api/error_book/add_batch', {'question_ids': ids}, token)
    again = _post(client, '/api/error_book/add_batch', {'question_ids': ids}, token)
    data = again.get_json()['data']
    assert data['added'] == 0 and data['skipped'] == 3
    with app.app_context():
        assert ErrorBook.query.count() == 3      # 没有重复插入


def test_add_batch_dedups_repeated_ids(app, client, login):
    """同一个 id 在入参里出现多次只算一次 —— 去重发生在 parse_id_list。"""
    with app.app_context():
        ids = _seed(('微积分',))
    login('student', 'StudentPass123456')
    token = get_csrf(client)

    r = _post(client, '/api/error_book/add_batch',
              {'question_ids': [ids[0], ids[0], ids[0]]}, token)
    data = r.get_json()['data']
    assert data['added'] == 1 and data['skipped'] == 0


def test_add_batch_rejects_empty_and_malformed(app, client, login):
    login('student', 'StudentPass123456')
    token = get_csrf(client)

    empty = _post(client, '/api/error_book/add_batch', {'question_ids': []}, token)
    assert empty.status_code == 400
    assert empty.get_json()['error'] == 'question_ids 不能为空'

    not_a_list = _post(client, '/api/error_book/add_batch', {'question_ids': 'abc'}, token)
    assert not_a_list.status_code == 400
    assert 'question_ids 必须为数组' in not_a_list.get_json()['error']

    bad_item = _post(client, '/api/error_book/add_batch', {'question_ids': [0]}, token)
    assert bad_item.status_code == 400


def test_add_batch_writes_to_current_user_only(app, client, login):
    with app.app_context():
        ids = _seed(('微积分',))
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    _post(client, '/api/error_book/add_batch', {'question_ids': ids}, token)

    with app.app_context():
        student = User.query.filter_by(username='student').one()
        rows = ErrorBook.query.all()
        assert len(rows) == 1 and rows[0].user_id == student.id


# --------------------------------------------------------------- check_batch
def test_check_batch_returns_only_own_entries(app, client, login):
    with app.app_context():
        ids = _seed()
    _other_user_entry(app, ids[0])           # 这条属于 admin
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    _post(client, '/api/error_book/add_batch', {'question_ids': [ids[1]]}, token)

    r = _post(client, '/api/error_book/check_batch', {'question_ids': ids}, token)
    assert r.status_code == 200
    # 只回 student 自己加的那道,admin 那条不能泄露出来
    assert r.get_json()['data']['in_error_book'] == [ids[1]]


def test_check_batch_empty_list_is_ok_not_error(app, client, login):
    """空列表回 200 空结果,不是 400 —— 列表页为空时回填书签是常态,报错会刷红控制台。"""
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    r = _post(client, '/api/error_book/check_batch', {'question_ids': []}, token)
    assert r.status_code == 200
    assert r.get_json()['data']['in_error_book'] == []


def test_check_batch_rejects_malformed(app, client, login):
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    r = _post(client, '/api/error_book/check_batch', {'question_ids': {'a': 1}}, token)
    assert r.status_code == 400


# --------------------------------------------------------------- remove
def test_remove_accepts_both_single_and_batch_form(app, client, login):
    with app.app_context():
        ids = _seed()
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    _post(client, '/api/error_book/add_batch', {'question_ids': ids}, token)

    single = _post(client, '/api/error_book/remove', {'question_id': ids[0]}, token)
    assert single.get_json()['data']['removed'] == 1

    batch = _post(client, '/api/error_book/remove',
                  {'question_ids': [ids[1], ids[2]]}, token)
    assert batch.get_json()['data']['removed'] == 2
    with app.app_context():
        assert ErrorBook.query.count() == 0


def test_remove_counts_only_rows_actually_deleted(app, client, login):
    """移出一道本来就不在错题本里的题:不报错,removed 计 0。"""
    with app.app_context():
        ids = _seed(('微积分',))
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    r = _post(client, '/api/error_book/remove', {'question_id': ids[0]}, token)
    assert r.status_code == 200
    assert r.get_json()['data']['removed'] == 0


def test_remove_cannot_touch_another_users_entry(app, client, login):
    with app.app_context():
        ids = _seed(('微积分',))
    _other_user_entry(app, ids[0])
    login('student', 'StudentPass123456')
    token = get_csrf(client)

    r = _post(client, '/api/error_book/remove', {'question_id': ids[0]}, token)
    assert r.get_json()['data']['removed'] == 0
    with app.app_context():
        assert ErrorBook.query.count() == 1        # admin 那条还在


def test_remove_requires_some_id(app, client, login):
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    r = _post(client, '/api/error_book/remove', {}, token)
    assert r.status_code == 400
    assert r.get_json()['error'] == '缺少 question_id 或 question_ids 参数'

    empty = _post(client, '/api/error_book/remove', {'question_ids': []}, token)
    assert empty.status_code == 400
    assert empty.get_json()['error'] == 'question_ids 不能为空'


# --------------------------------------------------------------- stats
def test_stats_counts_by_subject(app, client, login):
    with app.app_context():
        ids = _seed(('微积分', '微积分', '线性代数'))
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    _post(client, '/api/error_book/add_batch', {'question_ids': ids}, token)

    data = client.get('/api/error_book/stats').get_json()['data']
    assert data['total'] == 3
    assert data['by_subject'] == {'微积分': 2, '线性代数': 1}


def test_stats_includes_subject_outside_the_enum(app, client, login):
    """课程枚举之外的科目也要计入 —— 老数据里有 config.SUBJECTS 没有的值。"""
    with app.app_context():
        ids = _seed(('微积分', '天文学'))
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    _post(client, '/api/error_book/add_batch', {'question_ids': ids}, token)

    data = client.get('/api/error_book/stats').get_json()['data']
    assert data['total'] == 2
    assert data['by_subject'] == {'微积分': 1, '天文学': 1}


def test_stats_subject_order_is_not_the_configured_one(app, client, login):
    """⚠ 钉住一个反直觉的事实:by_subject 的顺序**不是** config.SUBJECTS。

    `stats()` 里那段"先按 config.SUBJECTS 排、枚举外的再兜底追加"的代码,在 HTTP 响应里
    没有任何可观测效果 —— Flask 的 `app.json.sort_keys` 默认为 True,序列化时会把 key
    按码点重排,handler 精心排好的顺序被原样丢掉。

    后果是错题本页(`error_book.js:renderSubjectStats` 直接 `Object.entries`)按码点顺序
    显示学科,而题目管理页(`questions.js:ppGroupHtml` 显式传 `CFG.subjects`)按课程顺序
    显示 —— 同一份学科分布,两个页面两种排法。

    这条测试**不是**在认可现状,而是防止有人只改 handler 就以为修好了:真要修,
    要么在前端传定序(照 ppGroupHtml 的做法),要么把 by_subject 改成数组。
    """
    with app.app_context():
        ids = _seed(('算法', '微积分'))
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    _post(client, '/api/error_book/add_batch', {'question_ids': ids}, token)

    data = client.get('/api/error_book/stats').get_json()['data']
    # config.SUBJECTS 里 算法 排在 微积分 之前;实际响应里恰好相反(微 U+5FAE < 算 U+7B97)
    assert list(data['by_subject']) == ['微积分', '算法']


def test_stats_is_per_user(app, client, login):
    with app.app_context():
        ids = _seed(('微积分',))
    _other_user_entry(app, ids[0])
    login('student', 'StudentPass123456')

    data = client.get('/api/error_book/stats').get_json()['data']
    assert data['total'] == 0 and data['by_subject'] == {}


# --------------------------------------------------------------- update_notes
def test_update_notes_saves_stripped_text(app, client, login):
    with app.app_context():
        ids = _seed(('微积分',))
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    _post(client, '/api/error_book/add_batch', {'question_ids': ids}, token)

    r = _post(client, '/api/error_book/update_notes',
              {'question_id': ids[0], 'notes': '  分部积分记错了  '}, token)
    assert r.status_code == 200
    with app.app_context():
        assert ErrorBook.query.one().notes == '分部积分记错了'


def test_update_notes_missing_notes_clears_it(app, client, login):
    """不传 notes 视为清空,而不是"保持原样" —— 前端清空输入框后就是这么发的。"""
    with app.app_context():
        ids = _seed(('微积分',))
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    _post(client, '/api/error_book/add_batch', {'question_ids': ids}, token)
    _post(client, '/api/error_book/update_notes',
          {'question_id': ids[0], 'notes': '先写点东西'}, token)

    _post(client, '/api/error_book/update_notes', {'question_id': ids[0]}, token)
    with app.app_context():
        assert ErrorBook.query.one().notes == ''


def test_update_notes_rejects_bad_input(app, client, login):
    with app.app_context():
        ids = _seed(('微积分',))
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    _post(client, '/api/error_book/add_batch', {'question_ids': ids}, token)

    no_id = _post(client, '/api/error_book/update_notes', {'notes': 'x'}, token)
    assert no_id.status_code == 400
    assert no_id.get_json()['error'] == 'question_id 必须为正整数'

    not_str = _post(client, '/api/error_book/update_notes',
                    {'question_id': ids[0], 'notes': 123}, token)
    assert not_str.status_code == 400
    assert not_str.get_json()['error'] == 'notes 必须是字符串'

    too_long = _post(client, '/api/error_book/update_notes',
                     {'question_id': ids[0], 'notes': 'x' * 5001}, token)
    assert too_long.status_code == 400
    assert '5000' in too_long.get_json()['error']


def test_update_notes_404_when_not_in_error_book(app, client, login):
    with app.app_context():
        ids = _seed(('微积分',))
    login('student', 'StudentPass123456')
    token = get_csrf(client)

    r = _post(client, '/api/error_book/update_notes',
              {'question_id': ids[0], 'notes': 'x'}, token)
    assert r.status_code == 404
    assert r.get_json()['code'] == 'NOT_FOUND'


def test_update_notes_cannot_touch_another_users_entry(app, client, login):
    """别人的错题在本人视角下"不存在",回 404 而不是 403 —— 不泄露它是否存在。"""
    with app.app_context():
        ids = _seed(('微积分',))
    _other_user_entry(app, ids[0])
    login('student', 'StudentPass123456')
    token = get_csrf(client)

    r = _post(client, '/api/error_book/update_notes',
              {'question_id': ids[0], 'notes': '改掉'}, token)
    assert r.status_code == 404
    with app.app_context():
        assert ErrorBook.query.one().notes == 'admin 的备注'    # 原样未动
