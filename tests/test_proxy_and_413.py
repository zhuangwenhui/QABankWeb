"""ProxyFix(仅生产)与 413 API/页面分流。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def test_proxyfix_enabled_by_config(app_factory):
    application = app_factory(USE_PROXYFIX=True)

    @application.route('/_echo_ip')
    def _echo_ip():
        from flask import request
        return request.remote_addr or ''

    client = application.test_client()
    r = client.get('/_echo_ip', headers={'X-Forwarded-For': '203.0.113.9'})
    assert r.get_data(as_text=True) == '203.0.113.9'


def test_proxyfix_disabled_by_default(client, app):
    # TestingConfig 未开 USE_PROXYFIX:伪造头不得生效
    @app.route('/_echo_ip2')
    def _echo_ip2():
        from flask import request
        return request.remote_addr or ''
    r = client.get('/_echo_ip2', headers={'X-Forwarded-For': '203.0.113.9'})
    assert r.get_data(as_text=True) != '203.0.113.9'


def test_413_api_returns_json(app_factory):
    # 413 在 before_request 读取请求体(CSRF 校验读 form)时即触发,先于登录校验,
    # 匿名请求足以覆盖;不需要 login 夹具。
    application = app_factory(MAX_CONTENT_LENGTH=1024)
    client = application.test_client()
    big = b'x' * 4096
    r = client.post('/api/error_book/add', data=big,
                    headers={'Content-Type': 'application/json'})
    assert r.status_code == 413
    assert r.get_json()['code'] == 'TOO_LARGE'


def test_413_page_redirects_with_flash(app_factory):
    application = app_factory(MAX_CONTENT_LENGTH=1024)
    client = application.test_client()
    r = client.post('/login', data={'x': 'y' * 4096})
    assert r.status_code in (302, 303)


def test_413_page_drops_cross_site_referrer(app_factory):
    # 开放重定向回归:413 先于 CSRF/鉴权触发,匿名跨站超大 POST 若把
    # 客户端可控 Referer 反射进 Location 即可 302 到外站。跨站 referrer 须被丢弃。
    application = app_factory(MAX_CONTENT_LENGTH=1024)
    client = application.test_client()
    r = client.post('/login', data={'x': 'y' * 4096},
                    headers={'Referer': 'https://evil.example.com/phish'})
    assert r.status_code in (302, 303)
    assert 'evil.example.com' not in r.headers['Location']


def test_413_page_keeps_same_origin_referrer(app_factory):
    # 同源 referrer 应保留:回到用户来时的本站页面。
    application = app_factory(MAX_CONTENT_LENGTH=1024)
    client = application.test_client()
    r = client.post('/login', data={'x': 'y' * 4096},
                    headers={'Referer': 'http://localhost/error_book'})
    assert r.status_code in (302, 303)
    assert r.headers['Location'] == 'http://localhost/error_book'
