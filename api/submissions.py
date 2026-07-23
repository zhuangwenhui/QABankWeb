"""采点判题 API(蓝图 api_submissions)。

学生上传手写作答照片 → 采点引擎(grading.get_grader)按题目 rubric 评分 → 存档。
所有数据限定当前登录用户(g.user)。评分同步进行(gunicorn timeout 内)。
"""
import os
import uuid
from datetime import datetime

from flask import Blueprint, current_app, g, jsonify, request

from auth import login_required
from grading import GradingError, get_grader
from models import AnswerSubmission, Question, db

bp = Blueprint('api_submissions', __name__, url_prefix='/api')

MAX_IMAGES = 4  # 单次提交作答图上限


def _ok(data=None, message=None, status=200):
    payload = {'success': True}
    if data is not None:
        payload['data'] = data
    if message:
        payload['message'] = message
    return jsonify(payload), status


def _err(error, code='INVALID_INPUT', status=400):
    return jsonify(success=False, error=error, code=code), status


def _upload_folder():
    return current_app.config['UPLOAD_FOLDER']


def _image_exts():
    # 作答图仅收位图(不含 pdf:多模态阅卷需 image 块)
    return set(current_app.config.get('ALLOWED_UPLOAD_EXTENSIONS', set())) - {'pdf'}


def _save_images(files):
    """校验并落盘作答图,返回文件名列表;非法即抛 ValueError(交调用方转 _err)。"""
    if not files:
        raise ValueError('请上传至少一张作答照片')
    if len(files) > MAX_IMAGES:
        raise ValueError(f'最多上传 {MAX_IMAGES} 张作答照片')
    allowed = _image_exts()
    folder = _upload_folder()
    os.makedirs(folder, exist_ok=True)
    names = []
    for f in files:
        fname = (f.filename or '').strip()
        if not fname:
            raise ValueError('存在空文件名的上传项')
        ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
        if ext not in allowed:
            raise ValueError('不支持的图片类型,仅允许:' + '、'.join(sorted(allowed)))
        new_name = 'answer_' + uuid.uuid4().hex + '.' + ext
        f.save(os.path.join(folder, new_name))
        names.append(new_name)
    return names


def _remove_files(names):
    folder = os.path.realpath(_upload_folder())
    for n in names or []:
        try:
            path = os.path.realpath(os.path.join(folder, n))
            # 防目录穿越:仅删 upload 目录内文件
            if path.startswith(folder + os.sep) and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


def _reference_solution(q):
    parts = []
    if (q.solution_latex or '').strip():
        parts.append('【中文速览】\n' + q.solution_latex.strip())
    if (q.solution_ja or '').strip():
        parts.append('【日本語詳解】\n' + q.solution_ja.strip())
    return '\n\n'.join(parts)


@bp.route('/questions/<int:qid>/submissions', methods=['POST'])
@login_required
def create_submission(qid):
    """上传作答照片并采点评分(同步)。multipart 字段 images(1–4 张)。"""
    question = db.session.get(Question, qid)
    if question is None:
        return _err('题目不存在', code='NOT_FOUND', status=404)

    files = [f for f in request.files.getlist('images') if f and (f.filename or '').strip()]
    try:
        names = _save_images(files)
    except ValueError as exc:
        return _err(str(exc))

    sub = AnswerSubmission(user_id=g.user.id, question_id=qid, status='pending')
    sub.image_paths_list = names
    db.session.add(sub)
    db.session.commit()  # 先持久化提交与图(即便评分失败也留档)

    grader = get_grader(current_app.config)
    folder = _upload_folder()
    try:
        result = grader.grade(
            question_text=question.question_latex or '',
            reference_solution=_reference_solution(question),
            rubric=question.solution_structured_dict,
            image_paths=[os.path.join(folder, n) for n in names])
        sub.status = 'graded'
        sub.total_score = result.get('total_score')
        sub.max_score = result.get('max_score')
        sub.rubric_breakdown_list = result.get('breakdown') or []
        sub.transcription = result.get('transcription') or ''
        sub.feedback = result.get('feedback') or ''
        sub.grader = grader.name
        sub.model = result.get('model')
        sub.graded_at = datetime.now()
    except GradingError as exc:
        sub.status = 'failed'
        sub.grader = grader.name
        sub.error = str(exc)[:1000]
    db.session.commit()
    return _ok({'submission': sub.to_dict()},
               message='评分完成' if sub.status == 'graded' else '评分失败',
               status=201)


@bp.route('/questions/<int:qid>/submissions', methods=['GET'])
@login_required
def list_submissions(qid):
    """当前用户对该题的作答历史(倒序)。"""
    subs = (AnswerSubmission.query
            .filter_by(user_id=g.user.id, question_id=qid)
            .order_by(AnswerSubmission.created_at.desc(), AnswerSubmission.id.desc())
            .all())
    return _ok({'submissions': [s.to_dict() for s in subs]})


def _owned_or_404(sid):
    sub = db.session.get(AnswerSubmission, sid)
    if sub is None or sub.user_id != g.user.id:
        return None
    return sub


@bp.route('/submissions/<int:sid>', methods=['GET'])
@login_required
def get_submission(sid):
    sub = _owned_or_404(sid)
    if sub is None:
        return _err('提交不存在', code='NOT_FOUND', status=404)
    return _ok({'submission': sub.to_dict()})


@bp.route('/submissions/<int:sid>', methods=['DELETE'])
@login_required
def delete_submission(sid):
    sub = _owned_or_404(sid)
    if sub is None:
        return _err('提交不存在', code='NOT_FOUND', status=404)
    _remove_files(sub.image_paths_list)
    db.session.delete(sub)
    db.session.commit()
    return _ok(message='已删除')
