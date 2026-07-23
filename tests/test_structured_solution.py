"""渐进提示 + 采点结构化题解:模型列 / to_dict 回环 + 迁移列存在。

内容生成属另一单元,本测试只验证数据模型的可显示骨架:
  - 写入 hints(JSON 数组)/ solution_structured(JSON 对象)后 GET 单题能取回;
  - 空值题(旧题)返回 [] / {},页面照常;
  - 迁移在空库 upgrade 后 questions 表含两新列。
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config as config_module
from app import create_app
from models import Question, db

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), '..', 'migrations')

HINTS = ['先想:被积函数在围道内是否解析?', '回忆留数定理 $\\oint f\\,dz = 2\\pi i\\sum \\mathrm{Res}$。',
         '孤立奇点在 $z=0$,求其留数。']
STRUCTURED = {
    'houshin': '## 解答方針\n用留数定理化围道积分为留数之和。',
    'model': '## 答案例\n$\\oint_{|z|=1}\\frac{dz}{z}=2\\pi i$。',
    'shitten': ':::warn 典型失点\n漏判奇点是否落在围道内。\n:::',
    'haiten': ':::conclusion 部分点\n定理陈述 3 分 / 留数计算 4 分 / 结论 3 分。\n:::',
}


def _seed(app, **extra):
    """直接建题并写入结构化字段(内容写入非本单元 API 职责),返回 id。"""
    with app.app_context():
        q = Question(subject='复变函数', difficulty='中等', question_latex='求 $\\oint dz$')
        for k, v in extra.items():
            setattr(q, k, v)
        db.session.add(q)
        db.session.commit()
        return q.id


def test_to_dict_returns_hints_list_and_structured_dict(app, client, login):
    """写入 hints/solution_structured → GET /api/questions/<id> 取回为 list/dict。"""
    login('admin', 'AdminPass123456')
    qid = _seed(app,
                hints=json.dumps(HINTS, ensure_ascii=False),
                solution_structured=json.dumps(STRUCTURED, ensure_ascii=False))
    r = client.get(f'/api/questions/{qid}')
    assert r.status_code == 200, r.get_data(as_text=True)
    q = r.get_json()['data']['question']

    assert isinstance(q['hints'], list)
    assert q['hints'] == HINTS
    assert isinstance(q['solution_structured'], dict)
    assert set(q['solution_structured']) == {'houshin', 'model', 'shitten', 'haiten'}
    assert q['solution_structured']['houshin'].startswith('## 解答方針')


def test_to_dict_empty_defaults_to_list_and_dict(app, client, login):
    """旧题无此数据(列为 NULL):hints→[]、solution_structured→{},列在 DB 为 NULL。"""
    login('admin', 'AdminPass123456')
    qid = _seed(app)
    r = client.get(f'/api/questions/{qid}')
    assert r.status_code == 200
    q = r.get_json()['data']['question']
    assert q['hints'] == []
    assert q['solution_structured'] == {}
    with app.app_context():
        row = db.session.get(Question, qid)
        assert row.hints is None
        assert row.solution_structured is None


def test_to_dict_malformed_json_falls_back(app, client, login):
    """脏数据(非合法 JSON / 类型不符)容错为 [] / {},绝不 500。"""
    login('admin', 'AdminPass123456')
    qid = _seed(app, hints='{not json', solution_structured='[1,2,3]')
    r = client.get(f'/api/questions/{qid}')
    assert r.status_code == 200
    q = r.get_json()['data']['question']
    assert q['hints'] == []               # 解析失败
    assert q['solution_structured'] == {}  # 类型非 dict


def test_detail_page_mounts_hint_and_structured_containers(app, client, login):
    """详情页骨架含渐进提示与采点结构化两个惰性容器(由 JS 按数据填充)。"""
    login('admin', 'AdminPass123456')
    qid = _seed(app)
    html = client.get(f'/questions/{qid}').get_data(as_text=True)
    assert 'qdHints' in html          # 渐进提示容器
    assert 'qdStructured' in html      # 采点结构化容器


def test_review_page_script_supports_structured(client, login):
    """复习页渲染脚本包含采点四段渲染(复习揭示时也显示)。"""
    login('student', 'StudentPass123456')
    r = client.get('/review')
    assert r.status_code == 200
    # 脚本资源已挂载;采点四段渲染逻辑在 review.js 内(静态资源另测其存在)
    assert 'review.js' in r.get_data(as_text=True)


def test_migration_adds_hints_and_structured_columns(tmp_path):
    """空文件库 upgrade 后 questions 含 hints / solution_structured 两列。"""
    db_file = tmp_path / 'fresh.db'
    cfg = type('Cfg', (config_module.TestingConfig,),
               {'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_file}'})
    application = create_app(cfg)
    with application.app_context():
        from flask_migrate import upgrade
        upgrade(directory=MIGRATIONS_DIR)
        cols = {row[1] for row in db.session.execute(
            db.text('PRAGMA table_info(questions)'))}
        for col in ('hints', 'solution_structured'):
            assert col in cols, f'questions 缺列:{col}'
