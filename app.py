"""题库系统应用入口。

页面路由(服务端渲染)+ /api/ 蓝图(JSON 接口)。
运行: .venv/bin/python app.py  (默认 http://127.0.0.1:5000)
"""
import os
import secrets
from urllib.parse import urlparse

from flask import (Flask, flash, g, jsonify, redirect, render_template,
                   request, Response, send_from_directory, session, url_for)
from flask_migrate import Migrate
from flask_talisman import Talisman
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

import captcha
import config
from auth import admin_required, csrf_protect, login_required
from logging_setup import audit, request_extra, setup_logging
from models import User, db
from ratelimit import LoginThrottle

# 登录限流:同一 IP 或用户名 5 分钟内失败 5 次,锁定 15 分钟
login_throttle = LoginThrottle(max_attempts=5, window=300, lockout=900)


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or config.get_config())
    if app.config.get('ENV_NAME') == 'production' and not (app.config.get('SECRET_KEY') or '').strip():
        raise RuntimeError('生产环境必须通过环境变量 SECRET_KEY 注入会话密钥,拒绝启动')

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['GENERATED_PDF_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(config.BASE_DIR, 'instance'), exist_ok=True)

    db.init_app(app)
    Migrate(app, db, render_as_batch=True)  # SQLite 改表需 batch 模式

    from api.questions import bp as questions_bp
    from api.error_book import bp as error_book_bp
    from api.feedback import bp as feedback_bp
    from api.overview import bp as overview_bp
    app.register_blueprint(questions_bp)
    app.register_blueprint(error_book_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(overview_bp)

    setup_logging(app)  # 须先于 load_user_and_csrf 注册,保证 g.request_id 先于其他 hook 就绪

    if app.config.get('USE_PROXYFIX'):
        # 仅生产启用:信任前置 Nginx 的 X-Forwarded-For/Proto 各一跳
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    csp = {
        'default-src': "'self'",
        'script-src': ["'self'", 'https://cdn.jsdelivr.net', 'https://cdnjs.cloudflare.com'],
        # 样式放宽 unsafe-inline:模板 style 属性与 MathJax/Bootstrap 动态样式所需(spec §3.2)
        'style-src': ["'self'", "'unsafe-inline'",
                      'https://cdn.jsdelivr.net', 'https://cdnjs.cloudflare.com'],
        'font-src': ["'self'", 'data:', 'https://cdn.jsdelivr.net', 'https://cdnjs.cloudflare.com'],
        'img-src': ["'self'", 'data:'],
        'connect-src': "'self'",
    }
    Talisman(
        app,
        content_security_policy=csp,
        content_security_policy_nonce_in=['script-src'],
        frame_options='SAMEORIGIN',
        referrer_policy='strict-origin-when-cross-origin',
        force_https=app.config.get('TALISMAN_FORCE_HTTPS', False),
        strict_transport_security=app.config.get('TALISMAN_FORCE_HTTPS', False),
        session_cookie_secure=app.config.get('SESSION_COOKIE_SECURE', False),
        session_cookie_http_only=True,
    )

    # ------------------------------------------------------------------ hooks

    @app.before_request
    def load_user_and_csrf():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(16)
        g.user = None
        user_id = session.get('user_id')
        if user_id:
            g.user = db.session.get(User, user_id)
        return csrf_protect()

    @app.context_processor
    def inject_globals():
        return {
            'current_user': g.get('user'),
            'csrf_token': session.get('csrf_token', ''),
            'SUBJECTS': config.SUBJECTS,
            'DIFFICULTIES': config.DIFFICULTIES,
            'PER_PAGE_OPTIONS': config.PER_PAGE_OPTIONS,
            'PDF_TEMPLATES': config.PDF_TEMPLATES,
        }

    # ------------------------------------------------------------------ 页面路由

    @app.route('/')
    def index():
        return redirect(url_for('questions_page'))

    @app.route('/captcha')
    def captcha_image():
        """登录验证码图片。no-store 防缓存,每次请求刷新一枚。"""
        png = captcha.issue()
        resp = Response(png, mimetype='image/png')
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        return resp

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if g.user:
            return redirect(url_for('questions_page'))
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            captcha_input = request.form.get('captcha', '')
            ip_key = 'ip:' + (request.remote_addr or 'unknown')
            user_key = 'user:' + username.lower() if username else None

            # 1) 锁定检查(IP 或用户名任一被锁即拒绝)
            locked = login_throttle.locked_for(ip_key)
            if not locked and user_key:
                locked = login_throttle.locked_for(user_key)
            if locked:
                mins = (locked + 59) // 60
                audit('login_locked', target=username)
                flash(f'尝试过于频繁,已临时锁定,请约 {mins} 分钟后再试。', 'danger')
                return render_template('login.html'), 429

            # 2) 验证码校验(先于密码,挡住脚本爬取/暴力破解)
            if not captcha.verify(captcha_input):
                login_throttle.record_failure(ip_key)
                audit('login_failed', target=username, detail='captcha')
                flash('验证码错误或已过期,请重新输入。', 'danger')
                return render_template('login.html')

            # 3) 凭据校验
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                login_throttle.reset(ip_key)
                if user_key:
                    login_throttle.reset(user_key)
                session.clear()  # 防会话固定:登录成功换新会话状态
                session['user_id'] = user.id
                session.permanent = True
                audit('login_success', target=username)
                flash(f'欢迎回来,{user.username}!', 'success')
                next_url = request.args.get('next')
                if next_url and next_url.startswith('/') and not next_url.startswith('//'):
                    return redirect(next_url)
                return redirect(url_for('questions_page'))

            # 4) 失败计数(IP 与用户名双维度)
            login_throttle.record_failure(ip_key)
            locked_now = login_throttle.record_failure(user_key) if user_key else 0
            remaining = login_throttle.remaining_attempts(ip_key)
            audit('login_failed', target=username, detail='password')
            if locked_now:
                flash('失败次数过多,账号已临时锁定 15 分钟。', 'danger')
            elif remaining <= 2:
                flash(f'用户名或密码错误,还可尝试 {remaining} 次。', 'danger')
            else:
                flash('用户名或密码错误', 'danger')
        return render_template('login.html')

    @app.route('/logout')
    def logout():
        session.pop('user_id', None)
        flash('已退出登录', 'info')
        return redirect(url_for('login'))

    @app.route('/questions')
    @login_required
    def questions_page():
        return render_template('questions.html')

    @app.route('/error_book')
    @login_required
    def error_book_page():
        return render_template('error_book.html')

    @app.route('/feedback')
    @login_required
    def feedback_page():
        return render_template('feedback.html')

    @app.route('/overview')
    @admin_required
    def overview_page():
        return render_template('overview.html')

    # ------------------------------------------------------------------ 健康检查

    @app.route('/healthz')
    def healthz():
        try:
            db.session.execute(db.text('SELECT 1'))
        except Exception:
            return jsonify(status='degraded'), 503
        return jsonify(status='ok')

    @app.route('/readyz')
    def readyz():
        # 就绪与存活同判据(单进程 + SQLite,无独立依赖需区分)
        return healthz()

    # ------------------------------------------------------------------ 文件服务

    @app.route('/uploads/<path:filename>')
    @login_required
    def uploaded_file(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    @app.route('/generated/<path:filename>')
    @login_required
    def generated_file(filename):
        return send_from_directory(app.config['GENERATED_PDF_FOLDER'], filename)

    # ------------------------------------------------------------------ 错误处理

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith('/api/'):
            return jsonify(success=False, error='资源不存在', code='NOT_FOUND'), 404
        return render_template('base.html'), 404

    @app.errorhandler(413)
    def too_large(e):
        if request.path.startswith('/api/'):
            return jsonify(success=False, error='文件过大,上限 20MB', code='TOO_LARGE'), 413
        flash('上传内容过大(上限 20MB)', 'danger')
        ref = request.referrer
        if ref:
            p = urlparse(ref)
            same_origin_abs = p.scheme and p.netloc and p.netloc == request.host
            clean_relative = (not p.scheme and not p.netloc
                              and ref.startswith('/')
                              and not ref.startswith('//')      # 挡 //evil、////evil 家族
                              and not ref.startswith('/\\'))    # 挡 /\evil(双保险)
            if not (same_origin_abs or clean_relative):
                ref = None
        return redirect(ref or url_for('questions_page'))

    @app.errorhandler(500)
    def server_error(e):
        if request.path.startswith('/api/'):
            return jsonify(success=False, error='服务器内部错误', code='SERVER_ERROR'), 500
        return render_template('error.html'), 500

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        if isinstance(e, HTTPException):
            return e  # 404/413 等交由既有处理器,不吞
        app.logger.exception('未捕获异常', extra=request_extra())  # 带 request_id 便于关联(spec §3.3)
        if request.path.startswith('/api/'):
            return jsonify(success=False, error='服务器内部错误', code='SERVER_ERROR'), 500
        return render_template('error.html'), 500

    return app


app = create_app()

if __name__ == '__main__':
    # 仅开发使用;生产入口为 gunicorn 'app:app'(见 deploy/)
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG') == '1'
    app.run(host=host, port=port, debug=debug)
