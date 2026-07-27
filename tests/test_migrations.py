"""迁移冒烟:空文件库执行 flask db upgrade 后,库结构必须与 models 完全一致。

此前另有一份 60 行的**手工表列清单**逐个断言"某表某列在不在"。它的每一条都被下面这个
从 db.metadata 自动派生的比对严格包含,而且手工清单每加一张表就要同步一次(漏同步不会
有任何报错,只会静静地少查一张表),故于 V1 收尾时删除。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config as config_module
from app import create_app
from models import db

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), '..', 'migrations')



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
