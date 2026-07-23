"""题目管理 API(SPEC §2.1)。

蓝图名 api_questions,url_prefix='/api'。全部接口需登录。
统一响应格式:
    成功: {"success": true, "data": {...}, "message": "可选提示"}
    失败: {"success": false, "error": "人类可读错误", "code": "机器可读错误码"} + 恰当的 HTTP 状态码
"""
import json
import os
import re
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func, or_

import config
from auth import login_required
from logging_setup import audit
from models import Question, QuestionProgress, QuestionTag, Tag, ViewLog, db

bp = Blueprint('api_questions', __name__, url_prefix='/api')

# 字段长度上限(与 models.py 列宽保持一致)
_MAX_CHAPTER_LEN = 128
_MAX_SOURCE_LEN = 128

# 院試题定位筛选(2026-07-19):院校/専攻/年份从 source 标签解析,学科按 subject 归三大类。
# exam-harvest 标签格式恒为 "{院校} {専攻} {年份} {科目} 第n問"(实测 166/166 命中),
# 故无需改表、无需回填数据——纯读侧解析即可支撑 时间/院校→専攻/学科 三级筛选。
_EXAM_LABEL_RE = re.compile(r'^(\S+)\s+(\S+)\s+(\d{4})\s+\S+\s+第\d+問$')
# 学科粗分组(学科范围):数学 / 复变 / 算法。subject 细类归并到这三档。
_SUBJECT_GROUPS = [
    ('数学', ['线性代数', '微积分', '概率统计', '微分方程', '向量解析', '备注']),
    ('复变', ['复变函数']),
    ('算法', ['算法']),
]
_SUBJECT_TO_GROUP = {s: g for g, subs in _SUBJECT_GROUPS for s in subs}


def _parse_exam_label(source):
    """从 source 标签解析 (院校, 専攻, 年份);非院試格式返回 None。"""
    if not source:
        return None
    m = _EXAM_LABEL_RE.match(source.strip())
    return (m.group(1), m.group(2), m.group(3)) if m else None


# ---------------------------------------------------------------- 响应辅助

def _ok(data=None, message=None, status=200):
    payload = {'success': True}
    if data is not None:
        payload['data'] = data
    if message:
        payload['message'] = message
    return jsonify(payload), status


def _fail(error, code='INVALID_INPUT', status=400):
    return jsonify(success=False, error=error, code=code), status


# ---------------------------------------------------------------- 校验辅助

def _escape_like(term):
    """转义 LIKE 通配符,配合 like(..., escape='\\\\') 使用。"""
    return (term.replace('\\', '\\\\')
                .replace('%', '\\%')
                .replace('_', '\\_'))


def _parse_date(raw, field):
    """解析 YYYY-MM-DD 日期,失败抛 ValueError。"""
    try:
        return datetime.strptime(raw, '%Y-%m-%d')
    except (TypeError, ValueError):
        raise ValueError(f'{field} 日期格式应为 YYYY-MM-DD')


def _parse_id_list(value, field='ids'):
    """校验并规整 id 数组:非空、元素为整数、去重保序。"""
    if not isinstance(value, list) or not value:
        raise ValueError(f'{field} 必须为非空数组')
    ids = []
    for item in value:
        if isinstance(item, bool):
            raise ValueError(f'{field} 中的元素必须为整数')
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            raise ValueError(f'{field} 中的元素必须为整数')
    return list(dict.fromkeys(ids))


