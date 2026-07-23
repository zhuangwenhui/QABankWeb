#!/usr/bin/env python
"""官方题单自动生成(纯元数据,无需 LLM)。

生成规则:
  1. 按院校×専攻×年份:同一「院校 専攻 年份」聚成一单(标题「… 真题」),
     题按 source 里的「第N問」升序。
  2. 按学科:每个 subject 一单(标题「… 专项」),题按年份倒序。

owner = 第一个 admin 用户;is_official=True;is_public=True。
幂等:按 title 判重,已存在的官方单跳过(不重复建、不改动既有 items)。

用法:
  .venv/bin/python scripts/gen_official_lists.py [--db instance/question_bank.db]
"""
import argparse
import os
import re
import sys

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from api.questions import _parse_exam_label  # noqa: E402  复用 source 解析
from models import (Question, QuestionList, QuestionListItem,  # noqa: E402
                    User)

_MON_RE = re.compile(r'第(\d+)問')
_YEAR_RE = re.compile(r'(\d{4})')


def _mondai_no(source):
    """从 source 抽取「第N問」序号;缺失置于末尾(大数)。"""
    m = _MON_RE.search(source or '')
    return int(m.group(1)) if m else 10 ** 6


def _year_of(q):
    """题目年份:优先 chapter 里的 4 位数字,退回 source 解析。"""
    m = _YEAR_RE.search(q.chapter or '')
    if m:
        return int(m.group(1))
    parsed = _parse_exam_label(q.source)
    return int(parsed[2]) if parsed else 0


def _candidate_lists(session):
    """返回候选题单 [(title, [有序 question_id]), ...](尚未落库)。"""
    questions = session.query(Question).all()

    # 规则 1:院校 × 専攻 × 年份
    exam_groups = {}
    for q in questions:
        parsed = _parse_exam_label(q.source)
        if not parsed:
            continue
        school, major, year = parsed
        exam_groups.setdefault((school, major, year), []).append(q)

    candidates = []
    for (school, major, year), qs in exam_groups.items():
        qs.sort(key=lambda q: (_mondai_no(q.source), q.id))
        title = f'{school} {major} {year} 真题'
        candidates.append((title, [q.id for q in qs]))

    # 规则 2:按学科(年份倒序,同年按 問 序号升序)
    subject_groups = {}
    for q in questions:
        if not q.subject:
            continue
        subject_groups.setdefault(q.subject, []).append(q)
    for subject, qs in subject_groups.items():
        qs.sort(key=lambda q: (-_year_of(q), _mondai_no(q.source), q.id))
        title = f'{subject} 专项'
        candidates.append((title, [q.id for q in qs]))

    return candidates


def generate(db_path, verbose=False):
    """对指定 SQLite 库生成官方题单;返回本次新建的题单数(幂等)。"""
    engine = create_engine(f'sqlite:///{db_path}')
    session = sessionmaker(bind=engine)()
    created = 0
    try:
        admin = (session.query(User)
                 .filter(User.role == 'admin')
                 .order_by(User.id).first())
        if admin is None:
            if verbose:
                print('未找到 admin 用户,跳过生成。')
            return 0

        existing_titles = {t for (t,) in session.query(QuestionList.title)
                           .filter(QuestionList.is_official.is_(True)).all()}

        for title, qids in _candidate_lists(session):
            if not qids or title in existing_titles:
                continue
            lst = QuestionList(owner_id=admin.id, title=title,
                               description='系统自动生成的官方精选题单',
                               is_official=True, is_public=True)
            session.add(lst)
            session.flush()
            for pos, qid in enumerate(qids):
                session.add(QuestionListItem(list_id=lst.id, question_id=qid,
                                             position=pos))
            existing_titles.add(title)
            created += 1
            if verbose:
                print(f'  + 新建官方单「{title}」({len(qids)} 题)')
        session.commit()
    finally:
        session.close()
        engine.dispose()
    return created


def main():
    parser = argparse.ArgumentParser(description='生成官方精选题单(幂等)')
    parser.add_argument('--db', default='instance/question_bank.db',
                        help='SQLite 数据库路径')
    args = parser.parse_args()
    if not os.path.exists(args.db):
        print(f'数据库不存在:{args.db}')
        raise SystemExit(1)

    # 报告库中当前官方单数
    engine = create_engine(f'sqlite:///{args.db}')
    session = sessionmaker(bind=engine)()
    before = session.query(func.count(QuestionList.id)).filter(
        QuestionList.is_official.is_(True)).scalar() or 0
    session.close()
    engine.dispose()

    print(f'目标库:{args.db}(已有官方单 {before} 个)')
    created = generate(args.db, verbose=True)
    print(f'完成:本次新建 {created} 个官方题单,现共 {before + created} 个。')


if __name__ == '__main__':
    main()
