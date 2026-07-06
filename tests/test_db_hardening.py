"""SQLite PRAGMA 加固:外键强制、WAL、busy_timeout。"""
import os
import sys

import pytest
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models import ErrorBook, db


def test_foreign_keys_enforced(app):
    """引用不存在的 question_id 必须触发 IntegrityError(FK 生效)。"""
    with app.app_context():
        db.session.add(ErrorBook(user_id=1, question_id=99999, notes=''))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_busy_timeout_and_wal(app_factory, tmp_path):
    """文件库上:busy_timeout=5000、journal_mode=WAL。"""
    db_file = tmp_path / 'hardening.db'
    application = app_factory(SQLALCHEMY_DATABASE_URI=f'sqlite:///{db_file}')
    with application.app_context():
        timeout = db.session.execute(db.text('PRAGMA busy_timeout')).scalar()
        assert int(timeout) == 5000
        mode = db.session.execute(db.text('PRAGMA journal_mode')).scalar()
        assert str(mode).lower() == 'wal'


def test_foreign_keys_pragma_on(app):
    with app.app_context():
        assert db.session.execute(db.text('PRAGMA foreign_keys')).scalar() == 1