def _clean_tags(value):
    """校验标签数组:元素转字符串、去空白、去重保序。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError('标签必须为数组')
    cleaned, seen = [], set()
    for tag in value:
        tag = str(tag).strip()
        if tag and tag not in seen:
            seen.add(tag)
            cleaned.append(tag)
    return cleaned


def _extract_question_fields(data, partial=False):
    """从请求 JSON 中提取并校验题目字段。

    partial=False(新建)时 subject 必填、difficulty 给默认值;
    partial=True(更新)时仅处理出现的字段。
    校验失败抛 ValueError(中文提示)。
    """
    if not isinstance(data, dict):
        raise ValueError('请求体必须为 JSON 对象')
    fields = {}

    if 'subject' in data or not partial:
        subject = str(data.get('subject') or '').strip()
        if not subject:
            raise ValueError('课程为必填项')
        if subject not in config.SUBJECTS:
            raise ValueError('课程不在允许的分类内')
        fields['subject'] = subject

    if 'difficulty' in data or not partial:
        difficulty = str(data.get('difficulty') or '').strip() or '中等'
        if difficulty not in config.DIFFICULTIES:
            raise ValueError('难度取值不合法')
        fields['difficulty'] = difficulty

    if 'chapter' in data:
        chapter = str(data.get('chapter') or '').strip()
        if len(chapter) > _MAX_CHAPTER_LEN:
            raise ValueError(f'章节长度不能超过 {_MAX_CHAPTER_LEN} 个字符')
        fields['chapter'] = chapter

    if 'source' in data:
        source = str(data.get('source') or '').strip()
        if len(source) > _MAX_SOURCE_LEN:
            raise ValueError(f'来源长度不能超过 {_MAX_SOURCE_LEN} 个字符')
        fields['source'] = source

    if 'tags' in data:
        fields['tags'] = _clean_tags(data.get('tags'))

    for key in ('question_latex', 'solution_latex', 'solution_ja'):
        if key in data:
            value = data.get(key)
            if value is not None and not isinstance(value, str):
                raise ValueError('LaTeX 内容必须为字符串')
            fields[key] = value or ''

    for key in ('question_image', 'solution_image'):
        if key in data:
            value = str(data.get(key) or '').strip()
            # basename 防路径穿越;空串表示清除附件
            fields[key] = os.path.basename(value) if value else None

    return fields


def _apply_fields(question, fields):
    """把校验后的字段写入模型实例。"""
    for key, value in fields.items():
        if key == 'tags':
            question.tags_list = value
        else:
            setattr(question, key, value)


# ---------------------------------------------------------------- 文件辅助

def _upload_folder():
    return current_app.config['UPLOAD_FOLDER']


def _remove_image_files(filenames):
    """删除 uploads 中不再被任何题目引用的图片文件(须在 commit 之后调用)。"""
    for raw in set(f for f in filenames if f):
        name = os.path.basename(raw)
        if not name:
            continue
        still_used = db.session.query(
            Question.query.filter(
                or_(Question.question_image == name,
                    Question.solution_image == name)
            ).exists()
        ).scalar()
        if still_used:
            continue
        path = os.path.join(_upload_folder(), name)
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError as exc:
            current_app.logger.warning('删除图片文件失败 %s: %s', name, exc)


# ================================================================ 题目查询

def _knowledge_tag_names(question_ids):
    """批量取题目的知识点标签名:{question_id: [name, ...]}。一次查询避免逐题 N+1。"""
    ids = list(question_ids)
    if not ids:
        return {}
    rows = (db.session.query(QuestionTag.question_id, Tag.name)
            .join(Tag, Tag.id == QuestionTag.tag_id)
            .filter(QuestionTag.question_id.in_(ids), Tag.category == '知识点')
            .all())
    out = {}
    for qid, name in rows:
        out.setdefault(qid, []).append(name)
    return out


@bp.route('/questions', methods=['GET'])
@login_required
def list_questions():
    """题目列表:基础筛选 + 高级搜索 + 分页。"""
    args = request.args
    try:
        page = max(int(args.get('page', 1)), 1)
    except (TypeError, ValueError):
        return _fail('page 参数必须为整数')
    try:
        per_page = int(args.get('per_page', 20))
    except (TypeError, ValueError):
        return _fail('per_page 参数必须为整数')
    if per_page not in config.PER_PAGE_OPTIONS:
        per_page = 20

    query = Question.query

    subject = (args.get('subject') or '').strip()
    if subject:
        query = query.filter(Question.subject == subject)

    chapter = (args.get('chapter') or '').strip()
    if chapter:
        query = query.filter(Question.chapter == chapter)

    difficulty = (args.get('difficulty') or '').strip()
    if difficulty:
        query = query.filter(Question.difficulty == difficulty)

    source = (args.get('source') or '').strip()
    if source:
        pattern = f'%{_escape_like(source)}%'
        query = query.filter(Question.source.like(pattern, escape='\\'))

    search = (args.get('search') or '').strip()
    if search:
        # 检索强化(2026-07-24):多词按 AND(词间与),每词命中 = 出现在任一正文/元信息
        # 字段(含日本語詳解轨 solution_ja),或该题挂名称含此词的知识点标签。标签名命中走
        # 子查询 id IN(...),不与既有 knowledgeTags 的 join/distinct/group_by 冲突。
        # 上限 6 词防滥用;单词查询是旧行为的超集(多覆盖 solution_ja 与标签名)。
        terms = [t for t in search.split() if t][:6]
        for term in terms:
            pattern = f'%{_escape_like(term)}%'
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

    question_id = (args.get('questionId') or '').strip()
    if question_id:
        try:
            qid = int(question_id.lstrip('#'))
        except ValueError:
            return _fail('题目 ID 必须为整数')
        query = query.filter(Question.id == qid)

    tag_filter = (args.get('tagFilter') or '').strip()
    if tag_filter:
        tags = [t.strip() for t in tag_filter.replace('，', ',').split(',') if t.strip()]
        if tags:
            # tags 以 JSON 字符串存储,含任一标签即命中
            clauses = [Question.tags.like(f'%"{_escape_like(t)}"%', escape='\\')
                       for t in tags]
            query = query.filter(or_(*clauses))

    date_from = (args.get('dateFrom') or '').strip()
    date_to = (args.get('dateTo') or '').strip()
    try:
        if date_from:
            query = query.filter(Question.created_at >= _parse_date(date_from, '起始'))
        if date_to:
            # 含当天:严格小于次日零点
            query = query.filter(
                Question.created_at < _parse_date(date_to, '截止') + timedelta(days=1))
    except ValueError as exc:
        return _fail(str(exc))

    # 院試定位筛选(2026-07-19):院校/専攻走 source 前缀锚定,年份走 chapter(exam-harvest
    # 恒 chapter==年份),学科范围走 subject 归组。専攻在 UI 上从属院校,故与院校联合锚定。
    school = (args.get('school') or '').strip()
    major = (args.get('major') or '').strip()
    if school and major:
        query = query.filter(Question.source.like(
            f'{_escape_like(school)} {_escape_like(major)} %', escape='\\'))
    elif school:
        query = query.filter(Question.source.like(f'{_escape_like(school)} %', escape='\\'))
    elif major:
        query = query.filter(Question.source.like(f'% {_escape_like(major)} %', escape='\\'))

    year = (args.get('year') or '').strip()
    if year:
        query = query.filter(Question.chapter == year)

    subject_group = (args.get('subjectGroup') or '').strip()
    if subject_group:
        subs = dict(_SUBJECT_GROUPS).get(subject_group)
        if subs:
            query = query.filter(Question.subject.in_(subs))

    # 掌握状态筛选(2026-07-23):按当前用户的 question_progress 过滤。
    # user_id 条件必须放进 outerjoin 的 ON 子句,否则 outer join 退化为 inner join,
    # new(无进度)一档就永远查不到题。仅在有值时才 join,不影响其他查询的计数/分页。
    mastery_status = (args.get('masteryStatus') or '').strip()
    if mastery_status in ('new', 'done', 'mastered'):
        query = query.outerjoin(
            QuestionProgress,
            (QuestionProgress.question_id == Question.id)
            & (QuestionProgress.user_id == g.user.id))
        if mastery_status == 'new':
            query = query.filter(QuestionProgress.id.is_(None))
        elif mastery_status == 'done':
            query = query.filter(QuestionProgress.status.in_(('done', 'mastered')))
        else:  # mastered
            query = query.filter(QuestionProgress.status == 'mastered')

    # 规范化知识点标签筛选(2026-07-23):独立于 Question.tags 的自由 JSON 标签(tagFilter)。
    # 仅当 knowledgeTags 非空才 join question_tags/tags,不影响其他查询的计数/分页。
    # any(默认)→ 命中任一标签,distinct 去重;all → group by 题目、having 命中标签种数等于请求数。
    knowledge_raw = (args.get('knowledgeTags') or '').strip()
    if knowledge_raw:
        names = [t.strip() for t in knowledge_raw.replace('，', ',').split(',') if t.strip()]
        names = list(dict.fromkeys(names))  # 去重保序
        if names:
            tag_mode = (args.get('tagMode') or 'any').strip().lower()
            query = (query.join(QuestionTag, QuestionTag.question_id == Question.id)
                          .join(Tag, Tag.id == QuestionTag.tag_id)
                          .filter(Tag.name.in_(names)))
            if tag_mode == 'all':
                query = (query.group_by(Question.id)
                              .having(func.count(func.distinct(Tag.id)) == len(names)))
            else:
                query = query.distinct()

    pagination = (query.order_by(Question.created_at.desc(), Question.id.desc())
                       .paginate(page=page, per_page=per_page, error_out=False))
    return _ok({
        'questions': [q.to_dict() for q in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': per_page,
        'pages': pagination.pages,
    })


@bp.route('/questions/<int:qid>', methods=['GET'])
@login_required
def get_question(qid):
    """单题详情。附 knowledge_tags(规范化知识点标签名),供详情页出可点标签。"""
    question = db.session.get(Question, qid)
    if question is None:
        return _fail('题目不存在', code='NOT_FOUND', status=404)
    d = question.to_dict()
    d['knowledge_tags'] = _knowledge_tag_names([qid]).get(qid, [])
    return _ok({'question': d})


@bp.route('/questions/<int:qid>/related', methods=['GET'])
@login_required
def related_questions(qid):
    """相关题:按共享知识点标签数排序,不足 limit 时以同科目最新题兜底。

    卡片为轻量元信息(不含题解正文):id/source/subject/difficulty/chapter/
    shared_tags(候选∩目标 的知识点标签名)/shared_count/has_solution。
    basis:tags(全靠标签)| subject(全靠兜底)| mixed(两者)。
    """
    target = db.session.get(Question, qid)
    if target is None:
        return _fail('题目不存在', code='NOT_FOUND', status=404)
    try:
        limit = int(request.args.get('limit', 6))
    except (TypeError, ValueError):
        limit = 6
    limit = max(1, min(limit, 12))

    # 目标题的知识点 tag_id 集合
    target_tag_ids = [tid for (tid,) in (
        db.session.query(QuestionTag.tag_id)
        .join(Tag, Tag.id == QuestionTag.tag_id)
        .filter(QuestionTag.question_id == qid, Tag.category == '知识点').all())]

    # 共享标签命中:{question_id: shared_count}
    shared_map = {}
    if target_tag_ids:
        rows = (db.session.query(QuestionTag.question_id,
                                 func.count(func.distinct(QuestionTag.tag_id)))
                .filter(QuestionTag.tag_id.in_(target_tag_ids),
                        QuestionTag.question_id != qid)
                .group_by(QuestionTag.question_id).all())
        shared_map = {q: c for (q, c) in rows}

    hit_questions = (Question.query.filter(Question.id.in_(list(shared_map)))
                     .all() if shared_map else [])
    hit_questions.sort(
        key=lambda q: (shared_map.get(q.id, 0),
                       1 if q.subject == target.subject else 0,
                       q.created_at or datetime.min),
        reverse=True)
    chosen = hit_questions[:limit]
    used_tags = bool(chosen)

    # 兜底:同科目最新题补足
    used_subject = False
    if len(chosen) < limit:
        exclude = {qid} | {q.id for q in chosen}
        fillers = (Question.query
                   .filter(Question.subject == target.subject,
                           Question.id.notin_(exclude))
                   .order_by(Question.created_at.desc(), Question.id.desc())
                   .limit(limit - len(chosen)).all())
        used_subject = bool(fillers)
        chosen.extend(fillers)

    names_map = _knowledge_tag_names([q.id for q in chosen])
    target_names = set(_knowledge_tag_names([qid]).get(qid, []))

    def _card(q):
        return {
            'id': q.id,
            'source': q.source or '',
            'subject': q.subject,
            'difficulty': q.difficulty,
            'chapter': q.chapter or '',
            'shared_tags': [n for n in names_map.get(q.id, []) if n in target_names],
            'shared_count': shared_map.get(q.id, 0),
            'has_solution': bool((q.solution_ja or '').strip()
                                 or (q.solution_latex or '').strip()),
        }

    basis = 'mixed' if (used_tags and used_subject) else ('tags' if used_tags else 'subject')
    return _ok({'related': [_card(q) for q in chosen], 'basis': basis})


# ================================================================ 题目增删改

@bp.route('/questions', methods=['POST'])
@login_required
def create_question():
    """新建题目。"""
    data = request.get_json(silent=True)
    if data is None:
        return _fail('请求体必须为 JSON')
    try:
        fields = _extract_question_fields(data, partial=False)
    except ValueError as exc:
        return _fail(str(exc))

    question = Question()
    _apply_fields(question, fields)
    try:
        db.session.add(question)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('创建题目失败')
        return _fail('创建题目失败,请稍后重试', code='SERVER_ERROR', status=500)
    return _ok({'question': question.to_dict()}, message='创建成功')


@bp.route('/questions/<int:qid>', methods=['PUT'])
@login_required
def update_question(qid):
    """更新题目(部分字段可省略,省略则不改)。"""
    question = db.session.get(Question, qid)
    if question is None:
        return _fail('题目不存在', code='NOT_FOUND', status=404)

    data = request.get_json(silent=True)
    if data is None:
        return _fail('请求体必须为 JSON')
    try:
        fields = _extract_question_fields(data, partial=True)
    except ValueError as exc:
        return _fail(str(exc))

    # 记录被替换/清除的旧附件,提交成功后清理孤儿文件
    replaced_images = []
    for key in ('question_image', 'solution_image'):
        old = getattr(question, key)
        if key in fields and old and old != fields[key]:
            replaced_images.append(old)

    _apply_fields(question, fields)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('更新题目失败 id=%s', qid)
        return _fail('更新题目失败,请稍后重试', code='SERVER_ERROR', status=500)

    _remove_image_files(replaced_images)
    return _ok({'question': question.to_dict()}, message='保存成功')


@bp.route('/questions/<int:qid>', methods=['DELETE'])
@login_required
def delete_question(qid):
    """删除题目(错题本关联、查看日志由级联清理;附件文件一并删除)。"""
    question = db.session.get(Question, qid)
    if question is None:
        return _fail('题目不存在', code='NOT_FOUND', status=404)

    images = [question.question_image, question.solution_image]
    try:
        db.session.delete(question)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('删除题目失败 id=%s', qid)
        return _fail('删除题目失败,请稍后重试', code='SERVER_ERROR', status=500)

    audit('question_delete', target=qid)
    _remove_image_files(images)
    return _ok(message='删除成功')


# ================================================================ 批量操作

@bp.route('/questions/batch_delete', methods=['POST'])
@login_required
def batch_delete():
    """批量删除题目。"""
    data = request.get_json(silent=True) or {}
    try:
        ids = _parse_id_list(data.get('ids'))
    except ValueError as exc:
        return _fail(str(exc))

    questions = Question.query.filter(Question.id.in_(ids)).all()
    if not questions:
        return _ok({'deleted': 0}, message='没有可删除的题目')

    images = []
    for q in questions:
        images.extend([q.question_image, q.solution_image])
    try:
        for q in questions:
            db.session.delete(q)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('批量删除题目失败')
        return _fail('批量删除失败,请稍后重试', code='SERVER_ERROR', status=500)

    audit('question_batch_delete', target=','.join(map(str, ids[:50])), detail=f'count={len(questions)}')
    _remove_image_files(images)
    return _ok({'deleted': len(questions)}, message=f'已删除 {len(questions)} 道题目')


@bp.route('/questions/batch_update_tags', methods=['POST'])
@login_required
def batch_update_tags():
    """批量编辑标签:replace 整体替换 / add 追加去重。"""
    data = request.get_json(silent=True) or {}
    try:
        ids = _parse_id_list(data.get('ids'))
        tags = _clean_tags(data.get('tags'))
    except ValueError as exc:
        return _fail(str(exc))

    mode = data.get('mode') or 'replace'
    if mode not in ('replace', 'add'):
        return _fail("mode 只能为 'replace' 或 'add'")
    if mode == 'add' and not tags:
        return _fail('追加模式下请至少提供一个标签')

    questions = Question.query.filter(Question.id.in_(ids)).all()
    try:
        for q in questions:
            if mode == 'replace':
                q.tags_list = tags
            else:
                existing = q.tags_list
                q.tags_list = existing + [t for t in tags if t not in existing]
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('批量编辑标签失败')
        return _fail('批量编辑标签失败,请稍后重试', code='SERVER_ERROR', status=500)
    return _ok({'updated': len(questions)}, message=f'已更新 {len(questions)} 道题目的标签')


@bp.route('/questions/batch_update_source', methods=['POST'])
@login_required
def batch_update_source():
    """批量修改来源。"""
    data = request.get_json(silent=True) or {}
    try:
        ids = _parse_id_list(data.get('ids'))
    except ValueError as exc:
        return _fail(str(exc))

    source = str(data.get('source') or '').strip()
    if not source:
        return _fail('来源不能为空')
    if len(source) > _MAX_SOURCE_LEN:
        return _fail(f'来源长度不能超过 {_MAX_SOURCE_LEN} 个字符')

    questions = Question.query.filter(Question.id.in_(ids)).all()
    try:
        for q in questions:
            q.source = source
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('批量修改来源失败')
        return _fail('批量修改来源失败,请稍后重试', code='SERVER_ERROR', status=500)
    return _ok({'updated': len(questions)}, message=f'已更新 {len(questions)} 道题目的来源')


# ================================================================ 筛选字典

@bp.route('/questions/filters', methods=['GET'])
@login_required
def question_filters():
    """筛选下拉字典:章节/来源/标签(去重排序;可按课程联动)。"""
    subject = (request.args.get('subject') or '').strip()
    query = db.session.query(Question.chapter, Question.source, Question.tags)
    if subject:
        query = query.filter(Question.subject == subject)

    chapters, sources, tag_set = set(), set(), set()
    for chapter, source, tags_json in query.all():
        if chapter:
            chapters.add(chapter)
        if source:
            sources.add(source)
        if tags_json:
            try:
                parsed = json.loads(tags_json)
            except (TypeError, ValueError):
                parsed = []
            if isinstance(parsed, list):
                tag_set.update(str(t).strip() for t in parsed if str(t).strip())

    return _ok({
        'chapters': sorted(chapters),
        'sources': sorted(sources),
        'tags': sorted(tag_set),
    })


@bp.route('/questions/facets', methods=['GET'])
@login_required
def question_facets():
    """定位筛选字典:院校→専攻(嵌套)、年份、学科范围(带题量)。
    从 source 标签解析院校/専攻/年份(非院試格式的题不进入此三级,仍可经课程/来源筛选)。"""
    rows = db.session.query(Question.source, Question.chapter, Question.subject).all()
    school_majors = {}          # 院校 -> {専攻: 计数}
    years, group_count = {}, {}
    for source, chapter, subject in rows:
        parsed = _parse_exam_label(source)
        if parsed:
            school, major, ylabel = parsed
            school_majors.setdefault(school, {})
            school_majors[school][major] = school_majors[school].get(major, 0) + 1
        # 年份优先取 chapter(exam-harvest 恒为年份);否则回落到标签解析出的年份
        y = chapter if (chapter or '').isdigit() and len(chapter) == 4 else (parsed[2] if parsed else None)
        if y:
            years[y] = years.get(y, 0) + 1
        grp = _SUBJECT_TO_GROUP.get(subject)
        if grp:
            group_count[grp] = group_count.get(grp, 0) + 1

    schools = [{
        'name': s,
        'count': sum(majors.values()),
        'majors': [{'name': mj, 'count': c} for mj, c in sorted(majors.items())],
    } for s, majors in sorted(school_majors.items(), key=lambda kv: -sum(kv[1].values()))]

    return _ok({
        'schools': schools,
        'years': sorted(years.keys(), reverse=True),
        'subjectGroups': [{'name': g, 'count': group_count.get(g, 0)}
                          for g, _ in _SUBJECT_GROUPS if group_count.get(g)],
    })


@bp.route('/questions/tag_facets', methods=['GET'])
@login_required
def tag_facets():
    """规范化知识点标签字典:按 category 分组,每标签带被引用题数(join question_tags 计数)。

    只列出至少被一道题引用的标签(未挂题的孤儿标签点选无结果,不进 facet);
    空标签库或全为孤儿标签时 categories 为空数组。
    """
    rows = (db.session.query(
                Tag.category, Tag.name,
                func.count(QuestionTag.question_id))
            .join(QuestionTag, QuestionTag.tag_id == Tag.id)
            .group_by(Tag.id)
            .order_by(Tag.category, Tag.name)
            .all())

    grouped = {}  # category -> [{name, count}]
    order = []    # 保持 category 首次出现顺序
    for category, name, count in rows:
        if category not in grouped:
            grouped[category] = []
            order.append(category)
        grouped[category].append({'name': name, 'count': count})

    categories = [{'category': c, 'tags': grouped[c]} for c in order]
    return _ok({'categories': categories})


# ================================================================ 来源判重

@bp.route('/source_exists', methods=['GET'])
@login_required
def source_exists():
    """来源判重(精确匹配;编辑时可用 exclude_id 排除自身)。"""
    source = (request.args.get('source') or '').strip()
    if not source:
        return _ok({'exists': False})

    query = Question.query.filter(Question.source == source)
    exclude_raw = (request.args.get('exclude_id') or '').strip()
    if exclude_raw:
        try:
            query = query.filter(Question.id != int(exclude_raw))
        except ValueError:
            return _fail('exclude_id 必须为整数')
    exists = db.session.query(query.exists()).scalar()
    return _ok({'exists': bool(exists)})


# ================================================================ 查看日志

@bp.route('/log_view_question', methods=['POST'])
@login_required
def log_view_question():
    """记录题目查看行为(支撑学习统计)。"""
    data = request.get_json(silent=True) or {}
    raw = data.get('question_id')
    if isinstance(raw, bool):
        return _fail('question_id 必须为整数')
    try:
        question_id = int(raw)
    except (TypeError, ValueError):
        return _fail('question_id 必须为整数')

    question = db.session.get(Question, question_id)
    if question is None:
        return _fail('题目不存在', code='NOT_FOUND', status=404)

    try:
        db.session.add(ViewLog(user_id=g.user.id, question_id=question_id))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('写入查看日志失败 question_id=%s', question_id)
        return _fail('记录查看日志失败', code='SERVER_ERROR', status=500)
    return _ok(message='ok')


# ================================================================ 图片上传/删除

@bp.route('/upload_question_image', methods=['POST'])
@login_required
def upload_question_image():
    """上传题目/解答附件(image/* 与 PDF;uuid 重命名,扩展名白名单)。"""
    file = request.files.get('file')
    if file is None or not (file.filename or '').strip():
        return _fail('未选择文件')

    filename = file.filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    allowed = current_app.config.get('ALLOWED_UPLOAD_EXTENSIONS', set())
    if not ext or ext not in allowed:
        return _fail('不支持的文件类型,仅允许:' + '、'.join(sorted(allowed)))

    mimetype = (file.mimetype or '').lower()
    if mimetype and not (mimetype.startswith('image/') or mimetype == 'application/pdf'):
        return _fail('仅支持图片或 PDF 文件')

    new_name = uuid.uuid4().hex + '.' + ext
    try:
        os.makedirs(_upload_folder(), exist_ok=True)
        file.save(os.path.join(_upload_folder(), new_name))
    except OSError:
        current_app.logger.exception('保存上传文件失败')
        return _fail('文件保存失败,请稍后重试', code='SERVER_ERROR', status=500)
    return _ok({'filename': new_name, 'url': f'/uploads/{new_name}'}, message='上传成功')


@bp.route('/delete_question_image', methods=['POST'])
@login_required
def delete_question_image():
    """删除上传的附件文件(basename 防路径穿越;文件不存在也视为成功)。

    注意:不自动清空引用它的题目字段,由调用方在保存题目时处理。
    """
    data = request.get_json(silent=True) or {}
    raw = str(data.get('filename') or '').strip()
    if not raw:
        return _fail('缺少文件名')

    name = os.path.basename(raw)
    if not name or name in ('.', '..'):
        return _fail('文件名不合法')

    folder = os.path.realpath(_upload_folder())
    path = os.path.realpath(os.path.join(folder, name))
    if not path.startswith(folder + os.sep):
        return _fail('文件名不合法')

    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        current_app.logger.exception('删除附件文件失败 %s', name)
        return _fail('删除文件失败,请稍后重试', code='SERVER_ERROR', status=500)
    return _ok(message='已删除')
