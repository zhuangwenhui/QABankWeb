"""迁移冒烟:空文件库执行 flask db upgrade 后关键表齐备。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config as config_module
from app import create_app
from models import db

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), '..', 'migrations')


def test_upgrade_creates_schema(tmp_path):
    db_file = tmp_path / 'fresh.db'
    cfg = type('Cfg', (config_module.TestingConfig,),
               {'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_file}'})
    application = create_app(cfg)
    with application.app_context():
        from flask_migrate import upgrade
        upgrade(directory=MIGRATIONS_DIR)  # 显式传目录,不依赖 CWD
        names = {row[0] for row in db.session.execute(
            db.text("SELECT name FROM sqlite_master WHERE type='table'"))}
        # 覆盖全部迁移的产物:初始 5 表 + generated_files(Task8)
        # + question_progress(学习闭环)+ tags/question_tags(知识点标签)
        # + question_lists/question_list_items(题单)
        for table in ('users', 'questions', 'error_book', 'feedback',
                      'view_logs', 'generated_files', 'question_progress',
                      'tags', 'question_tags',
                      'question_lists', 'question_list_items'):
            assert table in names, f'缺表:{table}'
        # users 的新列(Task10 迁移):must_change_password / is_active
        user_cols = {row[1] for row in db.session.execute(
            db.text("PRAGMA table_info(users)"))}
        for col in ('must_change_password', 'is_active'):
            assert col in user_cols, f'users 缺列:{col}'
        # questions 的新列(双轨题解迁移):solution_ja(可空)
        question_cols = {row[1] for row in db.session.execute(
            db.text("PRAGMA table_info(questions)"))}
        assert 'solution_ja' in question_cols, 'questions 缺列:solution_ja'
        # question_progress 的列(学习闭环迁移):status / updated_at / user_id / question_id
        progress_cols = {row[1] for row in db.session.execute(
            db.text("PRAGMA table_info(question_progress)"))}
        for col in ('user_id', 'question_id', 'status', 'updated_at'):
            assert col in progress_cols, f'question_progress 缺列:{col}'
        # error_book 的 SM-2 新列(学习闭环迁移):ease / interval_days / repetitions / due_at / last_reviewed_at
        error_book_cols = {row[1] for row in db.session.execute(
            db.text("PRAGMA table_info(error_book)"))}
        for col in ('ease', 'interval_days', 'repetitions', 'due_at', 'last_reviewed_at'):
            assert col in error_book_cols, f'error_book 缺列:{col}'
        # tags 的列(知识点标签迁移):name / category
        tags_cols = {row[1] for row in db.session.execute(
            db.text("PRAGMA table_info(tags)"))}
        for col in ('name', 'category'):
            assert col in tags_cols, f'tags 缺列:{col}'
        # question_tags 的列(知识点标签迁移):question_id / tag_id
        qt_cols = {row[1] for row in db.session.execute(
            db.text("PRAGMA table_info(question_tags)"))}
        for col in ('question_id', 'tag_id'):
            assert col in qt_cols, f'question_tags 缺列:{col}'
        # question_lists 的列(题单迁移):owner_id / title / is_official / is_public
        ql_cols = {row[1] for row in db.session.execute(
            db.text("PRAGMA table_info(question_lists)"))}
        for col in ('owner_id', 'title', 'description', 'is_official', 'is_public'):
            assert col in ql_cols, f'question_lists 缺列:{col}'
        # question_list_items 的列(题单迁移):list_id / question_id / position
        qli_cols = {row[1] for row in db.session.execute(
            db.text("PRAGMA table_info(question_list_items)"))}
        for col in ('list_id', 'question_id', 'position'):
            assert col in qli_cols, f'question_list_items 缺列:{col}'
