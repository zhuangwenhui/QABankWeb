"""pytest 夹具:独立内存库 app、client、登录辅助。"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import captcha as captcha_module
import config as config_module
from app import create_app, login_throttle
from models import User, db as _db


@pytest.fixture()
def app(tmp_path):
    """函数级隔离:内存库 + 临时上传/生成目录 + 预置 admin/student 账号。

    上传与生成目录指向 tmp_path,测试绝不读写仓库真实 uploads/、generated_pdfs/。
    """
    cfg = type('Cfg', (config_module.TestingConfig,), {
        'UPLOAD_FOLDER': str(tmp_path / 'uploads'),
        'GENERATED_PDF_FOLDER': str(tmp_path / 'generated'),
    })
    application = create_app(cfg)
    with application.app_context():
        _db.create_all()
        admin = User(username='admin', role='admin')
        admin.set_password('AdminPass123456')
        student = User(username='student', role='student')
        student.set_password('StudentPass123456')
        _db.session.add_all([admin, student])
        _db.session.commit()
    yield application
    with application.app_context():
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def app_factory(tmp_path):
    """特殊场景(文件库/自定义配置)用的 app 工厂。"""
    def _make(**overrides):
        cfg = type('Cfg', (config_module.TestingConfig,), overrides)
        application = create_app(cfg)
        with application.app_context():
            _db.create_all()
        return application
    return _make


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _reset_throttle():
    """login_throttle 是模块级全局,逐测试清零防串扰。"""
    for key in ('ip:127.0.0.1', 'user:admin', 'user:student', 'user:alice'):
        login_throttle.reset(key)
    yield
    for key in ('ip:127.0.0.1', 'user:admin', 'user:student', 'user:alice'):
        login_throttle.reset(key)


def get_csrf(client):
    """GET 一次让服务端生成 csrf_token 并读出。"""
    client.get('/login')
    with client.session_transaction() as sess:
        return sess.get('csrf_token', '')


def plant_captcha(client, answer):
    """在会话种入已知答案的验证码摘要(模拟用户看到图片)。"""
    with client.application.app_context():
        digest = captcha_module._digest(answer)
    with client.session_transaction() as sess:
        sess[captcha_module.SESSION_KEY] = {'d': digest, 'exp': time.time() + 300}


@pytest.fixture()
def login(client):
    """login('admin', 'AdminPass123456') → 完成含验证码的登录,返回响应。"""
    def _login(username, password):
        token = get_csrf(client)
        plant_captcha(client, 'TEST')
        return client.post('/login', data={
            'username': username, 'password': password,
            'captcha': 'TEST', 'csrf_token': token,
        }, follow_redirects=False)
    return _login
