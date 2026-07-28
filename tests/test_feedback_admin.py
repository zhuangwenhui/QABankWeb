"""反馈的管理侧两个端点:POST /<fid>/status(标记状态并回复)与 DELETE /<fid>。

这两个此前零测试覆盖,而它们是全站仅有的「管理员改写别人提交的内容」与
「跨用户删除」两条通道 —— 权限判定一旦漂移,学生就能删掉或篡改他人的工单。

删除权限有意做成两条不同的规则,测试分别钉住:
  - 状态/回复:仅管理员(@admin_required),学生连自己的工单都不能改状态;
  - 删除:本人或管理员(@login_required + 属主判定)。
"""
from conftest import get_csrf
from models import Feedback, User, db


def _seed_feedback(app, username, title='标题', content='正文'):
    """以 username 的身份建一条反馈,返回 fid。"""
    with app.app_context():
        user = User.query.filter_by(username=username).one()
        fb = Feedback(user_id=user.id, title=title, content=content)
        db.session.add(fb)
        db.session.commit()
        return fb.id


# --------------------------------------------------------------- 状态与回复
def test_update_status_marks_and_replies(app, client, login):
    fid = _seed_feedback(app, 'student')
    login('admin', 'AdminPass123456')
    token = get_csrf(client)

    r = client.post(f'/api/feedback/{fid}/status',
                    json={'status': '已处理', 'reply': '已修复,感谢反馈'},
                    headers={'X-CSRFToken': token})
    assert r.status_code == 200, r.get_data(as_text=True)
    fb = r.get_json()['data']['feedback']
    assert fb['status'] == '已处理' and fb['reply'] == '已修复,感谢反馈'
    # 回显里带提交人,管理端列表靠它直接显示,别退化成 None
    assert fb['username'] == 'student'


def test_update_status_without_reply_keeps_old_reply(app, client, login):
    """不带 reply 字段时只改状态,已有回复保持不变(前端「仅标记已处理」按钮走这条)。"""
    fid = _seed_feedback(app, 'student')
    login('admin', 'AdminPass123456')
    token = get_csrf(client)
    client.post(f'/api/feedback/{fid}/status',
                json={'status': '已处理', 'reply': '先给个回复'},
                headers={'X-CSRFToken': token})

    r = client.post(f'/api/feedback/{fid}/status', json={'status': '待处理'},
                    headers={'X-CSRFToken': token})
    assert r.get_json()['data']['feedback']['reply'] == '先给个回复'


def test_update_status_rejects_unknown_status(app, client, login):
    fid = _seed_feedback(app, 'student')
    login('admin', 'AdminPass123456')
    token = get_csrf(client)

    r = client.post(f'/api/feedback/{fid}/status', json={'status': '归档'},
                    headers={'X-CSRFToken': token})
    assert r.status_code == 400
    assert '待处理' in r.get_json()['error'] and '已处理' in r.get_json()['error']

    missing = client.post(f'/api/feedback/{fid}/status', json={},
                          headers={'X-CSRFToken': token})
    assert missing.status_code == 400


def test_update_status_rejects_overlong_reply(app, client, login):
    fid = _seed_feedback(app, 'student')
    login('admin', 'AdminPass123456')
    token = get_csrf(client)

    r = client.post(f'/api/feedback/{fid}/status',
                    json={'status': '已处理', 'reply': 'x' * 5001},
                    headers={'X-CSRFToken': token})
    assert r.status_code == 400
    assert '5000' in r.get_json()['error']
    with app.app_context():
        # 超长回复被拒时,状态也不该被顺手改掉
        assert db.session.get(Feedback, fid).status == '待处理'


def test_update_status_404_for_missing_feedback(app, client, login):
    login('admin', 'AdminPass123456')
    token = get_csrf(client)
    r = client.post('/api/feedback/999999/status', json={'status': '已处理'},
                    headers={'X-CSRFToken': token})
    assert r.status_code == 404
    assert r.get_json()['code'] == 'NOT_FOUND'


def test_student_cannot_change_status_even_of_own_feedback(app, client, login):
    fid = _seed_feedback(app, 'student')
    login('student', 'StudentPass123456')
    token = get_csrf(client)

    r = client.post(f'/api/feedback/{fid}/status', json={'status': '已处理'},
                    headers={'X-CSRFToken': token})
    assert r.status_code == 403
    assert r.get_json()['code'] == 'FORBIDDEN'
    with app.app_context():
        assert db.session.get(Feedback, fid).status == '待处理'


# --------------------------------------------------------------- 删除
def test_owner_can_delete_own_feedback(app, client, login):
    fid = _seed_feedback(app, 'student')
    login('student', 'StudentPass123456')
    token = get_csrf(client)

    r = client.delete(f'/api/feedback/{fid}', headers={'X-CSRFToken': token})
    assert r.status_code == 200
    with app.app_context():
        assert Feedback.query.count() == 0


def test_admin_can_delete_others_feedback(app, client, login):
    fid = _seed_feedback(app, 'student')
    login('admin', 'AdminPass123456')
    token = get_csrf(client)

    r = client.delete(f'/api/feedback/{fid}', headers={'X-CSRFToken': token})
    assert r.status_code == 200
    with app.app_context():
        assert Feedback.query.count() == 0


def test_student_cannot_delete_others_feedback(app, client, login):
    fid = _seed_feedback(app, 'admin')          # 管理员提交的工单
    login('student', 'StudentPass123456')
    token = get_csrf(client)

    r = client.delete(f'/api/feedback/{fid}', headers={'X-CSRFToken': token})
    assert r.status_code == 403
    assert r.get_json()['code'] == 'FORBIDDEN'
    with app.app_context():
        assert Feedback.query.count() == 1


def test_delete_404_for_missing_feedback(app, client, login):
    login('student', 'StudentPass123456')
    token = get_csrf(client)
    r = client.delete('/api/feedback/999999', headers={'X-CSRFToken': token})
    assert r.status_code == 404


def test_delete_requires_csrf(app, client, login):
    """DELETE 也在 CSRF 保护范围内(csrf_protect 覆盖 POST/PUT/PATCH/DELETE)。"""
    fid = _seed_feedback(app, 'student')
    login('student', 'StudentPass123456')

    r = client.delete(f'/api/feedback/{fid}')      # 不带 X-CSRFToken
    assert r.status_code == 400
    assert r.get_json()['code'] == 'CSRF_ERROR'
    with app.app_context():
        assert Feedback.query.count() == 1
