"""认证与权限装饰器。g.user 由 app.before_request 加载。"""
from functools import wraps

from flask import g, jsonify, redirect, request, session, url_for

from logging_setup import audit


def _wants_json():
    """该请求该不该用 JSON 回话。

    按路径前缀判断而不是看 Accept 头:浏览器地址栏直接打开 /api/... 时 Accept 是 text/html,
    但那仍然是接口,回一个登录页的 302 只会让调试的人更糊涂。
    """
    return request.path.startswith('/api/')


def login_required(f):
    """要求已登录。未登录时:接口回 401 JSON,页面 302 到登录页并带上 next。"""
    # wrapper 不写 docstring:@wraps(f) 会把被装饰函数的 __doc__ 覆盖上来,
    # 这里写什么都不会出现在 help() 或 API 文档里。说明写在外层函数上。
    @wraps(f)
    def wrapper(*args, **kwargs):
        # g.user 由 app.before_request 的 load_user_and_csrf 提前放好,这里只做判断
        if g.get('user') is None:
            if _wants_json():
                audit('access_denied', detail='unauthorized ' + request.path)
                return jsonify(success=False, error='未登录或会话已过期', code='UNAUTHORIZED'), 401
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    """要求管理员。未登录同 login_required;已登录但非管理员时接口回 403、页面回题目管理。

    页面侧不回 403 错误页而是重定向:总览是管理侧视图,学生点到它属于走错门而不是越权攻击,
    甩一个 403 页面对学生没有意义。两条路径都会记一条 access_denied 审计。
    """
    # 同 login_required:wrapper 不写 docstring(@wraps 会覆盖)。
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
    """对非安全方法校验 CSRF token(header 或表单字段)。由 app.before_request 末尾调用。

    豁免导入通道:CSRF 防的是"浏览器带着用户 Cookie 被第三方站点诱导发请求",
    而导入通道用 Authorization: Bearer 认证、不依赖 Cookie,第三方站点没有那个令牌,
    诱导不出请求来,这条防线对它没有意义。
    """
    # ⚠️ 下面这个分支**当前永不可达**,别当成死代码删掉。
    # app.py 的 load_user_and_csrf 在认出导入通道后会**提前 return None**(见 app.py 中
    # `g.import_api = True` 紧随其后那行),压根走不到本函数。
    # 留着它是因为那条提前 return 是实现细节:哪天有人把导入通道改成"继续往下走完整个
    # before_request",这里就是唯一挡住 Bearer 请求被 CSRF 误杀的东西。删了不会有任何
    # 测试变红 —— 会在改动 app.py 的那天以 400 CSRF_ERROR 的形式炸在导入流水线上。
    if g.get('import_api'):
        return None
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        token = session.get('csrf_token')
        sent = request.headers.get('X-CSRFToken') or request.form.get('csrf_token')
        if not token or sent != token:
            if _wants_json():
                return jsonify(success=False, error='CSRF 校验失败,请刷新页面重试', code='CSRF_ERROR'), 400
            return 'CSRF 校验失败', 400
    return None
