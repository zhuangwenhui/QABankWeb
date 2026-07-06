"""ProxyFix(仅生产)与 413 API/页面分流。"""
import os
import sys

import pytest

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


@pytest.mark.parametrize('bad_ref', [
    'https://evil.example.com/phish',  # 跨站绝对 URL
    '//evil.com/x',                    # scheme-relative:netloc=evil.com
    'https:/evil.com',                 # 单斜杠:有 scheme、netloc 为空,Location 折叠成 //evil.com
    'javascript:alert(1)',             # 危险 scheme
    '///evil.com',                     # 三斜杠:urlparse netloc 空 → 折叠成 //evil.com
    '////evil.com',                    # 四斜杠空 authority 绕过:同上家族
    '/////evil.com',                   # 五斜杠:同上家族
    '/\\evil.com',                     # 反斜杠变体(浏览器规范化为 //)
])
def test_413_page_drops_cross_site_referrer(app_factory, bad_ref):
    # 开放重定向回归:413 先于 CSRF/鉴权触发,匿名跨站超大 POST 若把
    # 客户端可控 Referer 反射进 Location 即可 302 到外站。任何外来 scheme/host 须被丢弃,
    # 回落到本站 /questions。
    application = app_factory(MAX_CONTENT_LENGTH=1024)
    client = application.test_client()
    r = client.post('/login', data={'x': 'y' * 4096},
                    headers={'Referer': bad_ref})
    assert r.status_code in (302, 303)
    location = r.headers['Location']
    assert 'evil.com' not in location and 'evil.example.com' not in location
    assert location == '/questions'


@pytest.mark.parametrize('good_ref', [
    'http://localhost/error_book',   # 同源绝对(request.host == localhost)
    '/error_book',                   # 干净相对路径
    '/questions?page=2',             # 带 query 的相对路径
])
def test_413_page_keeps_same_origin_referrer(app_factory, good_ref):
    # 合法 referrer 应保留:回到用户来时的本站页面(同源绝对或安全相对)。
    application = app_factory(MAX_CONTENT_LENGTH=1024)
    client = application.test_client()
    r = client.post('/login', data={'x': 'y' * 4096},
                    headers={'Referer': good_ref})
    assert r.status_code in (302, 303)
    assert r.headers['Location'] == good_ref
