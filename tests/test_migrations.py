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
        # questions 的新列(渐进提示 + 采点结构化题解迁移):hints / solution_structured
        for col in ('hints', 'solution_structured'):
            assert col in question_cols, f'questions 缺列:{col}'
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


def test_upgrade_schema_matches_models(tmp_path):
    """漂移守卫(rank6):flask db upgrade 后 DB 的表/列集必须与 models 完全一致。

    期望表清单从 db.metadata 自动派生 —— 每加一张表零手工同步;'改了 models 忘写迁移'
    这类首次真库部署才炸的坑,在此用纯表/列对照兜住(避开 SQLite autogenerate 对
    索引/类型/默认值的噪声误报,只判最要命的表缺失与列增删)。
    """
    db_file = tmp_path / 'drift.db'
    cfg = type('Cfg', (config_module.TestingConfig,),
               {'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_file}'})
    application = create_app(cfg)
    with application.app_context():
        from flask_migrate import upgrade
        upgrade(directory=MIGRATIONS_DIR)
        model_schema = {t.name: {c.name for c in t.columns}
                        for t in db.metadata.sorted_tables}
        assert model_schema, '未从 models 采集到任何表'
        for table, model_cols in model_schema.items():
            db_cols = {row[1] for row in db.session.execute(
                db.text(f"PRAGMA table_info({table})"))}
            assert db_cols, f'迁移缺表(models 有但库无):{table} —— 忘写迁移?'
            missing = model_cols - db_cols
            assert not missing, f'{table} 迁移缺列 {missing} —— 忘写迁移?'
            extra = db_cols - model_cols
            assert not extra, f'{table} 库多出列 {extra} —— models 删了列但迁移未删?'
