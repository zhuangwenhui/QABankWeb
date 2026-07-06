"""账号功能:停用、强制改密、自助改密。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models import User, db
from tests.conftest import get_csrf, plant_captcha


def _set(app, username, **fields):
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        for k, v in fields.items():
            setattr(user, k, v)
        db.session.commit()


def test_user_new_columns_default(app):
    with app.app_context():
        u = User.query.filter_by(username='student').first()
        assert u.must_change_password is False
        assert u.is_active is True


def test_disabled_user_cannot_login(app, client, login):
    _set(app, 'student', is_active=False)
    r = login('student', 'StudentPass123456')
    assert r.status_code == 200  # 停留在登录页
    assert '已被停用' in r.get_data(as_text=True)


def test_disabled_mid_session_kicked(app, client, login):
    login('student', 'StudentPass123456')
    assert client.get('/questions').status_code == 200
    _set(app, 'student', is_active=False)
    r = client.get('/questions')
    assert r.status_code == 302 and '/login' in r.headers['Location']


def _change_password(client, old, new, confirm=None):
    token = get_csrf(client)
    return client.post('/change_password', data={
        'old_password': old, 'new_password': new,
        'confirm_password': confirm if confirm is not None else new,
        'csrf_token': token,
    }, follow_redirects=False)


def test_change_password_happy_path(app, client, login):
    login('student', 'StudentPass123456')
    r = _change_password(client, 'StudentPass123456', 'BrandNewPass1234')
    assert r.status_code == 302
    client.get('/logout')
    assert login('student', 'BrandNewPass1234').status_code == 302


def test_change_password_rejects_wrong_old(client, login):
    login('student', 'StudentPass123456')
    r = _change_password(client, 'wrong-old-pass', 'BrandNewPass1234')
    assert '旧密码不正确' in r.get_data(as_text=True)


def test_change_password_rejects_short(client, login):
    login('student', 'StudentPass123456')
    r = _change_password(client, 'StudentPass123456', 'short1234')
    assert '12' in r.get_data(as_text=True)


def test_change_password_rejects_mismatch(client, login):
    login('student', 'StudentPass123456')
    r = _change_password(client, 'StudentPass123456', 'BrandNewPass1234', 'Different1234567')
    assert '两次输入不一致' in r.get_data(as_text=True)


def test_must_change_password_forces_redirect(app, client, login):
    _set(app, 'student', must_change_password=True)
    login('student', 'StudentPass123456')
    r = client.get('/questions')
    assert r.status_code == 302 and '/change_password' in r.headers['Location']
    r = client.get('/api/questions')
    assert r.status_code == 403
    assert r.get_json()['code'] == 'MUST_CHANGE_PASSWORD'
    _change_password(client, 'StudentPass123456', 'BrandNewPass1234')
    assert client.get('/questions').status_code == 200
    with app.app_context():
        assert User.query.filter_by(username='student').first().must_change_password is False
