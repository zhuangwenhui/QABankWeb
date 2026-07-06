"""管理员用户管理 API 与 create-admin CLI。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models import User, db
from tests.conftest import get_csrf


def _post(client, url, payload):
    return client.post(url, json=payload, headers={'X-CSRFToken': get_csrf(client)})


def test_list_users_admin_only(client, login):
    login('student', 'StudentPass123456')
    assert client.get('/api/overview/users').status_code == 403
    client.get('/logout')
    login('admin', 'AdminPass123456')
    r = client.get('/api/overview/users')
    assert r.status_code == 200
    users = r.get_json()['data']['users']
    assert {u['username'] for u in users} >= {'admin', 'student'}
    assert all(set(u) >= {'id', 'username', 'role', 'is_active',
                          'must_change_password', 'created_at'} for u in users)


def test_create_user_returns_initial_password_once(app, client, login):
    login('admin', 'AdminPass123456')
    r = _post(client, '/api/overview/users', {'username': 'newbie', 'role': 'student'})
    assert r.status_code == 200
    data = r.get_json()['data']
    pw = data['initial_password']
    assert len(pw) >= 12
    with app.app_context():
        u = User.query.filter_by(username='newbie').first()
        assert u.check_password(pw) and u.must_change_password is True


def test_create_user_response_is_no_store(client, login):
    """明文初始密码过线的响应必须带 Cache-Control: no-store,防中间缓存/浏览器存盘。"""
    login('admin', 'AdminPass123456')
    r = _post(client, '/api/overview/users', {'username': 'nocache', 'role': 'student'})
    assert r.status_code == 200
    assert r.headers.get('Cache-Control') == 'no-store'


def test_create_user_validates(client, login):
    login('admin', 'AdminPass123456')
    assert _post(client, '/api/overview/users',
                 {'username': 'ab', 'role': 'student'}).status_code == 400     # 太短
    assert _post(client, '/api/overview/users',
                 {'username': 'bad name!', 'role': 'student'}).status_code == 400  # 非法字符
    assert _post(client, '/api/overview/users',
                 {'username': 'okname', 'role': 'boss'}).status_code == 400    # 非法角色
    assert _post(client, '/api/overview/users',
                 {'username': 'admin', 'role': 'student'}).status_code == 400  # 重名


def test_reset_password_and_toggle_active(app, client, login):
    login('admin', 'AdminPass123456')
    _post(client, '/api/overview/users', {'username': 'temp1', 'role': 'student'})
    with app.app_context():
        uid = User.query.filter_by(username='temp1').first().id
        admin_id = User.query.filter_by(username='admin').first().id
    r = _post(client, f'/api/overview/users/{uid}/reset_password', {})
    pw = r.get_json()['data']['initial_password']
    with app.app_context():
        u = db.session.get(User, uid)
        assert u.check_password(pw) and u.must_change_password is True
    r = _post(client, f'/api/overview/users/{uid}/toggle_active', {})
    with app.app_context():
        assert db.session.get(User, uid).is_active is False
    # 不能停用自己
    assert _post(client, f'/api/overview/users/{admin_id}/toggle_active', {}).status_code == 400


def test_create_admin_cli(app, monkeypatch):
    monkeypatch.setenv('ADMIN_INITIAL_PASSWORD', 'CliAdminPass1234')
    runner = app.test_cli_runner()
    result = runner.invoke(args=['create-admin', 'boss'])
    assert '创建成功' in result.output
    with app.app_context():
        u = User.query.filter_by(username='boss').first()
        assert u.is_admin and u.check_password('CliAdminPass1234')
    # 幂等:重复创建报错不崩
    result = runner.invoke(args=['create-admin', 'boss'])
    assert '已存在' in result.output


def test_create_admin_cli_rejects_bad_username(app, monkeypatch):
    """CLI 用户名校验与 API 统一:非法用户名被拒,且不建号。"""
    monkeypatch.setenv('ADMIN_INITIAL_PASSWORD', 'CliAdminPass1234')
    runner = app.test_cli_runner()
    for bad in ('ab', 'bad name'):
        result = runner.invoke(args=['create-admin', bad])
        assert result.exit_code != 0
        assert '用户名需为' in result.output
        with app.app_context():
            assert User.query.filter_by(username=bad).first() is None


def test_seed_refuses_production(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    import subprocess
    proc = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(__file__), '..', 'seed.py')],
        capture_output=True, text=True,
        env={**os.environ, 'APP_ENV': 'production', 'SECRET_KEY': 'x' * 32})
    assert proc.returncode != 0
    assert '生产环境' in (proc.stdout + proc.stderr)


def _run_seed(args, db_file):
    """在隔离的临时库上跑 seed.py(DATABASE_URL 指向 tmp,绝不碰 instance 真实库)。"""
    import subprocess
    env = {**os.environ, 'APP_ENV': 'development',
           'SECRET_KEY': 'x' * 32,
           'DATABASE_URL': f'sqlite:///{db_file}'}
    env.pop('PYTEST_CURRENT_TEST', None)
    return subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(__file__), '..', 'seed.py'), *args],
        capture_output=True, text=True, env=env)


def test_seed_drop_requires_force(tmp_path):
    """--drop 防误清:库已有数据时,不加 --force 应拒绝清空并提示;加 --force 才执行。"""
    import sqlite3
    db_file = tmp_path / 'seedtest.db'

    # 首次:空库 + --force 建 schema 并灌入演示数据
    proc = _run_seed(['--drop', '--force'], db_file)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert db_file.exists()

    def _counts():
        con = sqlite3.connect(str(db_file))
        try:
            q = con.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
            u = con.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            return q, u
        finally:
            con.close()

    q0, u0 = _counts()
    assert q0 > 0 and u0 == 2  # admin + student

    # 库已有数据 + 仅 --drop(无 --force):必须拒绝且不清库
    proc = _run_seed(['--drop'], db_file)
    assert '--force' in proc.stdout
    assert _counts() == (q0, u0)  # 数据原封不动

    # 追加一行,再用 --drop --force:应清空重建(行数回到基线,而非累加)
    con = sqlite3.connect(str(db_file))
    con.execute("INSERT INTO users (username, password_hash, role, "
                "must_change_password, is_active) VALUES ('extra', 'x', 'student', 0, 1)")
    con.commit()
    con.close()
    assert _counts()[1] == 3
    proc = _run_seed(['--drop', '--force'], db_file)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _counts() == (q0, u0)  # 清空重建,extra 已消失


def test_account_full_lifecycle(app, client, login):
    """spec §5「账号全流程」端到端:建号→初始密码登录→强制改密→正常使用→停用→拒登。"""
    from tests.conftest import plant_captcha

    def _raw_login(username, password):
        with client.session_transaction() as sess:
            token = sess.get('csrf_token', '')
        plant_captcha(client, 'TEST')
        return client.post('/login', data={'username': username, 'password': password,
                                           'captcha': 'TEST', 'csrf_token': token})

    login('admin', 'AdminPass123456')
    r = _post(client, '/api/overview/users', {'username': 'journey', 'role': 'student'})
    initial_pw = r.get_json()['data']['initial_password']
    from models import User as _User
    with app.app_context():
        uid = _User.query.filter_by(username='journey').first().id
    client.get('/logout')

    assert _raw_login('journey', initial_pw).status_code == 302     # 初始密码可登录
    r = client.get('/questions')
    assert r.status_code == 302 and '/change_password' in r.headers['Location']  # 强制改密

    with client.session_transaction() as sess:
        token = sess['csrf_token']
    r = client.post('/change_password', data={
        'old_password': initial_pw, 'new_password': 'JourneyNewPass12',
        'confirm_password': 'JourneyNewPass12', 'csrf_token': token})
    assert r.status_code == 302
    assert client.get('/questions').status_code == 200              # 改密后正常使用

    client.get('/logout')
    login('admin', 'AdminPass123456')
    _post(client, f'/api/overview/users/{uid}/toggle_active', {})   # 停用
    client.get('/logout')
    r = _raw_login('journey', 'JourneyNewPass12')
    assert '已被停用' in r.get_data(as_text=True)                   # 拒登
