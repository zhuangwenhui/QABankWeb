"""错题本 API(蓝图 api_error_book)。

提供错题列表筛选分页、加入/批量加入、移出、备注编辑、统计,
以及基于 LaTeX 模板的 PDF 试卷生成(编译逻辑见 pdf_gen.py)。
所有数据均限定当前登录用户(g.user)。
"""
import os
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

import config
from auth import login_required
from models import ErrorBook, GeneratedFile, Question, db
from pdf_gen import generate_pdf

bp = Blueprint('api_error_book', __name__, url_prefix='/api/error_book')

MAX_NOTES_LEN = 5000     # 备注长度上限
MAX_TEXT_LEN = 200       # 标题/副标题长度上限
MAX_NOTICE_LEN = 2000    # 注意事项长度上限
MAX_BATCH_SIZE = 2000    # 批量操作 ID 数上限

DEFAULT_NOTICE = ('1. 请独立完成全部题目,不要提前翻看解答;'
                  '2. 解题过程务必书写规范、条理清晰;'
                  '3. 完成后对照解答自查,并及时更新错题备注。')


# ---------------------------------------------------------------- 工具函数

def _ok(data=None, message=None, status=200):
    """统一成功响应。"""
    payload = {'success': True}
    if data is not None:
        payload['data'] = data
    if message:
        payload['message'] = message
    return jsonify(payload), status


def _err(error, code='INVALID_INPUT', status=400):
    """统一失败响应。"""
    return jsonify(success=False, error=error, code=code), status


class _FieldError(ValueError):
    """输入字段校验失败。"""


def _str_field(data, key, max_len):
    """从请求 JSON 中取字符串字段:去空白、限长,类型不合法时抛 _FieldError。"""
    value = data.get(key)
    if value is None:
        return ''
    if not isinstance(value, (str, int, float)):
        raise _FieldError(f'字段 {key} 格式不正确')
    s = str(value).strip()
    if len(s) > max_len:
        raise _FieldError(f'字段 {key} 长度超出上限({max_len} 字符)')
    return s


def _parse_int_list(value, max_size=MAX_BATCH_SIZE):
    """把请求中的 ID 列表转换为去重后的正整数列表(保持顺序);非法时返回 None。"""
    if not isinstance(value, list) or len(value) > max_size:
        return None
    result, seen = [], set()
    for item in value:
        # bool 是 int 的子类,需显式排除
        if isinstance(item, bool):
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


def _escape_like(term):
    """转义 LIKE 通配符,配合 like(..., escape='\\\\') 使用(与 api/questions.py 一致)。"""
    return (term.replace('\\', '\\\\')
                .replace('%', '\\%')
                .replace('_', '\\_'))


def _parse_question_id(data):
    """从请求 JSON 中解析单个 question_id,非法时返回 None。"""
    value = data.get('question_id')
    if isinstance(value, bool):
        return None
    try:
        qid = int(value)
    except (TypeError, ValueError):
        return None
    return qid if qid > 0 else None


def _split_scores(total_score, count):
    """把总分尽量均分到每道题(前面的题多 1 分补齐余数);无法均分时返回 None 列表。"""
    try:
        total = int(str(total_score).strip())
    except (TypeError, ValueError):
        return [None] * count
    if total <= 0 or count <= 0 or total < count:
        return [None] * count
    base, rem = divmod(total, count)
    return [base + 1 if i < rem else base for i in range(count)]


GENERATED_TTL_HOURS = 24


def _cleanup_generated():
    """删除超过 TTL 的产物记录与文件;孤儿文件(无记录且 mtime 过期)一并清理。"""
    folder = current_app.config['GENERATED_PDF_FOLDER']
    cutoff = datetime.now() - timedelta(hours=GENERATED_TTL_HOURS)
    try:
        expired = GeneratedFile.query.filter(GeneratedFile.created_at < cutoff).all()
        known = {r.filename for r in GeneratedFile.query.all()}
        for rec in expired:
            path = os.path.join(folder, rec.filename)
            if os.path.isfile(path):
                os.remove(path)
            db.session.delete(rec)
        db.session.commit()
        cutoff_ts = cutoff.timestamp()
        for name in os.listdir(folder):
            if name.startswith('.') or name in known:
                continue
            path = os.path.join(folder, name)
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff_ts:
                os.remove(path)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('清理生成物失败(不影响本次请求)')


