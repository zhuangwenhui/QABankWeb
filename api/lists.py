"""题单 API(蓝图 api_lists,url_prefix='/api/lists')。

题单(curated 学习路径):有序题目集合。分官方精选(is_official,仅 admin 可建/改)
与用户自建。全部接口需登录。统一响应信封见 api/questions.py。

进度语义与 api/progress.py 对齐:有 QuestionProgress 行即计入 done(含 mastered),
status=='mastered' 另计入 mastered。
"""
from flask import Blueprint, current_app, g, request
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError

from auth import login_required
from api._helpers import ok as _ok, err as _fail
from models import (Question, QuestionList, QuestionListItem,
                    QuestionProgress, db)

bp = Blueprint('api_lists', __name__, url_prefix='/api/lists')

_MAX_TITLE_LEN = 128
_MAX_DESC_LEN = 2000
_MAX_REORDER = 5000


# ---------------------------------------------------------------- 响应辅助

# 响应信封 _ok/_fail 已抽到 api/_helpers.py(见顶部别名导入,err as _fail)。


def _list_meta(lst, item_count, progress):
    return {
        'id': lst.id,
        'owner_id': lst.owner_id,
        'title': lst.title,
        'description': lst.description or '',
        'is_official': bool(lst.is_official),
        'is_public': bool(lst.is_public),
        'item_count': item_count,
        'progress': progress,
        'created_at': lst.created_at.strftime('%Y-%m-%d %H:%M:%S') if lst.created_at else None,
    }


def _can_edit(lst):
    """仅 owner 或 admin 可改;官方单由 admin 拥有,天然只有 admin 能动。"""
    return g.user.is_admin or lst.owner_id == g.user.id


def _parse_question_id(data):
    value = data.get('question_id')
    if isinstance(value, bool):
        return None
    try:
        qid = int(value)
    except (TypeError, ValueError):
        return None
    return qid if qid > 0 else None


# ---------------------------------------------------------------- 广场:列表

@bp.route('', methods=['GET'])
@login_required
def list_lists():
    """列出所有公开题单或自己拥有的题单;官方精选置顶。"""
    lists = (QuestionList.query
             .filter((QuestionList.is_public.is_(True))
                     | (QuestionList.owner_id == g.user.id))
             .order_by(QuestionList.is_official.desc(),
                       QuestionList.created_at.desc(),
                       QuestionList.id.desc())
             .all())
    lids = [l.id for l in lists]

    counts = dict(db.session.query(QuestionListItem.list_id,
                                   func.count(QuestionListItem.id))
                  .filter(QuestionListItem.list_id.in_(lids))
                  .group_by(QuestionListItem.list_id).all()) if lids else {}

    # 每单在当前用户下的 done/mastered(join 题单项 → 用户进度)
    prog = {}
    if lids:
        rows = (db.session.query(QuestionListItem.list_id,
                                 QuestionProgress.status,
                                 func.count(QuestionProgress.id))
                .join(QuestionProgress,
                      and_(QuestionProgress.question_id == QuestionListItem.question_id,
                           QuestionProgress.user_id == g.user.id))
                .filter(QuestionListItem.list_id.in_(lids))
                .group_by(QuestionListItem.list_id, QuestionProgress.status)
                .all())
        for lid, status, n in rows:
            bucket = prog.setdefault(lid, {'done': 0, 'mastered': 0})
            bucket['done'] += n
            if status == 'mastered':
                bucket['mastered'] += n

    result = []
    for lst in lists:
        total = counts.get(lst.id, 0)
        p = prog.get(lst.id, {'done': 0, 'mastered': 0})
        result.append(_list_meta(lst, total,
                                 {'total': total, 'done': p['done'],
                                  'mastered': p['mastered']}))
    return _ok({'lists': result})


# ---------------------------------------------------------------- 详情

@bp.route('/<int:lid>', methods=['GET'])
@login_required
def list_detail(lid):
    """题单详情:meta + 有序题目 + 当前用户在本单内的进度。"""
    lst = db.session.get(QuestionList, lid)
    if lst is None:
        return _fail('题单不存在', 'NOT_FOUND', 404)
    # 私有单仅 owner/admin 可见;不可见按 404 处理,避免泄露存在性
    if not lst.is_public and not _can_edit(lst):
        return _fail('题单不存在', 'NOT_FOUND', 404)

    items = (db.session.query(QuestionListItem, Question)
             .join(Question, Question.id == QuestionListItem.question_id)
             .filter(QuestionListItem.list_id == lid)
             .order_by(QuestionListItem.position.asc(),
                       QuestionListItem.id.asc())
             .all())
    questions = [q.to_dict(with_solution=False) for _item, q in items]
    qids = [q.id for _item, q in items]

    done = mastered = 0
    if qids:
        rows = (db.session.query(QuestionProgress.status,
                                 func.count(QuestionProgress.id))
                .filter(QuestionProgress.user_id == g.user.id,
                        QuestionProgress.question_id.in_(qids))
                .group_by(QuestionProgress.status).all())
        for status, n in rows:
            done += n
            if status == 'mastered':
                mastered += n

    progress = {'total': len(qids), 'done': done, 'mastered': mastered}
    return _ok({
        'list': _list_meta(lst, len(qids), progress),
        'questions': questions,
        'progress': progress,
    })


