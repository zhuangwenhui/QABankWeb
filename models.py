"""数据模型:用户、题目、错题本、反馈、查看日志。"""
import json
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def _fmt(dt):
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
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
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

    error_entries = db.relationship('ErrorBook', backref='question', lazy='dynamic',
                                    cascade='all, delete-orphan')
    view_logs = db.relationship('ViewLog', backref='question', lazy='dynamic',
                                cascade='all, delete-orphan')

    @property
    def tags_list(self):
        try:
            data = json.loads(self.tags or '[]')
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    @tags_list.setter
    def tags_list(self, value):
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
        self.solution_structured = json.dumps(dict(value or {}), ensure_ascii=False)

    def to_dict(self, with_solution=True):
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
            'created_at': _fmt(self.created_at),
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
        return {
            'id': self.id,
            'question_id': self.question_id,
            'notes': self.notes or '',
            'created_at': _fmt(self.created_at),
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
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content or '',
            'status': self.status,
            'reply': self.reply or '',
            'created_at': _fmt(self.created_at),
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


# --------------------------------------------------------------------- SQLite 加固
from sqlalchemy import event as _sa_event
from sqlalchemy.engine import Engine as _Engine


# 注意:全局 Engine 监听,Alembic 迁移连接同样生效;迁移期需关外键,见 migrations/env.py
@_sa_event.listens_for(_Engine, 'connect')
def _sqlite_pragmas(dbapi_connection, connection_record):
    """每个 SQLite 连接建立时启用外键约束、WAL 与忙等待。

    - foreign_keys:SQLite 默认 OFF,不开则 ForeignKey/级联形同虚设
    - journal_mode=WAL:读写不互斥,多用户并发的基础(内存库返回 memory,无害);
      WAL 为库级持久设置,此处每连接重复执行为幂等确认
    - busy_timeout:写锁冲突时等待 5s 而非立刻 database is locked
    """
    if type(dbapi_connection).__module__.startswith('sqlite3'):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA busy_timeout=5000')
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.close()
