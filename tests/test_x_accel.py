"""USE_X_ACCEL 开启时返回 X-Accel-Redirect 头而非文件体。"""
import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models import GeneratedFile, User, db
from tests.conftest import get_csrf, plant_captcha


def _login(client, username, password):
    token = get_csrf(client)
    plant_captcha(client, 'TEST')
    return client.post('/login', data={'username': username, 'password': password,
                                       'captcha': 'TEST', 'csrf_token': token})


def test_uploads_x_accel(app_factory, tmp_path):
    up_dir = tmp_path / 'up'
    up_dir.mkdir()
    (up_dir / 'pic.png').write_bytes(b'\x89PNG\r\n\x1a\nfake')
    application = app_factory(USE_X_ACCEL=True, UPLOAD_FOLDER=str(up_dir))
    with application.app_context():
        u = User(username='alice', role='student')
        u.set_password('AlicePass1234567')
        db.session.add(u)
        db.session.commit()
    client = application.test_client()
    _login(client, 'alice', 'AlicePass1234567')
    r = client.get('/uploads/pic.png')
    assert r.status_code == 200
    assert r.headers['X-Accel-Redirect'] == '/_protected_uploads/pic.png'
    assert r.data == b''                       # 文件体由 Nginx 发送
    assert 'image/png' in r.headers['Content-Type']


def test_uploads_direct_send_without_flag(client, app, login):
    """未开启开关(开发环境)仍由 Flask 直接发文件——回归保护。"""
    path = os.path.join(app.config['UPLOAD_FOLDER'], 'direct.png')
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\nfake')
    try:
        login('student', 'StudentPass123456')
        r = client.get('/uploads/direct.png')
        assert r.status_code == 200 and r.data.startswith(b'\x89PNG')
        assert 'X-Accel-Redirect' not in r.headers
    finally:
        os.remove(path)
