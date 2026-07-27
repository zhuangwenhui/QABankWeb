"""数据模型:用户、题目、错题本、反馈、查看日志。"""
import json
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def fmt_dt(dt):
    """datetime → 'YYYY-MM-DD HH:MM:SS';None 原样返回 None。

    全站对外的时间格式在此单点定义 —— SPEC §1 的 created_at 契约、前端 utils.js 的
    formatDate() 都按这个串来。api/ 下曾有六处手抄同一个 strftime 三元式,已改为复用本函数。
    """
    return dt.strftime('%Y-%m-%d %H:%M:%S') if dt else None


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(16), nullable=False, default='student')  # student | admin
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    error_entries = db.relationship('ErrorBook', backref='user', lazy='dynamic',
                                    cascade='all, delete-orphan')
    feedbacks = db.relationship('Feedback', backref='user', lazy='dynamic',
                                cascade='all, delete-orphan')

    def set_password(self, password):
        """存口令哈希(werkzeug 默认 scrypt),明文不落库、不进日志。"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """核对口令。内部是常数时间比较,别改成 == 自己比。"""
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        """是否管理员。角色只有 student / admin 两种,没有中间态。"""
        return self.role == 'admin'


class Question(db.Model):
    __tablename__ = 'questions'

    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(32), nullable=False, index=True)
    # 章节字段同时承载知识点章节(如"1 変数関数の微分法")与考试年份(如 2008-2021)
    chapter = db.Column(db.String(128), index=True)
    difficulty = db.Column(db.String(8), nullable=False, default='中等', index=True)
    source = db.Column(db.String(128), index=True)
    tags = db.Column(db.Text, default='[]')  # JSON 数组字符串
    question_latex = db.Column(db.Text, default='')
    question_image = db.Column(db.String(256))  # uploads/ 下的文件名
    solution_latex = db.Column(db.Text, default='')  # 中文·速览轨(既有)
    solution_ja = db.Column(db.Text, nullable=True)   # 日本語·詳解轨(新增,可空;旧题为 NULL)
    # 渐进提示:由浅入深的提示序列 JSON 数组 ["提示1","提示2",...](可空,旧题为 NULL)
    hints = db.Column(db.Text, nullable=True)
    # 采点结构化题解:JSON 对象 {"houshin":..,"model":..,"shitten":..,"haiten":..}(可空,旧题为 NULL)
    #   houshin=解答方針  model=答案例  shitten=典型失点  haiten=部分点分布(各段为 md 字符串)
    solution_structured = db.Column(db.Text, nullable=True)
    solution_image = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)

    # 删除一道题时,所有引用它的行必须一并清掉,否则 SQLite 抛
    # "FOREIGN KEY constraint failed",删除端点直接 500。
    # 历史教训:这里最初只声明了 error_book 与 view_logs,之后陆续加的标签(v1.3)、
    # 题单条目(v1.3)、做题进度(v1.2)、笔记/收藏(v1.6)、作答(v1.5)都没补 —— 而每道题
    # 都有标签,于是「删除题目」这个基础功能从 v1.3 起就一直是坏的,直到 2026-07-26 才发现。
    # 新增任何带 question_id 外键的表,都必须在此登记。护栏见 tests/test_delete_cascade.py。
    error_entries = db.relationship('ErrorBook', backref='question', lazy='dynamic',
                                    cascade='all, delete-orphan')
    view_logs = db.relationship('ViewLog', backref='question', lazy='dynamic',
                                cascade='all, delete-orphan')
    progress_entries = db.relationship('QuestionProgress', backref='question', lazy='dynamic',
                                       cascade='all, delete-orphan')
    list_items = db.relationship('QuestionListItem', backref='question', lazy='dynamic',
                                 cascade='all, delete-orphan')
    note_entries = db.relationship('QuestionNote', backref='question', lazy='dynamic',
                                   cascade='all, delete-orphan')
    bookmark_entries = db.relationship('QuestionBookmark', backref='question', lazy='dynamic',
                                       cascade='all, delete-orphan')
    tag_links = db.relationship('QuestionTag', backref='question', lazy='dynamic',
                                cascade='all, delete-orphan')
    submissions = db.relationship('AnswerSubmission', backref='question', lazy='dynamic',
                                  cascade='all, delete-orphan')

    @property
    def tags_list(self):
        """自由标签(JSON 数组字符串)→ list;解析失败或不是数组一律回 []。

        容错而不是抛:标签是展示用的附属信息,一条脏数据不该让整个列表页 500。
        注意这与规范化的知识点标签(Tag / QuestionTag 关联表)是**两套东西**,
        用途不同、并存 —— 见 SPEC §0。
        """
        try:
            data = json.loads(self.tags or '[]')
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    @tags_list.setter
    def tags_list(self, value):
        """写回 JSON。ensure_ascii=False 保证中文在库里可读,便于直接 sqlite3 排查。"""
        self.tags = json.dumps(list(value or []), ensure_ascii=False)

    @property
    def hints_list(self):
        """渐进提示解析:JSON 数组→list;非数组或解析失败→[](仿 tags_list 容错)。"""
        try:
            data = json.loads(self.hints or '[]')
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    @hints_list.setter
    def hints_list(self, value):
        """写回 JSON 数组。"""
        self.hints = json.dumps(list(value or []), ensure_ascii=False)

    @property
    def solution_structured_dict(self):
        """采点结构化题解解析:JSON 对象→dict;非对象或解析失败→{}(仿 tags_list 容错)。"""
        try:
            data = json.loads(self.solution_structured or '{}')
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    @solution_structured_dict.setter
    def solution_structured_dict(self, value):
        """写回 JSON 对象。"""
        self.solution_structured = json.dumps(dict(value or {}), ensure_ascii=False)

    def to_dict(self, with_solution=True):
        """题目的对外表示。**这里就是 API 契约本身**(SPEC §1 列的字段),改动即改接口。

        with_solution=False 时不带两轨题解正文:列表页一次要出 20-100 道,
        带上题解全文会让响应大出一个量级,而列表上根本不显示。
        时间统一走 fmt_dt(见本模块顶部),别在这里另写 strftime。
        """
        d = {
            'id': self.id,
            'subject': self.subject,
            'chapter': self.chapter or '',
            'difficulty': self.difficulty,
            'source': self.source or '',
            'tags': self.tags_list,
            'question_latex': self.question_latex or '',
            'question_image': self.question_image,
            'question_image_url': f'/uploads/{self.question_image}' if self.question_image else None,
            'created_at': fmt_dt(self.created_at),
        }
        if with_solution:
            d.update({
                'solution_latex': self.solution_latex or '',
                'solution_ja': self.solution_ja or '',
                'solution_image': self.solution_image,
                'solution_image_url': f'/uploads/{self.solution_image}' if self.solution_image else None,
                'hints': self.hints_list,                          # list;解析失败→[]
                'solution_structured': self.solution_structured_dict,  # dict;解析失败→{}
            })
        return d


class ErrorBook(db.Model):
    __tablename__ = 'error_book'
    __table_args__ = (db.UniqueConstraint('user_id', 'question_id', name='uq_user_question'),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False, index=True)
    notes = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.now)
    # SM-2 复习排期(全部可空,NULL 视为"到期/未排期",无需 server_default)
    ease = db.Column(db.Float, nullable=True)            # SM-2 easiness,默认视为 2.5
    interval_days = db.Column(db.Integer, nullable=True)  # 当前间隔
    repetitions = db.Column(db.Integer, nullable=True)   # 连续答对次数
    due_at = db.Column(db.DateTime, nullable=True, index=True)   # 下次复习时刻;NULL=立即到期
    last_reviewed_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        """错题条目的对外表示,**内嵌整道题**(question 字段走 Question.to_dict())。

        内嵌而不是只给 question_id:错题本列表要显示题面与题解,拆两次请求会让列表页
        变成 N+1。代价是响应偏大,故调用方在只需要计数时不要用这个方法。
        """
        return {
            'id': self.id,
            'question_id': self.question_id,
            'notes': self.notes or '',
            'created_at': fmt_dt(self.created_at),
            'question': self.question.to_dict() if self.question else None,
        }


class QuestionProgress(db.Model):
    """掌握状态轴:每个用户对每道题的做题进度(无行=未做)。"""
    __tablename__ = 'question_progress'
    __table_args__ = (db.UniqueConstraint('user_id', 'question_id', name='uq_progress_user_question'),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default='done')  # done | mastered
    updated_at = db.Column(db.DateTime, default=datetime.now, index=True)  # 兼作做题日历数据源


class QuestionList(db.Model):
    """题单(curated 学习路径):有序题目集合,可为官方精选或用户自建。"""
    __tablename__ = 'question_lists'

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, default='')
    is_official = db.Column(db.Boolean, nullable=False, default=False, index=True)  # 官方精选
    is_public = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class QuestionListItem(db.Model):
    """题单↔题目关联(同一题单不重复挂同一题,position 定序)。"""
    __tablename__ = 'question_list_items'
    __table_args__ = (db.UniqueConstraint('list_id', 'question_id', name='uq_list_question'),)

    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(db.Integer, db.ForeignKey('question_lists.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, default=0)


class QuestionNote(db.Model):
    """每个用户对每题的私人笔记(1:1,upsert)。"""
    __tablename__ = 'question_notes'
    __table_args__ = (db.UniqueConstraint('user_id', 'question_id', name='uq_note_user_question'),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False, index=True)
    content = db.Column(db.Text, default='')
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


class QuestionBookmark(db.Model):
    """收藏/书签:用户星标题目(存在即已收藏)。"""
    __tablename__ = 'question_bookmarks'
    __table_args__ = (db.UniqueConstraint('user_id', 'question_id', name='uq_bookmark_user_question'),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)


class Feedback(db.Model):
    __tablename__ = 'feedback'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(128), nullable=False)
    content = db.Column(db.Text, default='')
    status = db.Column(db.String(8), nullable=False, default='待处理', index=True)  # 待处理 | 已处理
    reply = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        """反馈工单的对外表示。带 username 便于管理员列表直接显示提交人,免去再查一次。"""
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content or '',
            'status': self.status,
            'reply': self.reply or '',
            'created_at': fmt_dt(self.created_at),
            'username': self.user.username if self.user else None,
            'user_id': self.user_id,
        }


class ViewLog(db.Model):
    """题目查看行为日志,支撑学习统计。"""
    __tablename__ = 'view_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False, index=True)
    viewed_at = db.Column(db.DateTime, default=datetime.now, index=True)


class GeneratedFile(db.Model):
    """PDF/试卷产物登记:属主校验与 TTL 清理的依据。"""
    __tablename__ = 'generated_files'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)


class Tag(db.Model):
    """规范化知识点标签:与 Question.tags(自由 JSON 标签)相互独立。

    同名标签可归属不同 category(如「概率」既是知识点也是概率论章节),
    故唯一性约束落在 (name, category) 组合上。
    """
    __tablename__ = 'tags'
    __table_args__ = (db.UniqueConstraint('name', 'category', name='uq_tag_name_category'),)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False, index=True)
    category = db.Column(db.String(32), nullable=False, default='知识点', index=True)


class QuestionTag(db.Model):
    """题目↔知识点标签的多对多关联(同一题不重复挂同一标签)。"""
    __tablename__ = 'question_tags'
    __table_args__ = (db.UniqueConstraint('question_id', 'tag_id', name='uq_question_tag'),)

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False, index=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('tags.id'), nullable=False, index=True)


class AnswerSubmission(db.Model):
    """学生手写作答提交 + 采点评分结果(1:1 内嵌,评分列 nullable 直到 graded)。

    学生上传作答照片,多模态 LLM(或占位 stub)按题目采点 rubric 逐项给分。
    image_paths / rubric_breakdown 存 JSON 字符串,容错解析同 Question.hints_list。
    """
    __tablename__ = 'answer_submissions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False, index=True)
    image_paths = db.Column(db.Text, default='[]')  # uploads/ 下的文件名 JSON 数组
    status = db.Column(db.String(16), nullable=False, default='pending', index=True)
    # 采点评分结果(graded 后填充)
    total_score = db.Column(db.Float, nullable=True)
    max_score = db.Column(db.Float, nullable=True)
    rubric_breakdown = db.Column(db.Text, nullable=True)   # JSON [{label,awarded,max,comment}]
    transcription = db.Column(db.Text, nullable=True)      # 模型读到的作答转写
    feedback = db.Column(db.Text, nullable=True)           # 综合反馈
    grader = db.Column(db.String(16), nullable=True)       # claude | stub
    model = db.Column(db.String(64), nullable=True)        # 具体模型名
    error = db.Column(db.Text, nullable=True)              # 失败原因
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
    graded_at = db.Column(db.DateTime, nullable=True)

    @property
    def image_paths_list(self):
        """作答图文件名列表(JSON 数组字符串)→ list;解析失败回 [](仿 tags_list 容错)。

        存的是**文件名**不是路径:上传目录由 config 决定,存绝对路径会让备份换机后全失效。
        """
        try:
            data = json.loads(self.image_paths or '[]')
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    @image_paths_list.setter
    def image_paths_list(self, value):
        """写回 JSON 数组。"""
        self.image_paths = json.dumps(list(value or []), ensure_ascii=False)

    @property
    def rubric_breakdown_list(self):
        """采点逐项得分(JSON 数组字符串)→ list;解析失败回 []。

        每项形如 {label, awarded, max, comment},由 grading._normalize 归一化后写入。
        """
        try:
            data = json.loads(self.rubric_breakdown or '[]')
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    @rubric_breakdown_list.setter
    def rubric_breakdown_list(self, value):
        """写回 JSON 数组。"""
        self.rubric_breakdown = json.dumps(list(value or []), ensure_ascii=False)

    def to_dict(self):
        """一份作答提交的对外表示:图片、评分、转写、反馈与两个时间戳。

        image_urls 由文件名现拼而不是入库:上传目录路径变了,历史记录不用跟着迁。
        """
        imgs = self.image_paths_list
        return {
            'id': self.id,
            'question_id': self.question_id,
            'status': self.status,
            'image_paths': imgs,
            'image_urls': ['/uploads/' + n for n in imgs],
            'total_score': self.total_score,
            'max_score': self.max_score,
            'rubric_breakdown': self.rubric_breakdown_list,
            'transcription': self.transcription or '',
            'feedback': self.feedback or '',
            'grader': self.grader,
            'model': self.model,
            'error': self.error or '',
            'created_at': fmt_dt(self.created_at),
            'graded_at': fmt_dt(self.graded_at),
        }


# --------------------------------------------------------------------- SQLite 加固
from sqlalchemy import event as _sa_event
from sqlalchemy.engine import Engine as _Engine


# 注意:全局 Engine 监听,Alembic 迁移连接同样生效;迁移期需关外键,见 migrations/env.py
@_sa_event.listens_for(_Engine, 'connect')
def _sqlite_pragmas(dbapi_connection, connection_record):
    """每个 SQLite 连接建立时设四条 PRAGMA:外键、忙等待、WAL、同步级别。

    - foreign_keys=ON:SQLite 默认 **OFF**,不开则 ForeignKey 与级联删除形同虚设
    - busy_timeout=5000:写锁冲突时等 5 秒,而不是立刻抛 database is locked
    - journal_mode=WAL:读写不互斥,多用户并发的基础(内存库返回 memory,无害);
      WAL 是**库级持久**设置,此处每连接重复执行只是幂等确认
    - synchronous=NORMAL:**拿持久性换性能**。默认的 FULL 每次提交都 fsync;NORMAL 下
      WAL 只在 checkpoint 时 fsync,写入快得多,代价是**操作系统崩溃或断电可能丢掉
      最后若干个已提交事务**(进程自己崩溃不会丢 —— 那种情况 WAL 仍是完整的)。
      单机自托管 + 每日 04:30 备份的前提下这个交换划算;哪天换成不能容忍丢数据的场景,
      要改的是这一行。
    """
    if type(dbapi_connection).__module__.startswith('sqlite3'):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA busy_timeout=5000')
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.close()
