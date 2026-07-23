"""个人学习工具 API(蓝图 api_study):私人笔记 + 收藏书签。

均限定当前登录用户(g.user)。笔记 1:1 upsert;收藏 toggle。
"""
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from auth import login_required
from models import Question, QuestionBookmark, QuestionNote, db

bp = Blueprint('api_study', __name__, url_prefix='/api')

MAX_NOTE_LEN = 20000


def _ok(data=None, message=None, status=200):
    payload = {'success': True}
    if data is not None:
        payload['data'] = data
    if message:
        payload['message'] = message
    return jsonify(payload), status


def _err(error, code='INVALID_INPUT', status=400):
    return jsonify(success=False, error=error, code=code), status


def _question_or_none(qid):
    return db.session.get(Question, qid)


# ------------------------------------------------------------------ 笔记
@bp.route('/questions/<int:qid>/note', methods=['GET'])
@login_required
def get_note(qid):
    note = QuestionNote.query.filter_by(user_id=g.user.id, question_id=qid).first()
    return _ok({'content': note.content if note else ''})


@bp.route('/questions/<int:qid>/note', methods=['PUT'])
@login_required
def put_note(qid):
    if _question_or_none(qid) is None:
        return _err('题目不存在', code='NOT_FOUND', status=404)
    data = request.get_json(silent=True) or {}
    content = data.get('content')
    if not isinstance(content, str):
        return _err('content 必须为字符串')
    if len(content) > MAX_NOTE_LEN:
        return _err(f'笔记过长(上限 {MAX_NOTE_LEN} 字)')
    note = QuestionNote.query.filter_by(user_id=g.user.id, question_id=qid).first()
    if note is None:
        note = QuestionNote(user_id=g.user.id, question_id=qid, content=content)
        db.session.add(note)
    else:
        note.content = content
        note.updated_at = datetime.now()
    db.session.commit()
    return _ok({'content': note.content}, message='已保存')


# ------------------------------------------------------------------ 收藏
@bp.route('/questions/<int:qid>/bookmark', methods=['GET'])
@login_required
def get_bookmark(qid):
    bm = QuestionBookmark.query.filter_by(user_id=g.user.id, question_id=qid).first()
    return _ok({'bookmarked': bm is not None})


@bp.route('/questions/<int:qid>/bookmark', methods=['POST'])
@login_required
def toggle_bookmark(qid):
    if _question_or_none(qid) is None:
        return _err('题目不存在', code='NOT_FOUND', status=404)
    bm = QuestionBookmark.query.filter_by(user_id=g.user.id, question_id=qid).first()
    if bm is None:
        db.session.add(QuestionBookmark(user_id=g.user.id, question_id=qid))
        db.session.commit()
        return _ok({'bookmarked': True}, message='已收藏')
    db.session.delete(bm)
    db.session.commit()
    return _ok({'bookmarked': False}, message='已取消收藏')


@bp.route('/bookmarks', methods=['GET'])
@login_required
def list_bookmarks():
    """当前用户收藏的题目 id 列表(供列表页批量标星)。"""
    ids = [b.question_id for b in
           QuestionBookmark.query.filter_by(user_id=g.user.id)
           .order_by(QuestionBookmark.created_at.desc()).all()]
    return _ok({'question_ids': ids})
