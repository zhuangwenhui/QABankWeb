"""权限矩阵:未登录 / student / admin × 关键端点的预期状态码。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# (method, path, anon 期望, student 期望, admin 期望)
MATRIX = [
    ('GET', '/questions',            302, 200, 200),
    ('GET', '/error_book',           302, 200, 200),
    ('GET', '/feedback',             302, 200, 200),
    ('GET', '/overview',             302, 302, 200),   # 学生重定向回题目管理
    ('GET', '/change_password',      302, 200, 200),
    ('GET', '/healthz',              200, 200, 200),
    ('GET', '/readyz',               200, 200, 200),
    ('GET', '/api/questions',        401, 200, 200),
    ('GET', '/api/error_book',       401, 200, 200),
    ('GET', '/api/overview/stats',   401, 403, 200),
    ('GET', '/api/overview/users',   401, 403, 200),
]


@pytest.mark.parametrize('method,path,anon,student,admin', MATRIX)
def test_permission_matrix(client, login, method, path, anon, student, admin):
    assert client.open(path, method=method).status_code == anon, f'anon {path}'
    login('student', 'StudentPass123456')
    assert client.open(path, method=method).status_code == student, f'student {path}'
    client.get('/logout')
    login('admin', 'AdminPass123456')
    assert client.open(path, method=method).status_code == admin, f'admin {path}'


def test_mutating_endpoints_reject_anon(client):
    """未登录的写操作一律 400(CSRF 先拦)或 401,绝不放行。"""
    for path in ('/api/questions', '/api/error_book/add',
                 '/api/overview/users', '/api/feedback'):
        r = client.post(path, json={})
        assert r.status_code in (400, 401), path
