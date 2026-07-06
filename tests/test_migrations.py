"""迁移冒烟:空文件库执行 flask db upgrade 后关键表齐备。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config as config_module
from app import create_app
from models import db


def test_upgrade_creates_schema(tmp_path):
    db_file = tmp_path / 'fresh.db'
    cfg = type('Cfg', (config_module.TestingConfig,),
               {'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_file}'})
    application = create_app(cfg)
    with application.app_context():
        from flask_migrate import upgrade
        upgrade()  # 使用项目根 migrations/
        names = {row[0] for row in db.session.execute(
            db.text("SELECT name FROM sqlite_master WHERE type='table'"))}
        for table in ('users', 'questions', 'error_book', 'feedback', 'view_logs'):
            assert table in names, f'缺表:{table}'
