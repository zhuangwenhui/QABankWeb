"""管理总览接口。

蓝图 api_overview,url_prefix='/api/overview'。仅管理员可访问。
所有统计均使用数据库聚合(func.count + group_by),不在 Python 侧遍历全表。
"""
import re
import secrets
import string
from datetime import date, datetime, time, timedelta

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func

import config
from auth import admin_required
from logging_setup import audit
from models import ErrorBook, Feedback, Question, User, ViewLog, db

bp = Blueprint('api_overview', __name__, url_prefix='/api/overview')

TREND_DAYS = 14       # 查看趋势统计天数
TOP_VIEWED_LIMIT = 10  # 最常查看题目条数
RECENT_LIMIT = 5       # 最近新增题目条数


def _count_by_group(rows, preset_keys=None):
    """把 (key, count) 行转成 dict;preset_keys 用于补齐计数为 0 的分组。"""
    result = {k: 0 for k in (preset_keys or [])}
    for key, n in rows:
        if key is None:
            continue
        result[key] = n
    return result


def _views_last_14_days():
    """近 14 天(含今天)每日查看次数,缺失日期补 0。"""
    today = date.today()
    start_day = today - timedelta(days=TREND_DAYS - 1)
    start_dt = datetime.combine(start_day, time.min)
    rows = (db.session.query(func.date(ViewLog.viewed_at), func.count(ViewLog.id))
            .filter(ViewLog.viewed_at >= start_dt)
            .group_by(func.date(ViewLog.viewed_at))
            .all())
    # SQLite 下 func.date 返回 'YYYY-MM-DD' 字符串,其他方言可能返回 date 对象,统一转字符串
    day_map = {str(d): n for d, n in rows if d is not None}
    trend = []
    for i in range(TREND_DAYS):
        day = start_day + timedelta(days=i)
        trend.append({
            'date': day.strftime('%m-%d'),
            'count': day_map.get(day.isoformat(), 0),
        })
    return trend


def _top_viewed():
    """最常查看题目 Top10:[{id, subject, source, count}]。"""
    cnt = func.count(ViewLog.id).label('cnt')
    rows = (db.session.query(Question.id, Question.subject, Question.source, cnt)
            .join(ViewLog, ViewLog.question_id == Question.id)
            .group_by(Question.id)
            .order_by(cnt.desc(), Question.id.asc())
            .limit(TOP_VIEWED_LIMIT)
            .all())
    return [{'id': qid, 'subject': subject, 'source': source or '', 'count': n}
            for qid, subject, source, n in rows]


@bp.route('/stats', methods=['GET'])
@admin_required
def stats():
    """总览统计数据(仪表盘一次性拉取)。"""
    try:
        question_total = db.session.query(func.count(Question.id)).scalar() or 0
        user_total = db.session.query(func.count(User.id)).scalar() or 0
        error_book_total = db.session.query(func.count(ErrorBook.id)).scalar() or 0
        feedback_pending = (db.session.query(func.count(Feedback.id))
                            .filter(Feedback.status == '待处理').scalar() or 0)

        by_subject = _count_by_group(
            db.session.query(Question.subject, func.count(Question.id))
            .group_by(Question.subject).all(),
            preset_keys=config.SUBJECTS)

        by_difficulty = _count_by_group(
            db.session.query(Question.difficulty, func.count(Question.id))
            .group_by(Question.difficulty).all(),
            preset_keys=config.DIFFICULTIES)

        # 全体用户错题按科目分布(联表聚合)
        error_by_subject = _count_by_group(
            db.session.query(Question.subject, func.count(ErrorBook.id))
            .join(Question, ErrorBook.question_id == Question.id)
            .group_by(Question.subject).all(),
            preset_keys=config.SUBJECTS)

        recent_questions = (Question.query
                            .order_by(Question.created_at.desc(), Question.id.desc())
                            .limit(RECENT_LIMIT).all())

        return jsonify(success=True, data={
            'question_total': question_total,
            'user_total': user_total,
            'error_book_total': error_book_total,
            'feedback_pending': feedback_pending,
            'by_subject': by_subject,
            'by_difficulty': by_difficulty,
            'views_last_14_days': _views_last_14_days(),
            'top_viewed': _top_viewed(),
            'error_by_subject': error_by_subject,
            'recent_questions': [q.to_dict() for q in recent_questions],
        })
    except Exception:
        current_app.logger.exception('总览统计查询失败')
        return jsonify(success=False, error='统计数据加载失败,请稍后重试',
                       code='SERVER_ERROR'), 500


