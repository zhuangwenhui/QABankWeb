"""复习队列 API(蓝图 api_review)。

复习队列 = 当前用户 error_book 成员 + SM-2 间隔调度。
所有数据均限定当前登录用户(g.user)。
"""
from datetime import date, datetime, time, timedelta

from flask import Blueprint, current_app, g, request
from sqlalchemy.orm import selectinload

from auth import login_required
from models import ErrorBook, Question, db
from api._helpers import ok as _ok, err as _err

bp = Blueprint('api_review', __name__, url_prefix='/api/review')

MAX_DUE_LIMIT = 100  # /due 单次返回上限
UPCOMING_WINDOW_DAYS = 7  # /stats 未来窗口天数

RATINGS = ('again', 'hard', 'good', 'easy')


# ---------------------------------------------------------------- SM-2 纯函数

def sm2_schedule(rating, ease, interval_days, repetitions):
    """rating: 'again'|'hard'|'good'|'easy'。返回 (ease, interval_days, repetitions)。

    ease 下限 1.3。again 重置连击、当日再来;good 走标准 SM-2;easy 更激进;hard 略缩。
    """
    ease = ease if ease else 2.5
    reps = repetitions or 0
    if rating == 'again':
        return (max(1.3, ease - 0.20), 0, 0)
    if rating == 'hard':
        iv = 1 if reps == 0 else (3 if reps == 1 else max(1, round(interval_days * 1.2)))
        return (max(1.3, ease - 0.15), iv, reps + 1)
    if rating == 'good':
        iv = 1 if reps == 0 else (6 if reps == 1 else max(1, round(interval_days * ease)))
        return (ease, iv, reps + 1)
    if rating == 'easy':
        iv = 2 if reps == 0 else (6 if reps == 1 else max(1, round(interval_days * ease * 1.3)))
        return (min(3.0, ease + 0.15), iv, reps + 1)
    raise ValueError('bad rating')


# ---------------------------------------------------------------- 工具函数

# 响应信封 _ok/_err 已抽到 api/_helpers.py(见顶部别名导入)。


def _parse_question_id(data):
    """从请求 JSON 中解析单个正整数 question_id,非法时返回 None。"""
    value = data.get('question_id')
    if isinstance(value, bool):
        return None
    try:
        qid = int(value)
    except (TypeError, ValueError):
        return None
    return qid if qid > 0 else None


def _entry_row(entry):
    """复习队列条目:题目 + error_book_id + SM-2 排期。"""
    return {
        'error_book_id': entry.id,
        'question_id': entry.question_id,
        'notes': entry.notes or '',
        'ease': entry.ease,
        'interval_days': entry.interval_days,
        'repetitions': entry.repetitions,
        'due_at': entry.due_at.strftime('%Y-%m-%d %H:%M:%S') if entry.due_at else None,
        'last_reviewed_at': (entry.last_reviewed_at.strftime('%Y-%m-%d %H:%M:%S')
                             if entry.last_reviewed_at else None),
        'question': entry.question.to_dict() if entry.question else None,
    }


# ---------------------------------------------------------------- 到期队列

@bp.route('/due', methods=['GET'])
@login_required
def due():
    """当前用户到期复习项:due_at 为 NULL(未排期=立即到期)或 <= 现在。"""
    limit = request.args.get('limit', 20, type=int)
    if limit < 1:
        limit = 20
    if limit > MAX_DUE_LIMIT:
        limit = MAX_DUE_LIMIT

    now = datetime.now()
    entries = (ErrorBook.query
               .filter(ErrorBook.user_id == g.user.id,
                       db.or_(ErrorBook.due_at.is_(None), ErrorBook.due_at <= now))
               .options(selectinload(ErrorBook.question))
               # NULL(立即到期)排在最前,其余按到期时间升序
               .order_by(ErrorBook.due_at.asc(), ErrorBook.id.asc())
               .limit(limit)
               .all())
    entries = [e for e in entries if e.question is not None]
    return _ok({'entries': [_entry_row(e) for e in entries], 'count': len(entries)})


# ---------------------------------------------------------------- 自评排期

@bp.route('/rate', methods=['POST'])
@login_required
def rate():
    """对到期题作四键自评,按 SM-2 重排下次复习时刻。"""
    data = request.get_json(silent=True) or {}
    qid = _parse_question_id(data)
    if qid is None:
        return _err('question_id 必须为正整数')

    rating = data.get('rating')
    if rating not in RATINGS:
        return _err('rating 必须是 again/hard/good/easy 之一')

    entry = ErrorBook.query.filter_by(user_id=g.user.id, question_id=qid).first()
    if entry is None:
        return _err('该题目不在复习队列中', 'NOT_FOUND', 404)

    new_ease, new_interval, new_reps = sm2_schedule(
        rating, entry.ease, entry.interval_days or 0, entry.repetitions)

    now = datetime.now()
    try:
        entry.ease = new_ease
        entry.interval_days = new_interval
        entry.repetitions = new_reps
        entry.last_reviewed_at = now
        entry.due_at = now + timedelta(days=new_interval)  # again 时 new_interval=0 → 当日再来
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('复习自评保存失败 question_id=%s', qid)
        return _err('复习进度保存失败,请稍后重试', 'SERVER_ERROR', 500)

    return _ok({
        'question_id': qid,
        'ease': entry.ease,
        'interval_days': entry.interval_days,
        'repetitions': entry.repetitions,
        'due_at': entry.due_at.strftime('%Y-%m-%d %H:%M:%S'),
        'last_reviewed_at': entry.last_reviewed_at.strftime('%Y-%m-%d %H:%M:%S'),
    }, message='已记录本次复习')


# ---------------------------------------------------------------- 统计

@bp.route('/stats', methods=['GET'])
@login_required
def stats():
    """复习概览:今日到期(含逾期/未排期)、未来 7 天、复习队列总量。"""
    now = datetime.now()
    today_end = datetime.combine(date.today(), time.max)
    window_end = datetime.combine(date.today() + timedelta(days=UPCOMING_WINDOW_DAYS), time.max)

    base = ErrorBook.query.filter(ErrorBook.user_id == g.user.id)

    due_today = base.filter(
        db.or_(ErrorBook.due_at.is_(None), ErrorBook.due_at <= today_end)).count()
    upcoming_7d = base.filter(
        ErrorBook.due_at > today_end, ErrorBook.due_at <= window_end).count()
    total_in_review = base.count()

    return _ok({
        'due_today': due_today,
        'upcoming_7d': upcoming_7d,
        'total_in_review': total_in_review,
    })
