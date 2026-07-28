"""院試定位筛选(时间/院校→専攻/学科范围)后端测试。"""
from datetime import datetime

from models import Question, db


def _seed():
    """植入跨院校/専攻/年份/学科的样本(source 标签走 exam-harvest 恒定格式)。"""
    rows = [
        # 東京科学大学 两个専攻
        ('算法', '2021', '東京科学大学 情報理工 2021 算法 第1問'),
        ('线性代数', '2021', '東京科学大学 数理計算科学 2021 数学 第1問'),
        ('概率统计', '2022', '東京科学大学 数理計算科学 2022 数学 第4問'),
        # 北海道大学
        ('复变函数', '2025', '北海道大学 情報理工 2025 复变 第1問'),
        ('微积分', '2024', '北海道大学 情報理工 2024 数学 第1問'),
        # 京都大学
        ('复变函数', '2025', '京都大学 情報学 2025 复变 第3問'),
        # 非院試格式(旧种子题):不应进入院校/専攻级联,但学科归组仍计入
        ('微积分', '1 変数関数の微分法', '微积分 期末'),
    ]
    for subject, chapter, source in rows:
        db.session.add(Question(subject=subject, chapter=chapter, difficulty='中等',
                                source=source, question_latex='x', created_at=datetime(2026, 1, 1)))
    db.session.commit()


def _facets(client):
    r = client.get('/api/questions/facets')
    assert r.status_code == 200
    return r.get_json()['data']


def _list(client, **params):
    from urllib.parse import urlencode
    r = client.get('/api/questions?' + urlencode(params))
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()['data']


def test_facets_nested_schools_years_groups(app, client, login):
    with app.app_context():
        _seed()
    login('student', 'StudentPass123456')
    data = _facets(client)

    schools = {s['name']: s for s in data['schools']}
    assert set(schools) == {'東京科学大学', '北海道大学', '京都大学'}
    # 東京科学大学 应有两个専攻,計数正确
    isct_majors = {m['name']: m['count'] for m in schools['東京科学大学']['majors']}
    assert isct_majors == {'情報理工': 1, '数理計算科学': 2}
    assert schools['東京科学大学']['count'] == 3
    # 年份倒序;含所有年份
    assert data['years'] == ['2025', '2024', '2022', '2021']
    # 学科范围归组带计数(非院試的微积分种子题也计入数学)
    groups = {g['name']: g['count'] for g in data['subjectGroups']}
    assert groups['复变'] == 2 and groups['算法'] == 1
    assert groups['数学'] == 4  # 线代1+概统1+微积分2(含种子题)


def test_filter_by_school(app, client, login):
    with app.app_context():
        _seed()
    login('student', 'StudentPass123456')
    data = _list(client, school='北海道大学')
    assert data['total'] == 2
    assert all('北海道大学' in q['source'] for q in data['questions'])


def test_filter_by_school_and_major(app, client, login):
    with app.app_context():
        _seed()
    login('student', 'StudentPass123456')
    data = _list(client, school='東京科学大学', major='数理計算科学')
    assert data['total'] == 2
    assert all('数理計算科学' in q['source'] for q in data['questions'])


def test_filter_by_year(app, client, login):
    with app.app_context():
        _seed()
    login('student', 'StudentPass123456')
    data = _list(client, year='2025')
    assert data['total'] == 2
    assert {q['source'].split()[0] for q in data['questions']} == {'北海道大学', '京都大学'}


def test_filter_by_subject_group(app, client, login):
    with app.app_context():
        _seed()
    login('student', 'StudentPass123456')
    data = _list(client, subjectGroup='复变')
    assert data['total'] == 2
    assert all(q['subject'] == '复变函数' for q in data['questions'])


def test_combined_school_year_group(app, client, login):
    with app.app_context():
        _seed()
    login('student', 'StudentPass123456')
    data = _list(client, school='北海道大学', year='2025', subjectGroup='复变')
    assert data['total'] == 1
    assert data['questions'][0]['source'] == '北海道大学 情報理工 2025 复变 第1問'


