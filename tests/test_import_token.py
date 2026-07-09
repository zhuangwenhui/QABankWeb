"""QB_IMPORT_TOKEN 导入通道:仅两个白名单端点、Bearer 校验、限流、默认关闭零影响。"""
import io

import pytest

import app as app_module
from models import db, User
from ratelimit import LoginThrottle

TOKEN = 't' * 40


@pytest.fixture
def token_app(app_factory, tmp_path):
    application = app_factory(QB_IMPORT_TOKEN=TOKEN,
                              UPLOAD_FOLDER=str(tmp_path / 'up'))
    with application.app_context():
        admin = User(username='imadmin', role='admin')
        admin.set_password('x' * 12)
        db.session.add(admin); db.session.commit()
    yield application
    app_module.import_throttle.reset_all()


def _payload():
    return {'subject': '微积分', 'chapter': '2025', 'difficulty': '中等',
            'source': '東京大学 情報理工 2025 数学 第1問',
            'tags': ['院試'], 'question_latex': '求 $x$', 'solution_latex': '略'}


def test_disabled_by_default(app_factory):
    application = app_factory()          # 不配 token
    c = application.test_client()
    r = c.post('/api/questions', json=_payload(),
               headers={'Authorization': f'Bearer {TOKEN}'})
    # 通道关闭时与普通未登录 POST 完全一致:先被 CSRF 拦(400),零行为变化
    assert r.status_code == 400 and r.get_json()['code'] == 'CSRF_ERROR'


def test_wrong_token_401(token_app):
    c = token_app.test_client()
    r = c.post('/api/questions', json=_payload(),
               headers={'Authorization': 'Bearer wrong'})
    assert r.status_code == 401


def test_create_and_upload_with_token(token_app):
    c = token_app.test_client()
    r = c.post('/api/questions', json=_payload(),
               headers={'Authorization': f'Bearer {TOKEN}'})
    assert r.status_code == 200 and r.get_json()['success'] is True
    qid = r.get_json()['data']['question']['id']
    assert qid > 0
    r2 = c.post('/api/upload_question_image',
                data={'file': (io.BytesIO(b'\x89PNG\r\n\x1a\nfake'), 'shot.png')},
                headers={'Authorization': f'Bearer {TOKEN}'},
                content_type='multipart/form-data')
    assert r2.status_code == 200 and r2.get_json()['data']['filename'].endswith('.png')


def test_token_rejected_on_other_endpoints(token_app):
    c = token_app.test_client()
    r = c.put('/api/questions/1', json={'source': 'x'},
              headers={'Authorization': f'Bearer {TOKEN}'})
    assert r.status_code == 400          # 白名单外 PUT 不认 token:落回 CSRF 拦截
    r2 = c.get('/api/questions', headers={'Authorization': f'Bearer {TOKEN}'})
    assert r2.status_code == 401         # 白名单外 GET:未登录 401


def test_source_exists_with_token(token_app):
    c = token_app.test_client()
    r = c.get('/api/source_exists', query_string={'source': '不存在的来源'},
              headers={'Authorization': f'Bearer {TOKEN}'})
    assert r.status_code == 200 and r.get_json()['data']['exists'] is False


def test_subject_algo_in_whitelist(token_app):
    c = token_app.test_client()
    p = _payload(); p['subject'] = '算法'; p['source'] = '東京大学 情報理工 2025 算法 第1問'
    r = c.post('/api/questions', json=p,
               headers={'Authorization': f'Bearer {TOKEN}'})
    assert r.status_code == 200


def test_throttle_429(token_app, monkeypatch):
    monkeypatch.setattr(app_module, 'import_throttle',
                        LoginThrottle(max_attempts=2, window=60, lockout=60))
    c = token_app.test_client()
    for _ in range(2):
        c.post('/api/questions', json=_payload(),
               headers={'Authorization': f'Bearer {TOKEN}'})
    r = c.post('/api/questions', json=_payload(),
               headers={'Authorization': f'Bearer {TOKEN}'})
    assert r.status_code == 429


def test_non_ascii_bearer_rejected(token_app):
    """非 ASCII 的 Bearer 值应按坏令牌返回 401,而非 compare_digest TypeError 兜成 500。"""
    c = token_app.test_client()
    r = c.post('/api/questions', json=_payload(),
               headers={'Authorization': 'Bearer 令牌'})
    assert r.status_code == 401 and r.get_json()['code'] == 'UNAUTHORIZED'


def test_no_admin_returns_500(app_factory, tmp_path):
    """配了令牌但无在职管理员时,正确令牌命中导入通道应 500(无可用管理员身份)。"""
    application = app_factory(QB_IMPORT_TOKEN=TOKEN,
                              UPLOAD_FOLDER=str(tmp_path / 'up'))
    with application.app_context():
        student = User(username='onlystudent', role='student')
        student.set_password('x' * 12)
        db.session.add(student); db.session.commit()
    c = application.test_client()
    r = c.post('/api/questions', json=_payload(),
               headers={'Authorization': f'Bearer {TOKEN}'})
    assert r.status_code == 500 and r.get_json()['code'] == 'SERVER_ERROR'
    app_module.import_throttle.reset_all()
