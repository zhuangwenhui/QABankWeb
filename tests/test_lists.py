"""内容发现 · 题单(curated 学习路径)。

覆盖:创建题单、官方题单加题、广场/详情读取、题单内进度、越权保护、
     以及 gen_official_lists 脚本对临时库的幂等。
"""
from conftest import get_csrf
from models import (Question, QuestionList, QuestionListItem,
                    QuestionProgress, User, db)


# ---------------------------------------------------------------- 夹具辅助

def _seed_questions(app, sources):
    """按 source 列表建题,返回 id 列表(顺序对应)。"""
    ids = []
    with app.app_context():
        for i, src in enumerate(sources):
            q = Question(subject='线性代数', difficulty='中等',
                         question_latex=f'q{i}', source=src, chapter='2025')
            db.session.add(q)
            db.session.flush()
            ids.append(q.id)
        db.session.commit()
    return ids


def _make_official_list(app, title, qids):
    """直接落库一个官方题单(owner=admin),含有序题目。"""
    with app.app_context():
        admin = User.query.filter_by(role='admin').first()
        lst = QuestionList(owner_id=admin.id, title=title, description='官方',
                           is_official=True, is_public=True)
        db.session.add(lst)
        db.session.flush()
        for pos, qid in enumerate(qids):
            db.session.add(QuestionListItem(list_id=lst.id, question_id=qid,
                                            position=pos))
        db.session.commit()
        return lst.id


def _set_progress(app, username, qid, status):
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        db.session.add(QuestionProgress(user_id=user.id, question_id=qid,
                                        status=status))
        db.session.commit()


# ---------------------------------------------------------------- 创建 / 加题

def test_student_creates_own_list(app, client, login):
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    r = client.post('/api/lists', json={'title': '我的复习单', 'description': '自用'},
                    headers={'X-CSRFToken': token})
    assert r.status_code == 200
    data = r.get_json()['data']
    assert data['title'] == '我的复习单'
    assert data['is_official'] is False
    with app.app_context():
        lst = db.session.get(QuestionList, data['id'])
        assert lst.owner_id == User.query.filter_by(username='student').first().id


def test_student_cannot_create_official_list(app, client, login):
    """非管理员即便请求 is_official=True 也只能建普通单。"""
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    r = client.post('/api/lists', json={'title': '伪官方', 'is_official': True},
                    headers={'X-CSRFToken': token})
    assert r.status_code == 200
    assert r.get_json()['data']['is_official'] is False


def test_create_rejects_empty_title(app, client, login):
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    r = client.post('/api/lists', json={'title': '   '},
                    headers={'X-CSRFToken': token})
    assert r.status_code == 400


def test_admin_adds_and_removes_items(app, client, login):
    q1, q2 = _seed_questions(app, ['京都大学 情報学 2025 复変 第1問',
                                   '京都大学 情報学 2025 复変 第2問'])
    login('admin', 'AdminPass123456')
    token = get_csrf(client)
    r = client.post('/api/lists', json={'title': '官方精选', 'is_official': True},
                    headers={'X-CSRFToken': token})
    lid = r.get_json()['data']['id']
    assert r.get_json()['data']['is_official'] is True

    assert client.post(f'/api/lists/{lid}/items', json={'question_id': q1},
                       headers={'X-CSRFToken': token}).status_code == 200
    assert client.post(f'/api/lists/{lid}/items', json={'question_id': q2},
                       headers={'X-CSRFToken': token}).status_code == 200

    detail = client.get(f'/api/lists/{lid}').get_json()['data']
    assert [q['id'] for q in detail['questions']] == [q1, q2]

    # 移除首题后剩余顺序正确
    assert client.delete(f'/api/lists/{lid}/items/{q1}',
                         headers={'X-CSRFToken': token}).status_code == 200
    detail = client.get(f'/api/lists/{lid}').get_json()['data']
    assert [q['id'] for q in detail['questions']] == [q2]


def test_add_duplicate_item_is_idempotent(app, client, login):
    q1, = _seed_questions(app, ['京都大学 情報学 2025 复変 第1問'])
    login('admin', 'AdminPass123456')
    token = get_csrf(client)
    lid = client.post('/api/lists', json={'title': 'L'},
                      headers={'X-CSRFToken': token}).get_json()['data']['id']
    client.post(f'/api/lists/{lid}/items', json={'question_id': q1},
                headers={'X-CSRFToken': token})
    # 重复加同一题不应报 500,题目仍只出现一次
    client.post(f'/api/lists/{lid}/items', json={'question_id': q1},
                headers={'X-CSRFToken': token})
    detail = client.get(f'/api/lists/{lid}').get_json()['data']
    assert [q['id'] for q in detail['questions']] == [q1]


# ---------------------------------------------------------------- 广场 / 详情 / 进度

def test_student_sees_official_list_in_plaza(app, client, login):
    qids = _seed_questions(app, ['京都大学 情報学 2025 复変 第1問',
                                 '京都大学 情報学 2025 复変 第2問'])
    lid = _make_official_list(app, '京都大学 情報学 2025 真题', qids)

    login('student', 'StudentPass123456')
    r = client.get('/api/lists')
    assert r.status_code == 200
    lists = r.get_json()['data']['lists']
    mine = [x for x in lists if x['id'] == lid][0]
    assert mine['is_official'] is True
    assert mine['item_count'] == 2
    # 官方单置顶
    assert lists[0]['is_official'] is True