def test_major_prefix_not_substring_collision(app, client, login):
    """専攻锚定用 '{校} {専攻} ' 前缀,不会把別校同名后缀误命中。"""
    with app.app_context():
        _seed()
    login('student', 'StudentPass123456')
    # 情報理工 属東京科学大学与北海道大学两校;仅指定北海道大学时不应带出東京科学大学的情報理工题
    data = _list(client, school='北海道大学', major='情報理工')
    assert data['total'] == 2
    assert all(q['source'].startswith('北海道大学 情報理工 ') for q in data['questions'])


# =================================================== /api/questions/filters
# 章节/来源/标签下拉字典。与 facets 同族但更朴素:不解析 source 的院試结构,
# 只做"去重 + 排序 + 可按课程收窄"。此前零测试覆盖。

def _filters(client, **params):
    from urllib.parse import urlencode
    qs = ('?' + urlencode(params)) if params else ''
    r = client.get('/api/questions/filters' + qs)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()['data']


def test_filters_dedups_and_sorts(app, client, login):
    with app.app_context():
        _seed()
    login('student', 'StudentPass123456')
    data = _filters(client)

    # _seed 里 '2021' 出现两次、'2025' 出现两次,字典里各只应有一份
    assert data['chapters'] == sorted(set(data['chapters']))
    assert len(data['chapters']) == len(set(data['chapters']))
    assert '2021' in data['chapters'] and '2025' in data['chapters']
    assert data['sources'] == sorted(set(data['sources']))


def test_filters_narrows_by_subject(app, client, login):
    with app.app_context():
        _seed()
    login('student', 'StudentPass123456')

    all_sources = set(_filters(client)['sources'])
    fukuhen = _filters(client, subject='复变函数')
    # 复变函数只有北大 2025 与京大 2025 两道
    assert set(fukuhen['sources']) == {'北海道大学 情報理工 2025 复变 第1問',
                                       '京都大学 情報学 2025 复变 第3問'}
    assert set(fukuhen['sources']) < all_sources


def test_filters_collects_tags_from_json_column(app, client, login):
    """tags 取自 Question.tags 这一列(JSON 数组字符串),与 tags 表无关。"""
    with app.app_context():
        q = Question(subject='微积分', chapter='ch', difficulty='中等',
                     source='src', question_latex='x')
        q.tags_list = ['换元', '分部积分', '换元']       # 重复项应被去掉
        db.session.add(q)
        db.session.commit()
    login('student', 'StudentPass123456')

    assert _filters(client)['tags'] == ['分部积分', '换元']


def test_filters_tolerates_broken_tags_json(app, client, login):
    """标签列存了非法 JSON 或非数组时按空处理,不能让整个字典接口 500。

    这是真实存在的形态:早期导入脚本往 tags 里写过裸字符串。
    """
    with app.app_context():
        for raw in ('not json at all', '{"a": 1}', '', None):
            db.session.add(Question(subject='微积分', chapter='ch', difficulty='中等',
                                    source='src', question_latex='x', tags=raw))
        good = Question(subject='微积分', chapter='ch', difficulty='中等',
                        source='src', question_latex='x')
        good.tags_list = ['正常标签']
        db.session.add(good)
        db.session.commit()
    login('student', 'StudentPass123456')

    assert _filters(client)['tags'] == ['正常标签']


def test_filters_skips_blank_values(app, client, login):
    """空章节/空来源/空白标签不进下拉框 —— 否则用户会看到一个选不中任何题的空选项。"""
    with app.app_context():
        q = Question(subject='微积分', chapter='', difficulty='中等',
                     source='', question_latex='x')
        q.tags_list = ['  ', '', '有效']
        db.session.add(q)
        db.session.commit()
    login('student', 'StudentPass123456')

    data = _filters(client)
    assert data['chapters'] == [] and data['sources'] == []
    assert data['tags'] == ['有效']


def test_filters_requires_login(app, client):
    r = client.get('/api/questions/filters')
    assert r.status_code == 401
    assert r.get_json()['code'] == 'UNAUTHORIZED'
