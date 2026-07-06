"""题库系统应用入口。

页面路由(服务端渲染)+ /api/ 蓝图(JSON 接口)。
运行: .venv/bin/python app.py  (默认 http://127.0.0.1:5000)
"""
import os
import secrets

from flask import (Flask, flash, g, jsonify, redirect, render_template,
                   request, Response, send_from_directory, session, url_for)

import captcha
import config
from auth import admin_required, csrf_protect, login_required
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

    from api.questions import bp as questions_bp
    from api.error_book import bp as error_book_bp
    from api.feedback import bp as feedback_bp
    from api.overview import bp as overview_bp
    app.register_blueprint(questions_bp)
    app.register_blueprint(error_book_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(overview_bp)

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
                flash(f'尝试过于频繁,已临时锁定,请约 {mins} 分钟后再试。', 'danger')
                return render_template('login.html'), 429

            # 2) 验证码校验(先于密码,挡住脚本爬取/暴力破解)
            if not captcha.verify(captcha_input):
                login_throttle.record_failure(ip_key)
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
                flash(f'欢迎回来,{user.username}!', 'success')
                next_url = request.args.get('next')
                if next_url and next_url.startswith('/') and not next_url.startswith('//'):
                    return redirect(next_url)
                return redirect(url_for('questions_page'))

            # 4) 失败计数(IP 与用户名双维度)
            login_throttle.record_failure(ip_key)
            locked_now = login_throttle.record_failure(user_key) if user_key else 0
            remaining = login_throttle.remaining_attempts(ip_key)
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
        return jsonify(success=False, error='文件过大,上限 20MB', code='TOO_LARGE'), 413

    @app.errorhandler(500)
    def server_error(e):
        if request.path.startswith('/api/'):
            return jsonify(success=False, error='服务器内部错误', code='SERVER_ERROR'), 500
        return '服务器内部错误', 500

    with app.app_context():
        db.create_all()

    return app


app = create_app()

if __name__ == '__main__':
    # 仅开发使用;生产入口为 gunicorn 'app:app'(见 deploy/)
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG') == '1'
    app.run(host=host, port=port, debug=debug)