# ---------------------------------------------------------------- 列表与统计

@bp.route('', methods=['GET'])
@login_required
def list_entries():
    """错题列表:按课程/章节/难度/来源/关键词筛选 + 分页。"""
    query = (ErrorBook.query
             .filter(ErrorBook.user_id == g.user.id)
             .join(Question, ErrorBook.question_id == Question.id)
             .options(selectinload(ErrorBook.question)))

    subject = request.args.get('subject', '').strip()
    chapter = request.args.get('chapter', '').strip()
    difficulty = request.args.get('difficulty', '').strip()
    source = request.args.get('source', '').strip()
    search = request.args.get('search', '').strip()

    if subject:
        query = query.filter(Question.subject == subject)
    if chapter:
        query = query.filter(Question.chapter == chapter)
    if difficulty:
        query = query.filter(Question.difficulty == difficulty)
    if source:
        pattern = f'%{_escape_like(source)}%'
        query = query.filter(Question.source.like(pattern, escape='\\'))
    if search:
        like = f'%{_escape_like(search)}%'
        query = query.filter(db.or_(
            Question.question_latex.like(like, escape='\\'),
            Question.solution_latex.like(like, escape='\\'),
            Question.source.like(like, escape='\\'),
            Question.chapter.like(like, escape='\\'),
        ))

    page = request.args.get('page', 1, type=int)
    if page < 1:
        page = 1
    per_page = request.args.get('per_page', 20, type=int)
    if per_page not in config.PER_PAGE_OPTIONS:
        per_page = 20

    query = query.order_by(ErrorBook.created_at.desc(), ErrorBook.id.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return _ok({
        'entries': [e.to_dict() for e in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': per_page,
        'pages': pagination.pages,
    })


@bp.route('/stats', methods=['GET'])
@login_required
def stats():
    """错题统计:总数 + 按科目分布(按固定课程顺序输出)。"""
    total = ErrorBook.query.filter_by(user_id=g.user.id).count()
    rows = (db.session.query(Question.subject, db.func.count(ErrorBook.id))
            .join(ErrorBook, ErrorBook.question_id == Question.id)
            .filter(ErrorBook.user_id == g.user.id)
            .group_by(Question.subject)
            .all())
    counts = {subject: cnt for subject, cnt in rows}
    by_subject = {s: counts[s] for s in config.SUBJECTS if s in counts}
    # 兜底:课程枚举之外的科目也一并返回
    for subject, cnt in counts.items():
        if subject not in by_subject:
            by_subject[subject] = cnt
    return _ok({'total': total, 'by_subject': by_subject})


# ---------------------------------------------------------------- 加入/移出

@bp.route('/add', methods=['POST'])
@login_required
def add_entry():
    """加入单题至错题本,可附带备注;已存在时幂等返回。"""
    data = request.get_json(silent=True) or {}
    qid = _parse_question_id(data)
    if qid is None:
        return _err('question_id 必须为正整数')

    try:
        notes = _str_field(data, 'notes', MAX_NOTES_LEN)
    except _FieldError as exc:
        return _err(str(exc))

    question = db.session.get(Question, qid)
    if question is None:
        return _err('题目不存在', 'NOT_FOUND', 404)

    existing = ErrorBook.query.filter_by(user_id=g.user.id, question_id=qid).first()
    if existing is not None:
        return _ok(message='已在错题本中')

    try:
        entry = ErrorBook(user_id=g.user.id, question_id=qid, notes=notes)
        db.session.add(entry)
        db.session.commit()
    except IntegrityError:
        # 并发下另一个请求已插入同一条:按幂等语义返回成功
        db.session.rollback()
        return _ok(message='已在错题本中')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('加入错题本失败 question_id=%s', qid)
        return _err('加入错题本失败,请稍后重试', 'SERVER_ERROR', 500)
    return _ok(message='已加入错题本')


@bp.route('/add_batch', methods=['POST'])
@login_required
def add_batch():
    """批量加入错题本:返回实际新增数与跳过数(已存在/不存在的题目跳过)。"""
    data = request.get_json(silent=True) or {}
    ids = _parse_int_list(data.get('question_ids'))
    if not ids:
        return _err('question_ids 必须是非空的正整数列表')

    valid_ids = {row[0] for row in
                 db.session.query(Question.id).filter(Question.id.in_(ids)).all()}
    existing_ids = {row[0] for row in
                    db.session.query(ErrorBook.question_id)
                    .filter(ErrorBook.user_id == g.user.id,
                            ErrorBook.question_id.in_(ids)).all()}

    added, skipped = 0, 0
    try:
        for qid in ids:
            if qid not in valid_ids or qid in existing_ids:
                skipped += 1
                continue
            try:
                # 每条用 SAVEPOINT 包裹:并发下唯一约束冲突只回退该条,不影响整批
                with db.session.begin_nested():
                    db.session.add(ErrorBook(user_id=g.user.id, question_id=qid, notes=''))
                added += 1
            except IntegrityError:
                skipped += 1
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('批量加入错题本失败')
        return _err('批量加入失败,请稍后重试', 'SERVER_ERROR', 500)
    return _ok({'added': added, 'skipped': skipped},
               message=f'已加入 {added} 题,跳过 {skipped} 题')


@bp.route('/remove', methods=['POST'])
@login_required
def remove_entries():
    """从错题本移出:支持 {question_id} 单个或 {question_ids} 批量两种形式。"""
    data = request.get_json(silent=True) or {}
    if 'question_ids' in data:
        ids = _parse_int_list(data.get('question_ids'))
        if not ids:
            return _err('question_ids 必须是非空的正整数列表')
    else:
        qid = _parse_question_id(data)
        if qid is None:
            return _err('缺少 question_id 或 question_ids 参数')
        ids = [qid]

    try:
        removed = (ErrorBook.query
                   .filter(ErrorBook.user_id == g.user.id,
                           ErrorBook.question_id.in_(ids))
                   .delete(synchronize_session=False))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('移出错题本失败')
        return _err('移出失败,请稍后重试', 'SERVER_ERROR', 500)
    return _ok({'removed': removed}, message=f'已移出 {removed} 题')


@bp.route('/check_batch', methods=['POST'])
@login_required
def check_batch():
    """批量查询题目是否已在错题本中,用于列表页回填书签状态。"""
    data = request.get_json(silent=True) or {}
    ids = _parse_int_list(data.get('question_ids'))
    if ids is None:
        return _err('question_ids 必须是正整数列表')
    if not ids:
        return _ok({'in_error_book': []})

    rows = (db.session.query(ErrorBook.question_id)
            .filter(ErrorBook.user_id == g.user.id,
                    ErrorBook.question_id.in_(ids))
            .all())
    return _ok({'in_error_book': [row[0] for row in rows]})


# ---------------------------------------------------------------- 备注

@bp.route('/update_notes', methods=['POST'])
@login_required
def update_notes():
    """更新某条错题的备注(内联编辑保存)。"""
    data = request.get_json(silent=True) or {}
    qid = _parse_question_id(data)
    if qid is None:
        return _err('question_id 必须为正整数')

    notes = data.get('notes')
    if notes is None:
        notes = ''
    if not isinstance(notes, str):
        return _err('notes 必须是字符串')
    notes = notes.strip()
    if len(notes) > MAX_NOTES_LEN:
        return _err(f'备注长度超出上限({MAX_NOTES_LEN} 字符)')

    entry = ErrorBook.query.filter_by(user_id=g.user.id, question_id=qid).first()
    if entry is None:
        return _err('该题目不在错题本中', 'NOT_FOUND', 404)

    try:
        entry.notes = notes
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('保存备注失败 question_id=%s', qid)
        return _err('保存备注失败,请稍后重试', 'SERVER_ERROR', 500)
    return _ok(message='备注已保存')


# ---------------------------------------------------------------- PDF 生成

@bp.route('/generate_pdf', methods=['POST'])
@login_required
def generate_pdf_route():
    """按配置生成 PDF 试卷;服务器无 LaTeX 引擎时降级为生成 .tex 源文件。"""
    _cleanup_generated()
    data = request.get_json(silent=True) or {}

    template = data.get('template')
    if not isinstance(template, str) or template not in config.PDF_TEMPLATES:
        return _err('无效的试卷模板', 'INVALID_INPUT')

    try:
        title = _str_field(data, 'title', MAX_TEXT_LEN) or '错题整理试卷'
        subtitle = _str_field(data, 'subtitle', MAX_TEXT_LEN)
        exam_date = _str_field(data, 'exam_date', 50) or '——'
        subject = _str_field(data, 'subject', 50) or '综合'
        duration = _str_field(data, 'duration', 20) or '——'
        total_score = _str_field(data, 'total_score', 20)
        notice = _str_field(data, 'notice', MAX_NOTICE_LEN) or DEFAULT_NOTICE
    except _FieldError as exc:
        return _err(str(exc), 'INVALID_INPUT')

    include_solutions = bool(data.get('include_solutions'))

    # 范围:显式传 question_ids 则按传入顺序取,否则取当前用户全部错题
    raw_ids = data.get('question_ids')
    if raw_ids is not None:
        ids = _parse_int_list(raw_ids)
        if not ids:
            return _err('question_ids 必须是非空的正整数列表', 'INVALID_INPUT')
        entries = (ErrorBook.query
                   .filter(ErrorBook.user_id == g.user.id,
                           ErrorBook.question_id.in_(ids))
                   .options(selectinload(ErrorBook.question))
                   .all())
        order = {qid: i for i, qid in enumerate(ids)}
        entries.sort(key=lambda e: order.get(e.question_id, len(order)))
    else:
        entries = (ErrorBook.query
                   .filter(ErrorBook.user_id == g.user.id)
                   .join(Question, ErrorBook.question_id == Question.id)
                   .options(selectinload(ErrorBook.question))
                   .order_by(Question.subject.asc(), Question.id.asc())
                   .all())

    entries = [e for e in entries if e.question is not None]
    if not entries:
        return _err('没有可用于生成试卷的错题', 'EMPTY_SET')

    # 每题分值:仅正式试卷模板标注(总分可均分时)
    if template == 'custom_exam_template':
        scores = _split_scores(total_score, len(entries))
    else:
        scores = [None] * len(entries)

    questions = []
    for entry, score in zip(entries, scores):
        q = entry.question
        questions.append({
            'question_latex': q.question_latex or '',
            'solution_latex': q.solution_latex or '',
            'subject': q.subject,
            'source': q.source or '',
            'difficulty': q.difficulty,
            'notes': entry.notes or '',
            'score': score,
        })

    context = {
        'TITLE': title,
        'SUBTITLE': subtitle,
        'EXAM_DATE': exam_date,
        'SUBJECT': subject,
        'DURATION': duration,
        'TOTAL_SCORE': total_score or '——',
        'NOTICE': notice,
        'include_solutions': include_solutions,
    }

    basename = uuid.uuid4().hex[:12]
    try:
        result = generate_pdf(template, context, questions, basename,
                              out_dir=current_app.config['GENERATED_PDF_FOLDER'])
    except Exception:
        current_app.logger.exception('PDF 生成异常')
        return _err('PDF 生成过程中发生服务器错误', 'SERVER_ERROR', 500)

    if result.get('busy'):
        return _err('服务器繁忙,已有试卷正在生成,请稍后重试', 'BUSY', 429)

    def _register_outputs():
        """把本次真实产出的文件登记到当前用户名下。"""
        folder = current_app.config['GENERATED_PDF_FOLDER']
        for ext in ('.tex', '.pdf'):
            if os.path.isfile(os.path.join(folder, basename + ext)):
                db.session.add(GeneratedFile(filename=basename + ext, user_id=g.user.id))
        db.session.commit()

    if result.get('engine_missing'):
        try:
            _register_outputs()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('登记生成物失败')
            return _err('生成记录保存失败,请重试', 'SERVER_ERROR', 500)
        return _ok(
            {'tex_url': f'/generated/{basename}.tex',
             'filename': f'{basename}.tex',
             'engine_missing': True},
            message='服务器未安装 LaTeX 引擎(xelatex/pdflatex),已生成 .tex 源文件,请下载后在本地编译')

    if not result.get('ok'):
        error_text = result.get('error') or '未知错误'
        if len(error_text) > 4000:
            error_text = '……' + error_text[-4000:]
        current_app.logger.warning('PDF 编译失败: %s', error_text)
        return _err('PDF 编译失败:' + error_text, 'PDF_COMPILE_FAILED', 500)

    try:
        _register_outputs()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('登记生成物失败')
        return _err('生成记录保存失败,请重试', 'SERVER_ERROR', 500)
    return _ok({'pdf_url': f'/generated/{basename}.pdf', 'filename': f'{basename}.pdf'},
               message='试卷生成成功')
