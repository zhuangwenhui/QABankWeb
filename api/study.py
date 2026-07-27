"""个人学习工具 API(蓝图 api_study):私人笔记 + 收藏书签。

均限定当前登录用户(g.user)。笔记 1:1 upsert;收藏 toggle。
"""
from datetime import datetime

from flask import Blueprint, g, request
from sqlalchemy.exc import IntegrityError

from auth import login_required
from models import Question, QuestionBookmark, QuestionNote, db
from api._helpers import ok as _ok, err as _err

bp = Blueprint('api_study', __name__, url_prefix='/api')

MAX_NOTE_LEN = 20000


def _question_or_none(qid):
    """题目存在就返回,不存在返回 None。写入端点用它先挡掉不存在的题号 ——
    不挡的话会插出一条指向空题的笔记/收藏,外键在 SQLite 下要 PRAGMA 开了才拦得住。"""
    return db.session.get(Question, qid)


# ------------------------------------------------------------------ 笔记
@bp.route('/questions/<int:qid>/note', methods=['GET'])
@login_required
def get_note(qid):
    """取当前用户在该题下的笔记。没写过就返回空串,不是 404 —— 前端直接填进输入框。"""
    note = QuestionNote.query.filter_by(user_id=g.user.id, question_id=qid).first()
    return _ok({'content': note.content if note else ''})


@bp.route('/questions/<int:qid>/note', methods=['PUT'])
@login_required
def put_note(qid):
    """保存当前用户在该题下的笔记(整体覆盖,非追加)。

    空串是合法输入,表示清空笔记 —— 所以校验的是"必须是字符串"而不是"必须非空"。
    首次保存走 upsert:并发下两个标签页同时保存会撞唯一约束,由 SAVEPOINT 兜住转为更新。
    """
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
        try:
            # SAVEPOINT 的用意见 api/_helpers.py 顶部说明(并发下只回退这一条)
            with db.session.begin_nested():
                note = QuestionNote(user_id=g.user.id, question_id=qid, content=content)
                db.session.add(note)
        except IntegrityError:
            # 并发下另一请求已插入同一 (user,question):改为更新已存在行(幂等)
            note = QuestionNote.query.filter_by(user_id=g.user.id, question_id=qid).first()
            note.content = content
            note.updated_at = datetime.now()
    else:
        note.content = content
        note.updated_at = datetime.now()
    db.session.commit()
    return _ok({'content': note.content}, message='已保存')


# ------------------------------------------------------------------ 收藏
@bp.route('/questions/<int:qid>/bookmark', methods=['GET'])
@login_required
def get_bookmark(qid):
    """当前用户是否收藏了该题。"""
    bm = QuestionBookmark.query.filter_by(user_id=g.user.id, question_id=qid).first()
    return _ok({'bookmarked': bm is not None})


@bp.route('/questions/<int:qid>/bookmark', methods=['POST'])
@login_required
def toggle_bookmark(qid):
    """切换收藏状态,返回切换后的结果。

    是 toggle 不是 set:前端只有一个星标按钮,点一下反转。因此**同一请求重发不幂等** ——
    网络重试会把刚收藏的又取消掉。前端(question_detail.js)靠按钮禁用防重复点击。
    """
    if _question_or_none(qid) is None:
        return _err('题目不存在', code='NOT_FOUND', status=404)
    bm = QuestionBookmark.query.filter_by(user_id=g.user.id, question_id=qid).first()
    if bm is None:
        try:
            # SAVEPOINT 的用意见 api/_helpers.py 顶部说明(并发下只回退这一条)
            with db.session.begin_nested():
                db.session.add(QuestionBookmark(user_id=g.user.id, question_id=qid))
        except IntegrityError:
            pass  # 并发下已插入同一 (user,question):幂等视为已收藏
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
