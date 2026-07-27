#!/usr/bin/env python3
"""把被误改成全角的 markdown 有序列表符号改回来。

2026-07-26 的句読点归一化把「1. 」这样的**列表项目符号**也当成句点转成了「1。 」
(日文轨)或「1. 」→「1。 」(中文轨)。后果有两层:读着别扭,而且 markdown 不再把它
当有序列表渲染,整段列表塌成普通段落。

判定很窄:行首(允许缩进)+ 1~2 位数字 + 全角句点 + 空白。这个形状在正文里不会出现
——句子不会以"数字 + 句号 + 空格"开头。

用法:
    python scripts/repair_ordered_lists.py <db>            # 只报告
    python scripts/repair_ordered_lists.py <db> --apply    # 写库(先备份)

生命周期:这次事故的源头(fix_language.py 的句読点归一化)已于 2026-07-27 打好补丁,
所以本脚本在干净数据上跑就是报 0 命中。**保留它是当回归检查用** ——
哪天 fix_language 又越界把列表符号吃了,先跑这个就能立刻看出来。
"""
import argparse
import json
import re
import sqlite3
import sys

BROKEN = re.compile(r'(?m)^([ \t]*)(\d{1,2})[。．]([ \t])')
COLUMNS = ('solution_latex', 'solution_ja')
JSON_COLUMNS = ('solution_structured', 'hints')


def repair(text):
    return BROKEN.subn(r'\1\2.\3', text or '')


def repair_json(raw):
    if not (raw or '').strip():
        return raw, 0
    try:
        data = json.loads(raw)
    except Exception:
        return raw, 0
    n = [0]

    def walk(node):
        if isinstance(node, str):
            out, k = repair(node)
            n[0] += k
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        return node

    fixed = walk(data)
    return (json.dumps(fixed, ensure_ascii=False) if n[0] else raw), n[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('db')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--show', type=int, default=5)
    args = ap.parse_args()

    con = sqlite3.connect(f'file:{args.db}{"" if args.apply else "?mode=ro"}', uri=True)
    cols = COLUMNS + JSON_COLUMNS
    rows = con.execute('SELECT id, ' + ', '.join(f"COALESCE({c},'')" for c in cols)
                       + ' FROM questions ORDER BY id').fetchall()
    updates, total, touched, shown = [], 0, 0, 0
    for row in rows:
        qid, vals = row[0], list(row[1:])
        new, cnt = [], 0
        for c, v in zip(cols, vals):
            if c in JSON_COLUMNS:
                out, k = repair_json(v)
            else:
                out, k = repair(v)
            cnt += k
            new.append(out)
        if cnt:
            total += cnt
            touched += 1
            updates.append((*new, qid))
            if shown < args.show:
                shown += 1
                m = BROKEN.search(vals[1] or vals[0])
                if m:
                    print(f'  id={qid} ×{cnt}  {m.group(0)!r} → {m.group(1)+m.group(2)+"."+m.group(3)!r}')

    print(f'\n=== 有序列表符号修复:{touched} 道题,共 {total} 处 ===')
    if args.apply:
        con.executemany('UPDATE questions SET ' + ', '.join(f'{c}=?' for c in cols)
                        + ' WHERE id=?', updates)
        con.commit()
        print(f'✓ 已写入 {len(updates)} 道')
    else:
        print('(未写库;加 --apply 才落盘)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
