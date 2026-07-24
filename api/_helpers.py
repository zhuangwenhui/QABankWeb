"""蓝图共用小工具。

集中此前在各 api/*.py 各抄一份的响应信封(曾命名分裂 _err/_fail)、LIKE 转义,
并提供**单一实现**的题目全文搜索,消除 questions/error_book 的搜索行为漂移
(错题本此前漏了 solution_ja 与知识点标签命中)。

仅依赖 flask 与 models,不依赖任何蓝图,无循环导入。
"""
from datetime import datetime, timedelta

from flask import jsonify


def ok(data=None, message=None, status=200):
    """成功信封:{success:True, data?, message?}。"""
    payload = {'success': True}
    if data is not None:
        payload['data'] = data
    if message:
        payload['message'] = message
    return jsonify(payload), status


def err(error, code='INVALID_INPUT', status=400):
    """失败信封:{success:False, error, code}。"""
    return jsonify(success=False, error=error, code=code), status


def escape_like(term):
    """转义 LIKE 通配符,配合 like(..., escape='\\\\') 使用。"""
    return (term.replace('\\', '\\\\')
                .replace('%', '\\%')
                .replace('_', '\\_'))


def apply_question_search(query, search):
    """把「多词 AND 全文搜索」施加到已含 Question 的 query 并返回。

    每词命中 = 出现在 question_latex/solution_latex/solution_ja/source/chapter 任一,
    或该题挂有名称含此词的知识点标签(子查询,不与主查询 join 冲突)。上限 6 词。
    questions 与 error_book 共用此单一实现,杜绝两处搜索覆盖面漂移。
    """
    from sqlalchemy import or_

    from models import Question, QuestionTag, Tag, db

    terms = [t for t in (search or '').split() if t][:6]
    for term in terms:
        pattern = f'%{escape_like(term)}%'
        tag_match = (db.session.query(QuestionTag.question_id)
                     .join(Tag, Tag.id == QuestionTag.tag_id)
                     .filter(Tag.category == '知识点',
                             Tag.name.like(pattern, escape='\\')))
        query = query.filter(or_(
            Question.question_latex.like(pattern, escape='\\'),
            Question.solution_latex.like(pattern, escape='\\'),
            Question.solution_ja.like(pattern, escape='\\'),
            Question.source.like(pattern, escape='\\'),
            Question.chapter.like(pattern, escape='\\'),
            Question.id.in_(tag_match),
        ))
    return query


def prune_view_logs(retention_days=180):
    """删除超过保留期的查看日志,防 view_logs 无界增长拖慢统计聚合(rank17)。

    调用方按 id 采样触发(非每次),失败静默(不影响主写入)。
    """
    from models import ViewLog, db

    cutoff = datetime.now() - timedelta(days=retention_days)
    try:
        ViewLog.query.filter(ViewLog.viewed_at < cutoff).delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
