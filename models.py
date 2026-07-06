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
    solution_latex = db.Column(db.Text, default='')
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
                'solution_image': self.solution_image,
                'solution_image_url': f'/uploads/{self.solution_image}' if self.solution_image else None,
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

    def to_dict(self):
        return {
            'id': self.id,
            'question_id': self.question_id,
            'notes': self.notes or '',
            'created_at': _fmt(self.created_at),
            'question': self.question.to_dict() if self.question else None,
        }


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
