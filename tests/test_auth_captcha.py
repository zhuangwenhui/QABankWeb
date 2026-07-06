"""登录验证码与限流的自动化测试。

运行:  .venv/bin/python -m pytest tests/ -q
或直接:.venv/bin/python tests/test_auth_captcha.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import captcha  # noqa: E402
from app import app, login_throttle  # noqa: E402
from models import User, db  # noqa: E402


def _fresh_app():
    """用独立的内存数据库跑测试,不碰真实 instance/ 数据。"""
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        WTF_CSRF_ENABLED=False,
    )
    with app.app_context():
        db.drop_all()
        db.create_all()
        u = User(username='alice', role='student')
        u.set_password('secret123')
        db.session.add(u)
        db.session.commit()
    return app


def _client():
    return _fresh_app().test_client()


def _csrf(client):
    """触发一次 GET 让服务端在会话里生成 csrf_token,并读出来。"""
    client.get('/login')
    with client.session_transaction() as sess:
        return sess.get('csrf_token', '')


def _plant_captcha(client, answer):
    """在会话里种入一枚已知答案的验证码摘要,模拟用户看到图片。"""
    with app.app_context():
        digest = captcha._digest(answer)
    with client.session_transaction() as sess:
        sess[captcha.SESSION_KEY] = {'d': digest, 'exp': time.time() + 300}


def _login(client, username, password, captcha_answer, csrf=None):
    return client.post('/login', data={
        'username': username, 'password': password,
        'captcha': captcha_answer, 'csrf_token': csrf or _csrf(client),
    }, follow_redirects=False)


def test_captcha_endpoint_returns_png():
    c = _client()
    r = c.get('/captcha')
    assert r.status_code == 200
    assert r.mimetype == 'image/png'
    assert r.data[:8] == b'\x89PNG\r\n\x1a\n'          # PNG 魔数
    assert 'no-store' in r.headers.get('Cache-Control', '')
    with c.session_transaction() as sess:
        assert captcha.SESSION_KEY in sess              # 已在会话种下摘要
    print('✓ /captcha 返回 PNG 且写入会话')


def test_login_success_with_valid_captcha():
    c = _client()
    csrf = _csrf(c)
    _plant_captcha(c, 'ABCD')
    r = _login(c, 'alice', 'secret123', 'ABCD', csrf)
    assert r.status_code == 302 and '/questions' in r.headers['Location']
    with c.session_transaction() as sess:
        assert sess.get('user_id')                      # 已登录
    print('✓ 正确验证码 + 正确密码 → 登录成功')


def test_login_captcha_case_insensitive():
    c = _client()
    csrf = _csrf(c)
    _plant_captcha(c, 'ABCD')
    r = _login(c, 'alice', 'secret123', ' abcd ', csrf)  # 小写 + 空格
    assert r.status_code == 302
    print('✓ 验证码大小写/空白不敏感')


def test_login_rejected_wrong_captcha():
    c = _client()
    csrf = _csrf(c)
    _plant_captcha(c, 'ABCD')
    r = _login(c, 'alice', 'secret123', 'ZZZZ', csrf)
    assert r.status_code == 200                          # 未跳转
    body = r.get_data(as_text=True)
    assert '验证码错误' in body
    with c.session_transaction() as sess:
        assert not sess.get('user_id')
    print('✓ 错误验证码 → 拒绝(即使密码正确)')


def test_login_rejected_missing_captcha():
    c = _client()
    csrf = _csrf(c)
    _plant_captcha(c, 'ABCD')
    r = _login(c, 'alice', 'secret123', '', csrf)
    assert r.status_code == 200 and '验证码错误' in r.get_data(as_text=True)
    print('✓ 空验证码 → 拒绝')


def test_captcha_is_one_time_use():
    c = _client()
    csrf = _csrf(c)
    _plant_captcha(c, 'ABCD')
    _login(c, 'alice', 'wrongpass', 'ABCD', csrf)        # 消费掉验证码
    r = _login(c, 'alice', 'secret123', 'ABCD', csrf)    # 同一枚不能复用
    assert r.status_code == 200 and '验证码错误' in r.get_data(as_text=True)
    print('✓ 验证码一次性使用,不可重放')


def test_rate_limit_locks_after_failures():
    c = _client()
    login_throttle.reset('ip:127.0.0.1')
    login_throttle.reset('user:alice')
    csrf = _csrf(c)
    # 连续 5 次错误密码(验证码正确),触发锁定
    for _ in range(5):
        _plant_captcha(c, 'ABCD')
        _login(c, 'alice', 'wrongpass', 'ABCD', csrf)
    # 第 6 次即便密码正确也应被锁定拦截(429)
    _plant_captcha(c, 'ABCD')
    r = _login(c, 'alice', 'secret123', 'ABCD', csrf)
    assert r.status_code == 429
    assert '锁定' in r.get_data(as_text=True)
    login_throttle.reset('ip:127.0.0.1')
    login_throttle.reset('user:alice')
    print('✓ 连续失败触发限流锁定(429)')


def test_captcha_digest_not_plaintext():
    """会话里存的是 HMAC 摘要而非明文,机器人读 Cookie 也拿不到答案。"""
    c = _client()
    c.get('/captcha')
    with c.session_transaction() as sess:
        data = sess[captcha.SESSION_KEY]
    assert set(data.keys()) == {'d', 'exp'}
    assert len(data['d']) == 64 and all(ch in '0123456789abcdef' for ch in data['d'])
    print('✓ 会话仅存 HMAC 摘要(64 位十六进制),无明文答案')


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for fn in fns:
        fn()
    print(f'\n全部 {len(fns)} 项测试通过。')
