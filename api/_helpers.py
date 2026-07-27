"""蓝图共用小工具。

集中此前在各 api/*.py 各抄一份的响应信封、LIKE 转义,
并提供**单一实现**的题目全文搜索,消除 questions/error_book 的搜索行为漂移
(错题本此前漏了 solution_ja 与知识点标签命中)。

仅依赖 flask 与 models,不依赖任何蓝图,无循环导入。


关于各写入端点里那个 `with db.session.begin_nested():`
--------------------------------------------------
error_book / progress / lists / study 共五处 upsert 都是这个写法,含义在这里说一次:

    try:
        with db.session.begin_nested():      # 开一个 SAVEPOINT
            db.session.add(SomeRow(...))
    except IntegrityError:
        ...改为更新已存在的行 / 计入 skipped...

为什么非要 SAVEPOINT,不能只 try/except 包住 add:
  · SQLAlchemy 的 `add()` 只是把对象放进 session,唯一约束冲突要到 **flush** 才暴露。
    `begin_nested()` 退出时会 flush,冲突在这里就地抛出,而不是拖到最后 commit 才炸。
  · 更要命的是 IntegrityError 会让**整个事务**进入失效状态 —— 不回滚就再也提交不了。
    SAVEPOINT 让 except 分支只回退这一条,前面已经攒好的写入原样保留。
    批量加错题(api/error_book.py 的 add_batch)靠的就是这一点:一批 200 道里有 3 道
    已存在,那 3 道计入 skipped,其余 197 道照常入库。少了 SAVEPOINT,整批一起完蛋。

触发条件是**并发**:同一用户两个标签页同时点、或前端重试。单请求顺序执行时永远走不到
except 分支 —— 所以它没有测试覆盖,改的时候别以为跑绿了就没事。
"""
from datetime import datetime, timedelta

from flask import current_app, jsonify
from sqlalchemy import or_

from models import Question, QuestionTag, Tag, ViewLog, db


def ok(data=None, message=None, status=200):
    """成功信封:{success:True, data?, message?}。"""
    payload = {'success': True}
    if data is not None:
        payload['data'] = data
    if message:
        payload['message'] = message
    return jsonify(payload), status


def err(error, code='INVALID_INPUT', status=400):
    """失败信封:{success:False, error, code}。"""
    return jsonify(success=False, error=error, code=code), status


# 批量端点单次可处理的 ID 数上限。挡的是"一个请求让数据库扫十万行"这类放大攻击,
# 不是业务约束 —— 前端跨页全选最多也就几百条。
#
# ⚠️ 与前端对不上:static/js/error_book.js 的 collectFilteredIds() 最多收 50 页 × 100 = 5000 个
# id(生成"按当前筛选"的 PDF 试卷时用)。筛选结果超过 2000 条就会被这里拒掉。
# 生产 358 道题够不到,故一直没暴露;要修改前端那侧的上限,别抬高这个数。
MAX_BATCH_SIZE = 2000


def parse_id_list(value, field='question_ids', max_size=MAX_BATCH_SIZE):
    """把请求里的 ID 数组规整成**去重保序的正整数列表**;非法输入抛 ValueError。

    此前 questions 与 error_book/progress 各有一套解析器,在四点上语义相反:失败方式
    (抛异常 vs 返回 None)、空列表(拒绝 vs 接受)、非正数(接受 vs 拒绝)、批量上限
    (无 vs 2000)。同一个 `{"ids": [-1]}` 在两边一个 200 一个 400,没人说得清哪个对。
    V1 收尾时统一到**最严格的那套**:抛异常、拒非正数、有上限。

    **空列表不在这里判**:它返回 `[]`,由调用点决定该答什么 —— 写入类端点答
    「你没选东西」(400),查询类端点(check_batch)答空结果(200)。那是端点语义,
    不是解析语义,塞进解析器会逼着两类端点二选一。

    `isinstance(item, bool)` 那行不能省:Python 的 bool 是 int 的子类,少了它
    `{"question_ids": [true]}` 会被静静地当成题号 1 处理。

    已知的保留行为:`int(1.9)` 不抛异常,小数被**静默截断**成 1。合并前七份拷贝都是这样,
    统一的授权范围只覆盖上述四点,故原样保留;要收紧留给 V2.0。见
    tests/test_helpers_parsers.py 的 test_parse_id_list_truncates_float。
    """
    if not isinstance(value, list):
        raise ValueError(f'{field} 必须为数组')
    if len(value) > max_size:
        raise ValueError(f'{field} 单次最多 {max_size} 项')
    ids, seen = [], set()
    for item in value:
        if isinstance(item, bool):
            raise ValueError(f'{field} 的元素必须为正整数')
        try:
            n = int(item)
        except (TypeError, ValueError):
            raise ValueError(f'{field} 的元素必须为正整数')
        if n <= 0:
            raise ValueError(f'{field} 的元素必须为正整数')
        if n not in seen:
            seen.add(n)
            ids.append(n)
    return ids


