"""学习闭环 · /questions 顶部进度面板(总进度 + 分组进度条 + 做题日历热力图)。

面板为服务端骨架(数据由 questions.js:initProgressPanel() 异步填充),故断言骨架
容器与样式已挂载;三个数据源(summary/calendar/stats)登录后各自可达且形状正确。
"""


# ---------------------------------------------------------------- 页面骨架

def test_questions_page_has_progress_panel(client, login):
    """登录后 GET /questions:200 且含进度面板容器与其专属样式表。"""
    login('student', 'StudentPass123456')
    r = client.get('/questions')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="progressPanel"' in html          # 进度面板根容器
    assert 'progress-panel.css' in html          # 面板专属样式
    assert 'id="ppCalGrid"' in html              # 热力图网格挂载点


# ---------------------------------------------------------------- 数据源可达

def test_progress_summary_endpoint_reachable(client, login):
    """总进度数据源:GET /api/progress/summary 登录后 200,带 overall/by_difficulty/by_subject。"""
    login('student', 'StudentPass123456')
    r = client.get('/api/progress/summary')
    assert r.status_code == 200
    data = r.get_json()['data']
    assert 'overall' in data
    assert 'by_difficulty' in data
    assert 'by_subject' in data


def test_progress_calendar_endpoint_reachable(client, login):
    """日历数据源:GET /api/progress/calendar 登录后 200,data.calendar 为逐日 [{date,count}]。"""
    login('student', 'StudentPass123456')
    r = client.get('/api/progress/calendar?days=365')
    assert r.status_code == 200
    data = r.get_json()['data']
    assert 'calendar' in data
    assert isinstance(data['calendar'], list)
    if data['calendar']:
        assert 'date' in data['calendar'][0]
        assert 'count' in data['calendar'][0]


def test_review_stats_endpoint_reachable(client, login):
    """待复习数据源:GET /api/review/stats 登录后 200,带 due_today。"""
    login('student', 'StudentPass123456')
    r = client.get('/api/review/stats')
    assert r.status_code == 200
    assert 'due_today' in r.get_json()['data']
