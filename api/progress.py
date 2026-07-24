"""学习进度 API(蓝图 api_progress)。

掌握状态轴:每个用户对每道题的做题进度(done / mastered),无行=未做。
所有数据均限定当前登录用户(g.user)。
"""
from datetime import date, datetime, time, timedelta

from flask import Blueprint, current_app, g, request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

import config
from auth import login_required
from models import Question, QuestionProgress, db
from api._helpers import ok as _ok, err as _err

bp = Blueprint('api_progress', __name__, url_prefix='/api/progress')

VALID_STATUSES = ('done', 'mastered')  # 可持久化的状态;'none' 表示删除记录
MAX_BATCH_SIZE = 2000
MAX_CALENDAR_DAYS = 366


# ---------------------------------------------------------------- 工具函数

# 响应信封 _ok/_err 已抽到 api/_helpers.py(见顶部别名导入)。


def _parse_question_id(data):
    value = data.get('question_id')
    if isinstance(value, bool):
        return None
    try:
        qid = int(value)
    except (TypeError, ValueError):
        return None
    return qid if qid > 0 else None


def _parse_int_list(value, max_size=MAX_BATCH_SIZE):
    """把请求中的 ID 列表转换为去重后的正整数列表(保持顺序);非法时返回 None。"""
    if not isinstance(value, list) or len(value) > max_size:
        return None
    result, seen = [], set()
    for item in value:
        if isinstance(item, bool):  # bool 是 int 子类,需显式排除
            return None
        try:
            n = int(item)
        except (TypeError, ValueError):
            return None
        if n <= 0:
            return None
        if n not in seen:
            seen.add(n)
            result.append(n)
    return result


# ---------------------------------------------------------------- 设置状态

@bp.route('/set', methods=['POST'])
@login_required
def set_progress():
    """设置某题的掌握状态:done/mastered 则 upsert,none 则删行(回到未做)。"""
    data = request.get_json(silent=True) or {}
    qid = _parse_question_id(data)
    if qid is None:
        return _err('question_id 必须为正整数')

    status = data.get('status')
    if status not in VALID_STATUSES and status != 'none':
        return _err('status 必须是 done/mastered/none 之一')

    if db.session.get(Question, qid) is None:
        return _err('题目不存在', 'NOT_FOUND', 404)

    row = QuestionProgress.query.filter_by(user_id=g.user.id, question_id=qid).first()

    try:
        if status == 'none':
            if row is not None:
                db.session.delete(row)
                db.session.commit()
            return _ok({'question_id': qid, 'status': None}, message='已标记为未做')

        if row is None:
            try:
                with db.session.begin_nested():
                    db.session.add(QuestionProgress(
                        user_id=g.user.id, question_id=qid, status=status))
            except IntegrityError:
                # 并发下另一请求已插入同一条:改为更新已存在行
                row = QuestionProgress.query.filter_by(
                    user_id=g.user.id, question_id=qid).first()
                if row is not None:
                    row.status = status
                    row.updated_at = datetime.now()
        else:
            row.status = status
            row.updated_at = datetime.now()
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('设置学习进度失败 question_id=%s', qid)
        return _err('保存进度失败,请稍后重试', 'SERVER_ERROR', 500)

    return _ok({'question_id': qid, 'status': status}, message='进度已更新')


# ---------------------------------------------------------------- 批量查询

@bp.route('/check_batch', methods=['POST'])
@login_required
def check_batch():
    """批量查询题目的掌握状态,用于列表页回填。返回 {statuses: {qid: status}}。"""
    data = request.get_json(silent=True) or {}
    ids = _parse_int_list(data.get('question_ids'))
    if ids is None:
        return _err('question_ids 必须是正整数列表')
    if not ids:
        return _ok({'statuses': {}})

    rows = (db.session.query(QuestionProgress.question_id, QuestionProgress.status)
            .filter(QuestionProgress.user_id == g.user.id,
                    QuestionProgress.question_id.in_(ids))
            .all())
    # JSON 键须为字符串
    return _ok({'statuses': {str(qid): status for qid, status in rows}})


# ---------------------------------------------------------------- 进度汇总

def _summary_by(group_col, preset_keys):
    """按 group_col(难度/学科)汇总:total=题库该组总题数,done=已做(含掌握),mastered=已掌握。"""
    result = {k: {'total': 0, 'done': 0, 'mastered': 0} for k in preset_keys}

    def _bucket(key):
        return result.setdefault(key, {'total': 0, 'done': 0, 'mastered': 0})

    # 分母:题库中该组的全部题目
    for key, n in (db.session.query(group_col, func.count(Question.id))
                   .group_by(group_col).all()):
        if key is None:
            continue
        _bucket(key)['total'] = n

    # 分子:当前用户的进度(按状态计),done 记全部尝试,mastered 仅记掌握
    rows = (db.session.query(group_col, QuestionProgress.status,
                             func.count(QuestionProgress.id))
            .join(Question, QuestionProgress.question_id == Question.id)
            .filter(QuestionProgress.user_id == g.user.id)
            .group_by(group_col, QuestionProgress.status).all())
    for key, status, n in rows:
        if key is None:
            continue
        bucket = _bucket(key)
        bucket['done'] += n  # 有进度行即已做过
        if status == 'mastered':
            bucket['mastered'] += n
    return result


@bp.route('/summary', methods=['GET'])
@login_required
def summary():
    """进度面板:按难度/学科给出 {total, done, mastered}。"""
    by_difficulty = _summary_by(Question.difficulty, config.DIFFICULTIES)
    by_subject = _summary_by(Question.subject, config.SUBJECTS)

    overall_total = db.session.query(func.count(Question.id)).scalar() or 0
    done = (db.session.query(func.count(QuestionProgress.id))
            .filter(QuestionProgress.user_id == g.user.id).scalar() or 0)
    mastered = (db.session.query(func.count(QuestionProgress.id))
                .filter(QuestionProgress.user_id == g.user.id,
                        QuestionProgress.status == 'mastered').scalar() or 0)

    return _ok({
        'overall': {'total': overall_total, 'done': done, 'mastered': mastered},
        'by_difficulty': by_difficulty,
        'by_subject': by_subject,
    })


# ---------------------------------------------------------------- 做题日历

@bp.route('/calendar', methods=['GET'])
@login_required
def calendar():
    """当前用户每日活跃题数(按 updated_at 聚合),缺日补 0,返回 [{date, count}]。"""
    days = request.args.get('days', 365, type=int)
    if days < 1:
        days = 1
    if days > MAX_CALENDAR_DAYS:
        days = MAX_CALENDAR_DAYS

    today = date.today()
    start_day = today - timedelta(days=days - 1)
    start_dt = datetime.combine(start_day, time.min)

    rows = (db.session.query(func.date(QuestionProgress.updated_at),
                             func.count(QuestionProgress.id))
            .filter(QuestionProgress.user_id == g.user.id,
                    QuestionProgress.updated_at >= start_dt)
            .group_by(func.date(QuestionProgress.updated_at))
            .all())
    # SQLite 下 func.date 返回 'YYYY-MM-DD' 字符串;统一转字符串键
    day_map = {str(d): n for d, n in rows if d is not None}

    calendar_data = []
    for i in range(days):
        day = start_day + timedelta(days=i)
        calendar_data.append({
            'date': day.isoformat(),
            'count': day_map.get(day.isoformat(), 0),
        })
    return _ok({'calendar': calendar_data})
