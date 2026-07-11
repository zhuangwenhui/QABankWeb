"""双轨题解:solution_ja 存储/接口回环 + LeetCode 详情页路由。"""
from conftest import get_csrf
from models import Question, db


def _create(client, **extra):
    """带 CSRF 的 POST /api/questions 建题,返回响应 JSON。"""
    token = get_csrf(client)
    payload = {'subject': '复变函数', 'difficulty': '中等',
               'question_latex': '求 $\\oint dz$'}
    payload.update(extra)
    return client.post('/api/questions', json=payload,
                       headers={'X-CSRFToken': token})


def test_solution_ja_round_trips(client, login):
    """POST 带 solution_ja → to_dict / GET 单题都能取回。"""
    login('admin', 'AdminPass123456')
    ja = '## 問題重述\n本文は日本語の詳解。$e^{i\\pi}=-1$。'
    r = _create(client, solution_latex='中文速览', solution_ja=ja)
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()['data']['question']
    assert data['solution_ja'] == ja
    assert data['solution_latex'] == '中文速览'

    # 落库确认 + GET 单题回环
    qid = data['id']
    r2 = client.get(f'/api/questions/{qid}')
    assert r2.status_code == 200
    assert r2.get_json()['data']['question']['solution_ja'] == ja


def test_solution_ja_defaults_empty(client, login, app):
    """未提供 solution_ja 的旧式建题:列为 NULL,to_dict 输出空串(非 None)。"""
    login('admin', 'AdminPass123456')
    r = _create(client, solution_latex='仅中文')
    assert r.status_code == 200
    qid = r.get_json()['data']['question']['id']
    assert r.get_json()['data']['question']['solution_ja'] == ''
    with app.app_context():
        assert db.session.get(Question, qid).solution_ja is None


def test_detail_page_requires_login(client):
    """未登录访问详情页应重定向到登录。"""
    r = client.get('/questions/1')
    assert r.status_code in (302, 401)


def test_detail_page_404_when_missing(client, login):
    login('admin', 'AdminPass123456')
    r = client.get('/questions/999999')
    assert r.status_code == 404


def test_detail_page_has_two_panels_and_toggle(client, login):
    """登录后 GET 详情页:200,含左右两栏与中日语言切换。"""
    login('admin', 'AdminPass123456')
    created = _create(client, solution_latex='中文', solution_ja='日本語')
    qid = created.get_json()['data']['question']['id']
    r = client.get(f'/questions/{qid}')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # 左右两栏
    assert 'qdProblemPanel' in html
    assert 'qdSolutionPanel' in html
    # 中文/日本語 语言切换
    assert 'data-track="zh"' in html
    assert 'data-track="ja"' in html
    assert '中文' in html and '日本語' in html
    # 渲染器与样式资源已挂载
    assert 'question_detail.js' in html
    assert 'question-detail.css' in html
