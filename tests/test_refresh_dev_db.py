"""`scripts/refresh_dev_db.py` 的护栏。

这个脚本会 `DELETE FROM` 五张内容表加六张用户表,是仓库里破坏力最大的脚本。
它平时对着开发库跑、出事也只是本地重来,但两件事一旦失手代价就不可逆:
指错库(比如 --db 填成生产路径),或者结构不一致时硬灌导致列错位。
本文件把这两道闸门、以及"账号必须留下"这条不变量钉死。

全部走真实子进程 + 真实 SQLite 文件,不 mock —— 要验的正是它对文件的实际操作。
"""
import pathlib
import sqlite3
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'refresh_dev_db.py'

CONTENT_TABLES = ['questions', 'tags', 'question_tags',
                  'question_lists', 'question_list_items']


def _make_db(path, version='abc123'):
    """按 models 的真实 schema 建一个空库,并写入 alembic 版本号。"""
    import os
    os.environ.setdefault('SECRET_KEY', 'x' * 32)
    from models import db
    from sqlalchemy import create_engine
    engine = create_engine(f'sqlite:///{path}')
    db.metadata.create_all(engine)
    engine.dispose()
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)')
    con.execute('DELETE FROM alembic_version')
    con.execute('INSERT INTO alembic_version VALUES (?)', (version,))
    con.commit()
    con.close()


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, cwd=str(ROOT))


@pytest.fixture()
def dbs(tmp_path):
    """一对结构相同的库:snap 装内容,local 装账号与旧内容。"""
    snap, local = tmp_path / 'snap.db', tmp_path / 'local.db'
    _make_db(snap)
    _make_db(local)

    # 走裸 sqlite3 而不是 ORM:模型的 Python 侧默认值不落进 DDL,所以 NOT NULL 的列
    # 这里必须逐个显式给值(difficulty / is_official / role 等都属此列)。
    user_cols = 'id,username,password_hash,role,must_change_password,is_active'
    s = sqlite3.connect(snap)
    s.execute("INSERT INTO questions(id,subject,difficulty,question_latex)"
              " VALUES(1,'微积分','中等','新题一')")
    s.execute("INSERT INTO questions(id,subject,difficulty,question_latex)"
              " VALUES(2,'算法','困难','新题二')")
    s.execute("INSERT INTO tags(id,name,category) VALUES(1,'换元','知识点')")
    s.execute("INSERT INTO question_tags(question_id,tag_id) VALUES(1,1)")
    s.execute(f"INSERT INTO users({user_cols}) VALUES(9,'prod_admin','h','admin',0,1)")
    s.execute("INSERT INTO question_lists(id,owner_id,title,is_official,is_public)"
              " VALUES(1,9,'官方题单',1,1)")
    s.execute("INSERT INTO question_list_items(list_id,question_id,position) VALUES(1,1,0)")
    s.commit(); s.close()

    lo = sqlite3.connect(local)
    lo.execute(f"INSERT INTO users({user_cols}) VALUES(1,'me','local_hash','admin',0,1)")
    lo.execute(f"INSERT INTO users({user_cols}) VALUES(2,'stu','local_hash2','student',0,1)")
    lo.execute("INSERT INTO questions(id,subject,difficulty,question_latex)"
               " VALUES(1,'旧科目','简单','旧题')")
    lo.execute("INSERT INTO error_book(user_id,question_id) VALUES(1,1)")
    lo.execute("INSERT INTO view_logs(user_id,question_id) VALUES(1,1)")
    lo.commit(); lo.close()
    return snap, local


def _rows(path, table):
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    n = con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    con.close()
    return n


# --------------------------------------------------------------- 闸门
def test_refuses_production_path():
    """--db 指向 /srv/ 一律拒绝:那是生产库的位置,本脚本没有任何理由碰它。"""
    r = _run('--db', '/srv/question-bank/instance/question_bank.db', '--apply')
    assert r.returncode != 0
    assert '拒绝执行' in r.stdout + r.stderr


def test_refuses_on_schema_version_mismatch(dbs, tmp_path):
    """结构版本不一致时必须停:INSERT ... SELECT * 靠列序对齐,错位是静默写坏数据。"""
    snap, local = dbs
    other = tmp_path / 'other.db'
    _make_db(other, version='different')
    r = _run('--db', str(other), '--snapshot', str(snap), '--apply')
    assert r.returncode != 0
    assert '结构版本不一致' in r.stdout + r.stderr
    assert _rows(other, 'questions') == 0        # 一行都没动


def test_dry_run_writes_nothing(dbs):
    snap, local = dbs
    before = {t: _rows(local, t) for t in CONTENT_TABLES + ['users', 'error_book', 'view_logs']}
    r = _run('--db', str(local), '--snapshot', str(snap), '--no-images')
    assert r.returncode == 0, r.stdout + r.stderr
    assert '未写库' in r.stdout
    after = {t: _rows(local, t) for t in before}
    assert after == before


# --------------------------------------------------------------- 落库行为
def test_apply_replaces_content_and_keeps_accounts(dbs):
    snap, local = dbs
    r = _run('--db', str(local), '--snapshot', str(snap), '--apply', '--no-images')
    assert r.returncode == 0, r.stdout + r.stderr

    for t in CONTENT_TABLES:
        assert _rows(local, t) == _rows(snap, t), f'{t} 行数没对上'

    # 账号必须原样保留:把 users 一起覆盖会把开发者知道的本地密码换成线上哈希
    con = sqlite3.connect(f'file:{local}?mode=ro', uri=True)
    users = con.execute('SELECT username, password_hash FROM users ORDER BY id').fetchall()
    con.close()
    assert users == [('me', 'local_hash'), ('stu', 'local_hash2')]


def test_apply_clears_question_scoped_user_rows(dbs):
    """引用旧题 id 的用户数据必须清掉:新旧库 id 会重叠但指向不同的题,留着是静默指错。"""
    snap, local = dbs
    _run('--db', str(local), '--snapshot', str(snap), '--apply', '--no-images')
    assert _rows(local, 'error_book') == 0
    assert _rows(local, 'view_logs') == 0


def test_apply_rebinds_list_owner_to_local_admin(dbs):
    """题单 owner 指向生产的 admin(id=9),落到本地要改绑本地 admin(id=1)。"""
    snap, local = dbs
    _run('--db', str(local), '--snapshot', str(snap), '--apply', '--no-images')
    con = sqlite3.connect(f'file:{local}?mode=ro', uri=True)
    owners = {r[0] for r in con.execute('SELECT owner_id FROM question_lists')}
    con.close()
    assert owners == {1}


def test_apply_leaves_a_backup(dbs):
    snap, local = dbs
    _run('--db', str(local), '--snapshot', str(snap), '--apply', '--no-images')
    bak = pathlib.Path(str(local) + '.bak')
    assert bak.is_file() and bak.stat().st_size > 0
    # 备份里应还是刷新前的旧内容
    assert _rows(bak, 'questions') == 1
