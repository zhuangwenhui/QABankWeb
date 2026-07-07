"""登录验证码与限流的自动化测试。

运行:  .venv/bin/python -m pytest tests/ -v
"""
import captcha

from tests.conftest import get_csrf, plant_captcha


def test_captcha_endpoint_returns_png(client):
    r = client.get('/captcha')
    assert r.status_code == 200
    assert r.mimetype == 'image/png'
    assert r.data[:8] == b'\x89PNG\r\n\x1a\n'          # PNG 魔数
    assert 'no-store' in r.headers.get('Cache-Control', '')
    with client.session_transaction() as sess:
        assert captcha.SESSION_KEY in sess              # 已在会话种下摘要


def test_login_success_with_valid_captcha(client, login):
    r = login('student', 'StudentPass123456')
    assert r.status_code == 302 and '/questions' in r.headers['Location']
    with client.session_transaction() as sess:
        assert sess.get('user_id')                      # 已登录


def test_login_captcha_case_insensitive(client):
    csrf = get_csrf(client)
    plant_captcha(client, 'ABCD')
    r = client.post('/login', data={
        'username': 'student', 'password': 'StudentPass123456',
        'captcha': ' abcd ', 'csrf_token': csrf,          # 小写 + 空格
    }, follow_redirects=False)
    assert r.status_code == 302


def test_login_rejected_wrong_captcha(client):
    csrf = get_csrf(client)
    plant_captcha(client, 'ABCD')
    r = client.post('/login', data={
        'username': 'student', 'password': 'StudentPass123456',
        'captcha': 'ZZZZ', 'csrf_token': csrf,
    }, follow_redirects=False)
    assert r.status_code == 200                          # 未跳转
    body = r.get_data(as_text=True)
    assert '验证码错误' in body
    with client.session_transaction() as sess:
        assert not sess.get('user_id')


def test_login_rejected_missing_captcha(client):
    csrf = get_csrf(client)
    plant_captcha(client, 'ABCD')
    r = client.post('/login', data={
        'username': 'student', 'password': 'StudentPass123456',
        'captcha': '', 'csrf_token': csrf,
    }, follow_redirects=False)
    assert r.status_code == 200 and '验证码错误' in r.get_data(as_text=True)


def test_captcha_is_one_time_use(client):
    csrf = get_csrf(client)
    plant_captcha(client, 'ABCD')
    client.post('/login', data={                          # 消费掉验证码
        'username': 'student', 'password': 'wrongpass',
        'captcha': 'ABCD', 'csrf_token': csrf,
    }, follow_redirects=False)
    r = client.post('/login', data={                        # 同一枚不能复用
        'username': 'student', 'password': 'StudentPass123456',
        'captcha': 'ABCD', 'csrf_token': csrf,
    }, follow_redirects=False)
    assert r.status_code == 200 and '验证码错误' in r.get_data(as_text=True)


def test_rate_limit_locks_after_failures(client):
    csrf = get_csrf(client)
    # 连续 5 次错误密码(验证码正确),触发锁定
    for _ in range(5):
        plant_captcha(client, 'ABCD')
        client.post('/login', data={
            'username': 'student', 'password': 'wrongpass',
            'captcha': 'ABCD', 'csrf_token': csrf,
        }, follow_redirects=False)
    # 第 6 次即便密码正确也应被锁定拦截(429)
    plant_captcha(client, 'ABCD')
    r = client.post('/login', data={
        'username': 'student', 'password': 'StudentPass123456',
        'captcha': 'ABCD', 'csrf_token': csrf,
    }, follow_redirects=False)
    assert r.status_code == 429
    assert '锁定' in r.get_data(as_text=True)


def test_captcha_digest_not_plaintext(client):
    """会话里存的是 HMAC 摘要而非明文,机器人读 Cookie 也拿不到答案。"""
    client.get('/captcha')
    with client.session_transaction() as sess:
        data = sess[captcha.SESSION_KEY]
    assert set(data.keys()) == {'d', 'exp'}
    assert len(data['d']) == 64 and all(ch in '0123456789abcdef' for ch in data['d'])