def parse_question_id(data, field='question_id'):
    """从请求 JSON 里取单个正整数题号;非法时返回 None(不抛)。

    与 parse_id_list 的失败方式不同是**刻意**的:调用点全是
    `if qid is None: return _err('缺少 question_id')` 这种单值校验,给它套 try/except
    只会让每处多两行。此前 error_book/lists/progress/review 各抄了一份逐字节相同的实现。
    """
    value = data.get(field)
    if isinstance(value, bool):      # 同上:bool 是 int 子类,不拦则 true → 题号 1
        return None
    try:
        qid = int(value)
    except (TypeError, ValueError):
        return None
    return qid if qid > 0 else None


def upload_folder():
    """上传目录的绝对路径。questions 与 submissions 共用同一目录(题面图与作答图同盘)。"""
    return current_app.config['UPLOAD_FOLDER']


def escape_like(term):
    """转义 LIKE 通配符,配合 like(..., escape='\\\\') 使用。"""
    return (term.replace('\\', '\\\\')
                .replace('%', '\\%')
                .replace('_', '\\_'))


def apply_question_search(query, search):
    """把「多词 AND 全文搜索」施加到已含 Question 的 query 并返回。

    每词命中 = 出现在 question_latex/solution_latex/solution_ja/source/chapter 任一,
    或该题挂有名称含此词的知识点标签(子查询,不与主查询 join 冲突)。上限 6 词。
    questions 与 error_book 共用此单一实现,杜绝两处搜索覆盖面漂移。
    """
    terms = [t for t in (search or '').split() if t][:6]
    for term in terms:
        pattern = f'%{escape_like(term)}%'
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
    return query


def apply_basic_filters(query, args):
    """把 subject/chapter/difficulty/source/search 五个基础筛选施加到已含 Question 的 query。

    questions(题库列表)与 error_book(错题本列表)此前各写一份,逐条比对下来行为等价,
    只是取值写法不同:一处 `(args.get(k) or '').strip()`,一处 `args.get(k, '').strip()` ——
    参数缺失与传空串两种情形下两者都得 ''。合并取前者(对 args.get 返回 None 也稳)。

    source 走模糊、其余走精确,search 交给 apply_question_search 的多词 AND 实现。
    这条边界别动:source 是「東大 情報理工 2021」这类拼接串,精确匹配等于不可用。
    """
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
        pattern = f'%{escape_like(source)}%'
        query = query.filter(Question.source.like(pattern, escape='\\'))

    search = (args.get('search') or '').strip()
    if search:
        query = apply_question_search(query, search)

    return query


def prune_view_logs(retention_days=180):
    """删除超过保留期的查看日志,防 view_logs 无界增长拖慢统计聚合(rank17)。

    调用方按 id 采样触发(非每次),失败静默(不影响主写入)。
    """
    cutoff = datetime.now() - timedelta(days=retention_days)
    try:
        ViewLog.query.filter(ViewLog.viewed_at < cutoff).delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