# ---------------------------------------------------------------- 用户管理

_USERNAME_RE = re.compile(r'^[A-Za-z0-9_-]{3,32}$')
_PW_CHARS = string.ascii_letters + string.digits


def _gen_initial_password(length=None):
    length = length or config.MIN_PASSWORD_LEN
    return ''.join(secrets.choice(_PW_CHARS) for _ in range(length))


def _user_row(u):
    return {'id': u.id, 'username': u.username, 'role': u.role,
            'is_active': u.is_active, 'must_change_password': u.must_change_password,
            'created_at': u.created_at.strftime('%Y-%m-%d %H:%M:%S') if u.created_at else None}


@bp.route('/users', methods=['GET'])
@admin_required
def list_users():
    users = User.query.order_by(User.id.asc()).all()
    return jsonify(success=True, data={'users': [_user_row(u) for u in users]})


@bp.route('/users', methods=['POST'])
@admin_required
def create_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username') or '').strip()
    role = data.get('role')
    if not _USERNAME_RE.match(username):
        return jsonify(success=False, error='用户名需为 3-32 位字母/数字/下划线/连字符',
                       code='INVALID_INPUT'), 400
    if role not in ('student', 'admin'):
        return jsonify(success=False, error='角色必须是 student 或 admin',
                       code='INVALID_INPUT'), 400
    if User.query.filter_by(username=username).first():
        return jsonify(success=False, error='用户名已存在', code='INVALID_INPUT'), 400
    password = _gen_initial_password()
    try:
        user = User(username=username, role=role, must_change_password=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('创建用户失败')
        return jsonify(success=False, error='创建用户失败', code='SERVER_ERROR'), 500
    audit('user_created', target=username, detail=f'role={role}')
    return jsonify(success=True, message='创建成功,初始密码仅本次展示',
                   data={'user': _user_row(user), 'initial_password': password})


@bp.route('/users/<int:uid>/reset_password', methods=['POST'])
@admin_required
def reset_password(uid):
    user = db.session.get(User, uid)
    if user is None:
        return jsonify(success=False, error='用户不存在', code='NOT_FOUND'), 404
    password = _gen_initial_password()
    try:
        user.set_password(password)
        user.must_change_password = True
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('重置密码失败')
        return jsonify(success=False, error='重置密码失败', code='SERVER_ERROR'), 500
    audit('password_reset', target=user.username)
    return jsonify(success=True, message='已重置,初始密码仅本次展示',
                   data={'initial_password': password})


@bp.route('/users/<int:uid>/toggle_active', methods=['POST'])
@admin_required
def toggle_active(uid):
    user = db.session.get(User, uid)
    if user is None:
        return jsonify(success=False, error='用户不存在', code='NOT_FOUND'), 404
    if user.id == g.user.id:
        return jsonify(success=False, error='不能停用自己', code='INVALID_INPUT'), 400
    try:
        user.is_active = not user.is_active
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('切换用户状态失败')
        return jsonify(success=False, error='操作失败', code='SERVER_ERROR'), 500
    audit('user_disabled' if not user.is_active else 'user_enabled', target=user.username)
    return jsonify(success=True, message=('已停用' if not user.is_active else '已启用'),
                   data={'user': _user_row(user)})
