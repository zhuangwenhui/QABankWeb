"""删除题目的级联护栏。

「删除题目」这个基础功能从 v1.3 加知识点标签起就一直是坏的:Question 只对 error_book 与
view_logs 声明了级联,之后新增的六张带 question_id 外键的表都没补,SQLite 直接抛
FOREIGN KEY constraint failed,端点 500。而每道题都有标签 —— 也就是任何一道题都删不掉,
直到 2026-07-26 才被发现。此文件确保它不会再悄悄退化。
"""
import sqlalchemy as sa

from models import (AnswerSubmission, ErrorBook, Question, QuestionBookmark, QuestionList,
                    QuestionListItem, QuestionNote, QuestionProgress, QuestionTag, Tag,
                    User, ViewLog, db)


def _question(**kw):
    q = Question(subject='数学', chapter='测试', difficulty='中等',
                 source='级联测试', question_latex='题面', **kw)
    db.session.add(q)
    db.session.commit()
    return q


def test_delete_question_with_every_kind_of_child_row(app):
    """挂满所有子表的题目也必须能删干净,且不留孤儿行。"""
    with app.app_context():
        user = User.query.filter_by(username='student').first()
        q = _question()
        lst = QuestionList(owner_id=user.id, title='测试题单')
        tag = Tag(name='级联测试标签', category='测试')
        db.session.add_all([lst, tag])
        db.session.commit()

        db.session.add_all([
            ErrorBook(user_id=user.id, question_id=q.id),
            ViewLog(user_id=user.id, question_id=q.id),
            QuestionProgress(user_id=user.id, question_id=q.id, status='done'),
            QuestionListItem(list_id=lst.id, question_id=q.id, position=1),
            QuestionNote(user_id=user.id, question_id=q.id, content='笔记'),
            QuestionBookmark(user_id=user.id, question_id=q.id),
            QuestionTag(question_id=q.id, tag_id=tag.id),
            AnswerSubmission(user_id=user.id, question_id=q.id),
        ])
        db.session.commit()
        qid = q.id

        db.session.delete(q)
        db.session.commit()          # 有任何一张子表没级联,这里就抛 IntegrityError

        assert db.session.get(Question, qid) is None
        for model in (ErrorBook, ViewLog, QuestionProgress, QuestionListItem,
                      QuestionNote, QuestionBookmark, QuestionTag, AnswerSubmission):
            left = model.query.filter_by(question_id=qid).count()
            assert left == 0, f'{model.__name__} 残留 {left} 行孤儿'


def test_every_table_with_question_fk_is_cascaded():
    """任何带 question_id 外键的表都必须在 Question 上登记级联关系。

    这条比上面那条更狠:以后新增子表却忘了补级联,这里直接红,不用等有人去删题。
    """
    cascaded = {rel.mapper.class_.__tablename__
                for rel in sa.inspect(Question).relationships
                if 'delete' in (rel.cascade or '')}
    missing = []
    for table in db.metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name == 'questions' and table.name not in cascaded:
                missing.append(table.name)
    assert not missing, f'这些表引用了 questions 却没在 Question 上配级联:{sorted(set(missing))}'


def test_delete_endpoint_returns_success(client, app, login):
    """走真实端点:管理员删题应 200,而不是 500。"""
    from tests.conftest import get_csrf
    with app.app_context():
        q = _question()
        tag = Tag(name='端点级联标签', category='测试')
        db.session.add(tag)
        db.session.commit()
        db.session.add(QuestionTag(question_id=q.id, tag_id=tag.id))
        db.session.commit()
        qid = q.id

    login('admin', 'AdminPass123456')
    resp = client.delete(f'/api/questions/{qid}',
                         headers={'X-CSRFToken': get_csrf(client)})
    assert resp.status_code == 200, resp.data
    with app.app_context():
        assert db.session.get(Question, qid) is None