def test_detail_progress_counts_within_list(app, client, login):
    qids = _seed_questions(app, ['京都大学 情報学 2025 复変 第1問',
                                 '京都大学 情報学 2025 复変 第2問',
                                 '京都大学 情報学 2025 复変 第3問'])
    lid = _make_official_list(app, '京都大学 情報学 2025 真题', qids)
    _set_progress(app, 'student', qids[0], 'mastered')
    _set_progress(app, 'student', qids[1], 'done')

    login('student', 'StudentPass123456')
    data = client.get(f'/api/lists/{lid}').get_json()['data']
    assert data['progress']['total'] == 3
    assert data['progress']['done'] == 2       # done 含 mastered
    assert data['progress']['mastered'] == 1
    # 有序题目携带 to_dict 字段
    assert [q['id'] for q in data['questions']] == qids


def test_private_list_hidden_from_others(app, client, login):
    """他人的私有题单既不进广场,也不可直接读详情(404)。"""
    with app.app_context():
        admin = User.query.filter_by(role='admin').first()
        lst = QuestionList(owner_id=admin.id, title='管理员私单',
                           is_official=False, is_public=False)
        db.session.add(lst)
        db.session.commit()
        lid = lst.id

    login('student', 'StudentPass123456')
    lists = client.get('/api/lists').get_json()['data']['lists']
    assert all(x['id'] != lid for x in lists)
    assert client.get(f'/api/lists/{lid}').status_code == 404


# ---------------------------------------------------------------- 越权

def test_student_cannot_modify_others_list(app, client, login):
    q1, = _seed_questions(app, ['京都大学 情報学 2025 复変 第1問'])
    lid = _make_official_list(app, '官方单', [])

    login('student', 'StudentPass123456')
    token = get_csrf(client)
    r = client.post(f'/api/lists/{lid}/items', json={'question_id': q1},
                    headers={'X-CSRFToken': token})
    assert r.status_code == 403
    r = client.delete(f'/api/lists/{lid}/items/{q1}',
                      headers={'X-CSRFToken': token})
    assert r.status_code in (403, 404)  # 403 优先;题不在单内也不得越权


def test_reorder_by_owner(app, client, login):
    qids = _seed_questions(app, ['京都大学 情報学 2025 复変 第1問',
                                 '京都大学 情報学 2025 复変 第2問',
                                 '京都大学 情報学 2025 复変 第3問'])
    login('admin', 'AdminPass123456')
    token = get_csrf(client)
    lid = client.post('/api/lists', json={'title': 'L'},
                      headers={'X-CSRFToken': token}).get_json()['data']['id']
    for qid in qids:
        client.post(f'/api/lists/{lid}/items', json={'question_id': qid},
                    headers={'X-CSRFToken': token})
    new_order = [qids[2], qids[0], qids[1]]
    r = client.post(f'/api/lists/{lid}/reorder', json={'question_ids': new_order},
                    headers={'X-CSRFToken': token})
    assert r.status_code == 200
    detail = client.get(f'/api/lists/{lid}').get_json()['data']
    assert [q['id'] for q in detail['questions']] == new_order


# ---------------------------------------------------------------- 鉴权

def test_lists_require_login(app, client):
    assert client.get('/api/lists').status_code == 401


# ---------------------------------------------------------------- 页面路由

def test_pages_render(app, client, login):
    qids = _seed_questions(app, ['京都大学 情報学 2025 复変 第1問'])
    lid = _make_official_list(app, 'L', qids)
    login('student', 'StudentPass123456')
    assert client.get('/lists').status_code == 200
    assert client.get(f'/lists/{lid}').status_code == 200
    assert client.get('/lists/999999').status_code == 404


# ---------------------------------------------------------------- gen 脚本幂等

def test_gen_official_lists_idempotent(app, tmp_path):
    """gen 脚本对临时库跑两次:第二次不重复建单。"""
    import scripts.gen_official_lists as gen

    db_file = tmp_path / 'gen.db'
    # app 夹具用内存库,这里另起独立文件库供脚本按 --db 连接
    import config as config_module
    from app import create_app
    cfg = type('Cfg', (config_module.TestingConfig,),
               {'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_file}'})
    application = create_app(cfg)
    with application.app_context():
        db.create_all()
        admin = User(username='admin', role='admin')
        admin.set_password('AdminPass123456')
        db.session.add(admin)
        for src, subj in [('京都大学 情報学 2025 复変 第1問', '复变函数'),
                          ('京都大学 情報学 2025 复変 第2問', '复变函数'),
                          ('京都大学 情報学 2024 線形 第1問', '线性代数')]:
            db.session.add(Question(subject=subj, difficulty='中等',
                                    question_latex='x', source=src,
                                    chapter=src.split()[2]))
        db.session.commit()

    n1 = gen.generate(str(db_file))
    assert n1 > 0
    with application.app_context():
        count1 = QuestionList.query.filter_by(is_official=True).count()
    n2 = gen.generate(str(db_file))  # 第二次:幂等,不新增
    with application.app_context():
        count2 = QuestionList.query.filter_by(is_official=True).count()
    assert count2 == count1, '第二次运行不应重复建单'
