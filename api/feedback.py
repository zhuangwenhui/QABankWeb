"""意见反馈接口。

蓝图 api_feedback,url_prefix='/api/feedback'。
权限:学生只能查看/删除自己的反馈;管理员可查看全部、标记状态并回复、删除任意反馈。
统一响应格式:成功 {success, data?, message?};失败 {success:false, error, code}。
"""
from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func

import config
from auth import admin_required, login_required
from models import Feedback, db

bp = Blueprint('api_feedback', __name__, url_prefix='/api/feedback')

MAX_TITLE_LEN = 128
MAX_CONTENT_LEN = 5000
MAX_REPLY_LEN = 5000


def _err(message, code='INVALID_INPUT', status=400):
    """统一错误响应。"""
    return jsonify(success=False, error=message, code=code), status


def _visible_query():
    """当前用户可见的反馈查询:学生仅自己的,管理员全部。"""
    q = Feedback.query
    if not g.user.is_admin:
        q = q.filter(Feedback.user_id == g.user.id)
    return q


def _visible_counts():
    """按可见范围统计各状态数量(数据库聚合,避免全表遍历)。"""
    q = db.session.query(Feedback.status, func.count(Feedback.id))
    if not g.user.is_admin:
        q = q.filter(Feedback.user_id == g.user.id)
    rows = q.group_by(Feedback.status).all()
    counts = {s: 0 for s in config.FEEDBACK_STATUSES}
    for status, n in rows:
        if status in counts:
            counts[status] = n
    counts['全部'] = sum(n for _, n in rows)
    return counts


@bp.route('', methods=['GET'])
@login_required
def list_feedback():
    """反馈列表。query: status(全部/待处理/已处理,'全部'或空=不过滤)。"""
    status = (request.args.get('status') or '').strip()
    query = _visible_query()
    if status and status != '全部':
        if status not in config.FEEDBACK_STATUSES:
            return _err('无效的状态筛选,应为:全部 / ' + ' / '.join(config.FEEDBACK_STATUSES))
        query = query.filter(Feedback.status == status)
    feedbacks = query.order_by(Feedback.created_at.desc(), Feedback.id.desc()).all()
    return jsonify(success=True, data={
        'feedbacks': [f.to_dict() for f in feedbacks],
        'counts': _visible_counts(),
    })


@bp.route('', methods=['POST'])
@login_required
def create_feedback():
    """提交反馈。JSON: {title(必填), content}。"""
    data = request.get_json(silent=True) or {}
    title = str(data.get('title') or '').strip()
    content = str(data.get('content') or '').strip()

    if not title:
        return _err('标题不能为空')
    if len(title) > MAX_TITLE_LEN:
        return _err('标题过长(最多 %d 字)' % MAX_TITLE_LEN)
    if len(content) > MAX_CONTENT_LEN:
        return _err('内容过长(最多 %d 字)' % MAX_CONTENT_LEN)

    fb = Feedback(user_id=g.user.id, title=title, content=content)
    try:
        db.session.add(fb)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('创建反馈失败')
        return _err('提交失败,请稍后重试', code='SERVER_ERROR', status=500)
    return jsonify(success=True, data={'feedback': fb.to_dict()}, message='反馈提交成功')


@bp.route('/<int:fid>/status', methods=['POST'])
@admin_required
def update_status(fid):
    """管理员标记状态并可填写回复。JSON: {status, reply?}。"""
    fb = db.session.get(Feedback, fid)
    if fb is None:
        return _err('反馈不存在', code='NOT_FOUND', status=404)

    data = request.get_json(silent=True) or {}
    status = str(data.get('status') or '').strip()
    if status not in config.FEEDBACK_STATUSES:
        return _err('无效的状态,应为:' + ' / '.join(config.FEEDBACK_STATUSES))

    fb.status = status
    if 'reply' in data:
        reply = str(data.get('reply') or '').strip()
        if len(reply) > MAX_REPLY_LEN:
            return _err('回复过长(最多 %d 字)' % MAX_REPLY_LEN)
        fb.reply = reply

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('更新反馈状态失败: fid=%s', fid)
        return _err('更新失败,请稍后重试', code='SERVER_ERROR', status=500)
    return jsonify(success=True, data={'feedback': fb.to_dict()}, message='已更新')


@bp.route('/<int:fid>', methods=['DELETE'])
@login_required
def delete_feedback(fid):
    """删除反馈:本人或管理员。"""
    fb = db.session.get(Feedback, fid)
    if fb is None:
        return _err('反馈不存在', code='NOT_FOUND', status=404)
    if not g.user.is_admin and fb.user_id != g.user.id:
        return _err('无权删除该反馈', code='FORBIDDEN', status=403)

    try:
        db.session.delete(fb)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('删除反馈失败: fid=%s', fid)
        return _err('删除失败,请稍后重试', code='SERVER_ERROR', status=500)
    return jsonify(success=True, message='已删除')
