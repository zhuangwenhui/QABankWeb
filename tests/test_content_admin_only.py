"""内容管理端点严格 admin-only(权限双轨):学生 403、管理员放行;学生的读与自有数据不误伤。

背景:此前 create/update/delete_question、batch_*、*_image、source_exists 仅 @login_required,
任何登录学生都能管理共享题库(admin 与 student 在内容域权限等价 = 双轨失效)。现收紧为 @admin_required。
"""
from conftest import get_csrf
from models import Question, db

# (method, path 模板)—— 应仅管理员可达的内容管理端点
ADMIN_ENDPOINTS = [
    ('POST', '/api/questions'),
    ('PUT', '/api/questions/{qid}'),
    ('DELETE', '/api/questions/{qid}'),
    ('POST', '/api/questions/batch_delete'),
    ('POST', '/api/questions/batch_update_tags'),
    ('POST', '/api/questions/batch_update_source'),
    ('POST', '/api/upload_question_image'),
    ('POST', '/api/delete_question_image'),
    ('GET', '/api/source_exists'),
]


def _seed_q(app):
    with app.app_context():
        q = Question(subject='数学', difficulty='中等', question_latex='q')
        db.session.add(q)
        db.session.commit()
        return q.id


def _call(client, method, path, token):
    kw = {'headers': {'X-CSRFToken': token}}
    if method in ('POST', 'PUT'):
        kw['json'] = {}
    return client.open(path, method=method, **kw)


def test_student_forbidden_on_all_content_management(app, client, login):
    qid = _seed_q(app)
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    for method, tpl in ADMIN_ENDPOINTS:
        path = tpl.format(qid=qid)
        r = _call(client, method, path, token)
        assert r.status_code == 403, f'student {method} {path} 应 403,实得 {r.status_code}'


def test_admin_passes_auth_on_all_content_management(app, client, login):
    qid = _seed_q(app)
    login('admin', 'AdminPass123456')
    token = get_csrf(client)
    for method, tpl in ADMIN_ENDPOINTS:
        path = tpl.format(qid=qid)
        r = _call(client, method, path, token)
        # 管理员过鉴权门:可能因空 body 得 400,但绝不应是 403
        assert r.status_code != 403, f'admin {method} {path} 不应 403,实得 {r.status_code}'


def test_student_read_and_own_data_not_broken(app, client, login):
    """收紧不误伤:学生对题库的读、记录查看、自有进度仍可用(login_required 域不受影响)。"""
    qid = _seed_q(app)
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    assert client.get('/api/questions').status_code == 200
    assert client.get(f'/api/questions/{qid}').status_code == 200
    assert client.get('/api/questions/tag_facets').status_code == 200
    assert client.get(f'/api/questions/{qid}/related').status_code == 200
    assert client.post('/api/log_view_question', json={'question_id': qid},
                       headers={'X-CSRFToken': token}).status_code == 200
    assert client.post('/api/progress/set', json={'question_id': qid, 'status': 'done'},
                       headers={'X-CSRFToken': token}).status_code == 200
    # 自有错题本/收藏仍可写
    assert client.post('/api/error_book/add', json={'question_id': qid},
                       headers={'X-CSRFToken': token}).status_code in (200, 201)
    assert client.post(f'/api/questions/{qid}/bookmark',
                       headers={'X-CSRFToken': token}).status_code == 200


def test_questions_page_admin_ui_gated_by_role(app, client, login):
    """服务端渲染:学生页 body 无 is-admin、右键菜单无编辑/删除项;管理员页两者皆有。
    (前端 js-edit 行动作由 state.isAdmin 门控,是客户端行为,此处验服务端可断言的部分。)"""
    login('student', 'StudentPass123456')
    html = client.get('/questions').get_data(as_text=True)
    body_open = html.split('<body', 1)[1][:80]
    assert 'is-admin' not in body_open, '学生 body 不应有 is-admin'
    assert 'data-action="edit"' not in html, '学生右键菜单不应有编辑项'
    assert 'data-action="delete"' not in html, '学生右键菜单不应有删除项'

    client.get('/logout')
    login('admin', 'AdminPass123456')
    html2 = client.get('/questions').get_data(as_text=True)
    assert 'is-admin' in html2.split('<body', 1)[1][:80], '管理员 body 应有 is-admin'
    assert 'data-action="edit"' in html2 and 'data-action="delete"' in html2
