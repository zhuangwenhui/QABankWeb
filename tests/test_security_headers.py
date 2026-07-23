"""安全响应头:CSP(script nonce)、XFO、nosniff、Referrer-Policy。"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def test_security_headers_present(client):
    r = client.get('/login')
    assert r.headers.get('X-Frame-Options') == 'SAMEORIGIN'
    assert r.headers.get('X-Content-Type-Options') == 'nosniff'
    assert 'strict-origin-when-cross-origin' in r.headers.get('Referrer-Policy', '')
    csp = r.headers.get('Content-Security-Policy', '')
    assert "default-src 'self'" in csp
    assert 'https://cdn.jsdelivr.net' in csp and 'https://cdnjs.cloudflare.com' in csp
    assert "'nonce-" in csp  # script-src 含 nonce


def test_font_src_allows_self_for_webfonts(client):
    # 自托管字体依赖 CSP font-src 含 'self';字体排版期上线自托管 woff2 后必须保持,防回归
    r = client.get('/login')
    csp = r.headers.get('Content-Security-Policy', '')
    assert 'font-src' in csp and "'self'" in csp


def test_inline_scripts_carry_nonce(client):
    """登录页所有无 src 的 <script> 必须带 nonce 且与 CSP 头一致。"""
    r = client.get('/login')
    csp = r.headers.get('Content-Security-Policy', '')
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    html = r.get_data(as_text=True)
    inline_scripts = re.findall(r'<script(?![^>]*\bsrc=)([^>]*)>', html)
    assert inline_scripts, '登录页应有内联脚本(验证码刷新)'
    for attrs in inline_scripts:
        assert f'nonce="{nonce}"' in attrs


def test_no_hsts_outside_production(client):
    r = client.get('/login')
    assert 'Strict-Transport-Security' not in r.headers


def test_pages_still_render_after_talisman(client, login):
    login('student', 'StudentPass123456')
    for path in ('/questions', '/error_book', '/feedback'):
        assert client.get(path).status_code == 200
