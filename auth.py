"""认证与权限装饰器。g.user 由 app.before_request 加载。"""
from functools import wraps

from flask import g, jsonify, redirect, request, session, url_for

from logging_setup import audit


def _wants_json():
    return request.path.startswith('/api/')


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if g.get('user') is None:
            if _wants_json():
                audit('access_denied', detail='unauthorized ' + request.path)
                return jsonify(success=False, error='未登录或会话已过期', code='UNAUTHORIZED'), 401
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if g.get('user') is None:
            if _wants_json():
                audit('access_denied', detail='unauthorized ' + request.path)
                return jsonify(success=False, error='未登录或会话已过期', code='UNAUTHORIZED'), 401
            return redirect(url_for('login', next=request.path))
        if not g.user.is_admin:
            if _wants_json():
                audit('access_denied', detail='forbidden ' + request.path)
                return jsonify(success=False, error='需要管理员权限', code='FORBIDDEN'), 403
            # 总览为管理侧视图,学生角色重定向至题目管理页
            audit('access_denied', detail='forbidden ' + request.path)
            return redirect(url_for('questions_page'))
        return f(*args, **kwargs)
    return wrapper


def csrf_protect():
    """对非安全方法校验 CSRF token(header 或表单字段)。"""
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        token = session.get('csrf_token')
        sent = request.headers.get('X-CSRFToken') or request.form.get('csrf_token')
        if not token or sent != token:
            if _wants_json():
                return jsonify(success=False, error='CSRF 校验失败,请刷新页面重试', code='CSRF_ERROR'), 400
            return 'CSRF 校验失败', 400
    return None
