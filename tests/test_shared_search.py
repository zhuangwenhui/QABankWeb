"""技术债修复:共享题目搜索(消除错题本搜索漂移)+ view_logs 保留期清理。

rank9:questions 与 error_book 共用 api/_helpers.apply_question_search,
错题本此前漏 solution_ja 与知识点标签命中,现应与主列表一致。
rank17:prune_view_logs 删超期查看日志。
"""
from datetime import datetime, timedelta

from models import (Question, Tag, QuestionTag, ErrorBook, ViewLog, User, db)


def _student_id(app):
    with app.app_context():
        return User.query.filter_by(username='student').first().id


def _seed_errorbook(app):
    """建两题挂到 student 错题本:q_ja 的唯一词只在 solution_ja;q_tag 的词只在知识点标签名。"""
    uid = _student_id(app)
    with app.app_context():
        q_ja = Question(subject='数学', difficulty='中等',
                        question_latex='テスト問題', solution_latex='中文',
                        solution_ja='ディリクレ核を用いる')
        q_tag = Question(subject='数学', difficulty='中等', question_latex='行列の対角化')
        q_none = Question(subject='数学', difficulty='中等', question_latex='無関係')
        db.session.add_all([q_ja, q_tag, q_none])
        db.session.commit()
        t = Tag(name='線形代数', category='知识点')
        db.session.add(t)
        db.session.commit()
        db.session.add(QuestionTag(question_id=q_tag.id, tag_id=t.id))
        db.session.add_all([
            ErrorBook(user_id=uid, question_id=q_ja.id),
            ErrorBook(user_id=uid, question_id=q_tag.id),
            ErrorBook(user_id=uid, question_id=q_none.id),
        ])
        db.session.commit()
        return {'ja': q_ja.id, 'tag': q_tag.id, 'none': q_none.id}


def _eb_ids(client, query):
    r = client.get('/api/error_book' + query)
    assert r.status_code == 200, r.get_data(as_text=True)
    return {e['question_id'] for e in r.get_json()['data']['entries']}


def test_errorbook_search_hits_solution_ja(app, client, login):
    """漂移修复:错题本搜索现命中日本語詳解轨(修复前搜不到)。"""
    login('student', 'StudentPass123456')
    ids = _seed_errorbook(app)
    assert _eb_ids(client, '?search=ディリクレ') == {ids['ja']}


def test_errorbook_search_hits_knowledge_tag(app, client, login):
    """漂移修复:错题本搜索现命中知识点标签名(正文无此词也命中)。"""
    login('student', 'StudentPass123456')
    ids = _seed_errorbook(app)
    got = _eb_ids(client, '?search=線形代数')
    assert ids['tag'] in got  # q_tag 正文是「行列の対角化」,靠标签命中


def test_errorbook_search_multiterm_and(app, client, login):
    """多词 AND:两词须落同一题。"""
    login('student', 'StudentPass123456')
    ids = _seed_errorbook(app)
    # テスト(q_ja.question_latex) + ディリクレ(q_ja.solution_ja)→ 仅 q_ja
    assert _eb_ids(client, '?search=テスト ディリクレ') == {ids['ja']}


def test_prune_view_logs(app):
    """rank17:prune_view_logs 删超期日志、留窗口内日志。"""
    from api._helpers import prune_view_logs
    with app.app_context():
        u = User.query.filter_by(username='student').first()
        q = Question(subject='数学', difficulty='中等', question_latex='q')
        db.session.add(q)
        db.session.commit()
        old = ViewLog(user_id=u.id, question_id=q.id,
                      viewed_at=datetime.now() - timedelta(days=200))
        fresh = ViewLog(user_id=u.id, question_id=q.id,
                        viewed_at=datetime.now() - timedelta(days=5))
        db.session.add_all([old, fresh])
        db.session.commit()
        assert ViewLog.query.count() == 2
        prune_view_logs(retention_days=180)
        remaining = ViewLog.query.all()
        assert len(remaining) == 1 and remaining[0].id == fresh.id