# ---------------------------------------------------------------- 创建

@bp.route('', methods=['POST'])
@login_required
def create_list():
    """创建题单(owner=当前用户)。仅 admin 可置 is_official=True。"""
    data = request.get_json(silent=True) or {}
    title = str(data.get('title') or '').strip()
    if not title:
        return _fail('标题不能为空')
    if len(title) > _MAX_TITLE_LEN:
        return _fail(f'标题不得超过 {_MAX_TITLE_LEN} 字')
    description = str(data.get('description') or '').strip()
    if len(description) > _MAX_DESC_LEN:
        return _fail(f'简介不得超过 {_MAX_DESC_LEN} 字')

    # is_official 仅管理员可置;非管理员一律建普通单
    is_official = bool(data.get('is_official')) and g.user.is_admin
    is_public = bool(data.get('is_public', True))

    lst = QuestionList(owner_id=g.user.id, title=title, description=description,
                       is_official=is_official, is_public=is_public)
    db.session.add(lst)
    db.session.commit()
    return _ok(_list_meta(lst, 0, {'total': 0, 'done': 0, 'mastered': 0}),
               message='题单已创建')


# ---------------------------------------------------------------- 加题 / 移除

@bp.route('/<int:lid>/items', methods=['POST'])
@login_required
def add_item(lid):
    """向题单加题(position=末尾+1)。仅 owner 或 admin 可改;重复加题幂等。"""
    lst = db.session.get(QuestionList, lid)
    if lst is None:
        return _fail('题单不存在', 'NOT_FOUND', 404)
    if not _can_edit(lst):
        return _fail('无权修改此题单', 'FORBIDDEN', 403)

    data = request.get_json(silent=True) or {}
    qid = _parse_question_id(data)
    if qid is None:
        return _fail('question_id 必须为正整数')
    if db.session.get(Question, qid) is None:
        return _fail('题目不存在', 'NOT_FOUND', 404)

    exists = QuestionListItem.query.filter_by(list_id=lid, question_id=qid).first()
    if exists is not None:
        return _ok({'list_id': lid, 'question_id': qid, 'position': exists.position},
                   message='题目已在题单中')

    max_pos = (db.session.query(func.max(QuestionListItem.position))
               .filter(QuestionListItem.list_id == lid).scalar())
    next_pos = 0 if max_pos is None else max_pos + 1
    try:
        with db.session.begin_nested():
            db.session.add(QuestionListItem(list_id=lid, question_id=qid,
                                            position=next_pos))
        db.session.commit()
    except IntegrityError:
        # 并发下另一请求已插入同一 (list, question):按幂等处理
        db.session.rollback()
        exists = QuestionListItem.query.filter_by(list_id=lid, question_id=qid).first()
        return _ok({'list_id': lid, 'question_id': qid,
                    'position': exists.position if exists else next_pos},
                   message='题目已在题单中')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('题单加题失败 list=%s question=%s', lid, qid)
        return _fail('加题失败,请稍后重试', 'SERVER_ERROR', 500)

    return _ok({'list_id': lid, 'question_id': qid, 'position': next_pos},
               message='已加入题单')


@bp.route('/<int:lid>/items/<int:qid>', methods=['DELETE'])
@login_required
def remove_item(lid, qid):
    """从题单移除题目。仅 owner 或 admin 可改。"""
    lst = db.session.get(QuestionList, lid)
    if lst is None:
        return _fail('题单不存在', 'NOT_FOUND', 404)
    if not _can_edit(lst):
        return _fail('无权修改此题单', 'FORBIDDEN', 403)

    item = QuestionListItem.query.filter_by(list_id=lid, question_id=qid).first()
    if item is None:
        return _fail('该题不在此题单中', 'NOT_FOUND', 404)
    db.session.delete(item)
    db.session.commit()
    return _ok({'list_id': lid, 'question_id': qid}, message='已移除')


# ---------------------------------------------------------------- 重排

@bp.route('/<int:lid>/reorder', methods=['POST'])
@login_required
def reorder_items(lid):
    """按给定 question_ids 顺序重排 position。仅 owner 或 admin 可改。"""
    lst = db.session.get(QuestionList, lid)
    if lst is None:
        return _fail('题单不存在', 'NOT_FOUND', 404)
    if not _can_edit(lst):
        return _fail('无权修改此题单', 'FORBIDDEN', 403)

    data = request.get_json(silent=True) or {}
    order = data.get('question_ids')
    if not isinstance(order, list) or len(order) > _MAX_REORDER:
        return _fail('question_ids 必须是列表')

    items = {it.question_id: it for it in
             QuestionListItem.query.filter_by(list_id=lid).all()}
    seen = set()
    pos = 0
    for raw in order:
        if isinstance(raw, bool):
            return _fail('question_ids 含非法元素')
        try:
            qid = int(raw)
        except (TypeError, ValueError):
            return _fail('question_ids 含非法元素')
        if qid in seen:
            continue
        seen.add(qid)
        it = items.get(qid)
        if it is not None:
            it.position = pos
            pos += 1
    # 未在给定顺序中的既有题目顺延排到末尾(保持相对稳定)
    for qid, it in items.items():
        if qid not in seen:
            it.position = pos
            pos += 1
    db.session.commit()
    return _ok({'list_id': lid}, message='顺序已更新')
