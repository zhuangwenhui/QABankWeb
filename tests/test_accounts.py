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
