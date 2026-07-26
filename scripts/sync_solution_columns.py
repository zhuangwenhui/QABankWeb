#!/usr/bin/env python3
"""把本地整理好的题解正文同步进**在跑的**生产库,只动题面与题解这五列。

为什么不是"传一个整库覆盖过去":生产库同时装着用户数据(笔记、收藏、进度、作答、
错题本),整库覆盖会把这些一并抹掉。所以只更新 questions 表的五列(题面、中日两轨题解、
采点结构化、渐进提示),其余分毫不动。

并发保护:同步用三个库。
    base   —— 拉快照那一刻的生产库(即"我以为的现状")
    final  —— 在 base 上改完的结果
    live   —— 现在真正在跑的库
只有当 live 的当前值与 base 完全一致时才写入。若某题在这期间被人改过(live≠base),
该题**跳过并报出来**,绝不用旧内容盖掉新编辑。

用法(在服务器上跑):
    python sync_solution_columns.py --live instance/question_bank.db \
        --base /tmp/base.db --final /tmp/final.db            # 试算
    python sync_solution_columns.py ... --apply              # 写库(先备份)
"""
import argparse
import sqlite3
import sys

# question_latex(题面)也在同步范围内,但它是入试原题的转写,改它就可能变成另一道题。
# 只有当出错的那段本身是**录题者自撰的内容**(如照图整理的边表)、且逐条复核过时才该动;
# 本脚本不做这个判断,判断在上游 —— 这里只保证"我以为的现状"没被人动过。
COLUMNS = ('question_latex', 'solution_latex', 'solution_ja',
           'solution_structured', 'hints')
SELECT = 'SELECT id, ' + ', '.join(f"COALESCE({c},'')" for c in COLUMNS) + ' FROM questions'


def load(path):
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    return {r[0]: tuple(r[1:]) for r in con.execute(SELECT)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--live', required=True)
    ap.add_argument('--base', required=True)
    ap.add_argument('--final', required=True)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    base, final = load(args.base), load(args.final)
    live_con = sqlite3.connect(args.live if args.apply else f'file:{args.live}?mode=ro',
                               uri=not args.apply)
    live = {r[0]: tuple(r[1:]) for r in live_con.execute(SELECT)}

    todo, skipped, missing = [], [], []
    for qid, new in final.items():
        old = base.get(qid)
        cur = live.get(qid)
        if cur is None:
            missing.append(qid)
            continue
        if old is None or new == old:
            continue                      # 本次没改这道题
        if cur != old:
            skipped.append(qid)           # 期间被人动过,不覆盖
            continue
        todo.append((*new, qid))

    print(f'快照 {len(base)} 道 / 本次改动 {sum(1 for k, v in final.items() if base.get(k) != v)} 道')
    print(f'可安全写入 {len(todo)} 道;因线上已变更而跳过 {len(skipped)} 道;线上不存在 {len(missing)} 道')
    if skipped:
        print('  跳过的题号:', skipped[:20])
    if missing:
        print('  缺失的题号:', missing[:20])

    if args.apply:
        with live_con:
            live_con.executemany(
                'UPDATE questions SET ' + ', '.join(f'{c}=?' for c in COLUMNS) + ' WHERE id=?',
                todo)
        print(f'✓ 已写入 {len(todo)} 道')
    else:
        print('(未写库;加 --apply 才落盘)')
    return 1 if skipped or missing else 0


if __name__ == '__main__':
    sys.exit(main())
