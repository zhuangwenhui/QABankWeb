"""日志/审计/异常兜底/健康检查。"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def test_healthz_ok_without_login(client):
    r = client.get('/healthz')
    assert r.status_code == 200
    assert r.get_json()['status'] == 'ok'


def test_readyz_ok_without_login(client):
    r = client.get('/readyz')
    assert r.status_code == 200
    assert r.get_json()['status'] == 'ok'


def test_exception_log_carries_request_id(app, client, login, caplog):
    """未捕获异常的日志必须带 request_id(spec §3.3 可关联性)。"""
    @app.route('/api/_boom_rid')
    def _boom_rid():
        raise RuntimeError('rid-check')
    login('student', 'StudentPass123456')
    with caplog.at_level(logging.ERROR):
        client.get('/api/_boom_rid')
    records = [r for r in caplog.records if '未捕获异常' in r.getMessage()]
    assert records and getattr(records[-1], 'request_id', None)


def test_unhandled_exception_api_returns_json(app, client, login):
    @app.route('/api/_boom')
    def _boom():
        raise ValueError('boom')
    login('student', 'StudentPass123456')
    r = client.get('/api/_boom')
    assert r.status_code == 500
    body = r.get_json()
    assert body['success'] is False and body['code'] == 'SERVER_ERROR'
    assert 'boom' not in r.get_data(as_text=True)  # 不泄露异常细节


def test_unhandled_exception_page_returns_error_page(app, client, login):
    @app.route('/_boom_page')
    def _boom_page():
        raise ValueError('boom')
    login('student', 'StudentPass123456')
    r = client.get('/_boom_page')
    assert r.status_code == 500
    assert '服务器内部错误' in r.get_data(as_text=True)
    assert 'Traceback' not in r.get_data(as_text=True)


def test_http_404_not_swallowed_by_handler(client, login):
    login('student', 'StudentPass123456')
    r = client.get('/api/no_such_endpoint')
    assert r.status_code == 404
    assert r.get_json()['code'] == 'NOT_FOUND'


def test_request_log_line_is_json(app, client, caplog):
    with caplog.at_level(logging.INFO, logger='request'):
        client.get('/healthz')
    records = [rec for rec in caplog.records if rec.name == 'request']
    assert records, '应有请求日志'
    rec = records[-1]
    assert rec.path == '/healthz' and rec.status == 200
    assert getattr(rec, 'request_id', None)


def test_audit_helper_emits_event(app, caplog):
    from logging_setup import audit
    with app.test_request_context('/x'):
        with caplog.at_level(logging.INFO, logger='audit'):
            audit('login_failed', target='someone', detail='测试')
    rec = [r for r in caplog.records if r.name == 'audit'][-1]
    assert rec.event == 'login_failed' and rec.target == 'someone'


def test_json_formatter_output(app):
    from logging_setup import JsonFormatter
    rec = logging.LogRecord('x', logging.INFO, __file__, 1, '你好', None, None)
    out = json.loads(JsonFormatter().format(rec))
    assert out['message'] == '你好' and out['level'] == 'INFO'
