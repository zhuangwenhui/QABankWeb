"""templates/_macros.html:宏产出的 DOM 必须与抽取前的手写标记完全一致。

V1 收尾时把四份面包屑与五张统计卡外壳抽成了 Jinja 宏。templates/ 1756 行此前**零自动化覆盖**
(只有 scripts/audit_render.py 的人工巡检),抽宏抽错了不会有任何测试变红,只会在页面上看出来。
这份测试把抽取前的标记原样钉在断言里 —— 宏改坏了、少个 class、图标名写错,立刻红。

断言前把 HTML 的空白折叠:宏产出的缩进与手写时不同(Jinja 的宏体从行首展开),
但那是源码观感,不影响 DOM。
"""
import re

def norm(h):
    return re.sub(r'>\s+<', '><', re.sub(r'\s+', ' ', h)).strip()

def test_breadcrumb_dom(client, login):
    login('admin', 'AdminPass123456')
    for path, label in {'/questions': '题目管理', '/error_book': '错题本',
                        '/overview': '管理总览', '/feedback': '意见反馈'}.items():
        html = client.get(path).get_data(as_text=True)
        exp = norm(f'<div class="breadcrumb-container"><div class="breadcrumb-custom">'
                   f'<a href="/questions"><i class="fa-solid fa-house"></i> 首页</a>'
                   f'<span class="breadcrumb-separator">/</span><span>{label}</span></div></div>')
        assert exp in norm(html), f'{path} 面包屑 DOM 不一致'

def test_stat_card_dom(client, login):
    login('admin', 'AdminPass123456')
    ov = norm(client.get('/overview').get_data(as_text=True))
    for icon, title, bid, cls in [
            ('fa-layer-group', '按科目题数分布', 'subjectDist', 'h-100'),
            ('fa-gauge-high', '难度分布', 'difficultyDist', 'h-100'),
            ('fa-chart-column', '近 14 天题目查看趋势', 'viewTrend', 'mb-4'),
            ('fa-book-bookmark', '全体用户错题按科目分布', 'errorDist', 'h-100'),
            ('fa-clock-rotate-left', '最近新增题目', 'recentQuestions', 'mb-4')]:
        exp = norm(f'<div class="overview-card card {cls}">'
                   f'<div class="card-header"><i class="fa-solid {icon} me-1 text-primary"></i>{title}</div>'
                   f'<div class="card-body" id="{bid}">'
                   f'<div class="loading-block"><div class="spinner-border spinner-border-sm"></div> 加载中...</div>'
                   f'</div></div>')
        assert exp in ov, f'stat_card {bid} DOM 不一致'
