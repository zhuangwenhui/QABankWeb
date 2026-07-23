"""学习闭环 · 间隔复习页可达性 + 导航「复习」链接与待复习徽标接口连通。

页面本身为静态骨架(内容由 review.js 动态渲染),故断言关键元素/资源已挂载;
徽标数据源(GET /api/review/stats)与到期计数连通另测。
"""
from conftest import get_csrf
from models import Question, db


def _seed_question(app, subject='微积分', difficulty='中等'):
    with app.app_context():
        q = Question(subject=subject, difficulty=difficulty, question_latex='x')
        db.session.add(q)
        db.session.commit()
        return q.id


def _add_to_error_book(client, qid):
    token = get_csrf(client)
    return client.post('/api/error_book/add', json={'question_id': qid},
                       headers={'X-CSRFToken': token})


# ---------------------------------------------------------------- 页面可达性

def test_review_page_requires_login(client):
    """未登录访问 /review 应重定向到登录(或 401)。"""
    r = client.get('/review')
    assert r.status_code in (302, 401)


def test_review_page_renders_key_elements(client, login):
    """登录后 GET /review:200 且含复习根容器、渲染脚本与其 CDN 依赖。"""
    login('student', 'StudentPass123456')
    r = client.get('/review')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'rvApp' in html                 # 复习页根容器
    assert 'review.js' in html             # 流程/渲染脚本
    assert 'review.css' in html            # 复习专属样式
    assert 'question-detail.css' in html   # 复用题面/题解排版
    assert 'markdown-it' in html           # 渲染依赖 CDN
    assert 'dompurify' in html             # 消毒依赖 CDN


# ---------------------------------------------------------------- 导航徽标

def test_nav_has_review_link_and_badge(client, login):
    """登录后任意页导航含「复习」链接、待复习徽标占位与其填充脚本。"""
    login('student', 'StudentPass123456')
    html = client.get('/questions').get_data(as_text=True)
    assert 'href="/review"' in html
    assert 'reviewBadge' in html
    assert 'nav_badge.js' in html


def test_review_stats_endpoint_reachable(client, login):
    """徽标数据源:GET /api/review/stats 登录后 200 且带 due_today。"""
    login('student', 'StudentPass123456')
    r = client.get('/api/review/stats')
    assert r.status_code == 200
    assert 'due_today' in r.get_json()['data']


def test_review_badge_reflects_due_count(app, client, login):
    """加入错题后 due_today 计数 ≥1,徽标数据源与到期口径连通。"""
    login('student', 'StudentPass123456')
    qid = _seed_question(app)
    assert _add_to_error_book(client, qid).status_code == 200
    data = client.get('/api/review/stats').get_json()['data']
    assert data['due_today'] >= 1
