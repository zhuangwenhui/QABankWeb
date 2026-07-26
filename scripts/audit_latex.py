#!/usr/bin/env python3
"""LaTeX 可渲染性盘查:找出 MathJax 认不出的环境/宏。

MathJax 只实现了 TeX 的一个子集。内容里一旦出现它不认的东西(例如 mathtools 的
`psmallmatrix`),页面上就会出现一个刺眼的红色报错框 —— 而这在服务端完全看不出来。

用法:
    python scripts/audit_latex.py <db 路径>          # 只报告
    python scripts/audit_latex.py <db 路径> --fix    # 顺手把已知可安全替换的写法改掉
"""
import argparse
import re
import sqlite3
import sys

FIELDS = ('question_latex', 'solution_latex', 'solution_ja',
          'solution_structured', 'hints')

# MathJax(tex-svg + ams + boldsymbol)支持的环境。不在表里的会渲染成红色报错框。
KNOWN_ENVS = {
    'align', 'align*', 'aligned', 'alignat', 'alignat*', 'alignedat',
    'array', 'Bmatrix', 'bmatrix', 'cases', 'CD', 'eqnarray', 'eqnarray*',
    'equation', 'equation*', 'gather', 'gather*', 'gathered', 'matrix',
    'multline', 'multline*', 'pmatrix', 'smallmatrix', 'split', 'subarray',
    'Vmatrix', 'vmatrix', 'rcases', 'dcases', 'darray', 'dcases*',
}

# 已知可安全等价替换的写法(mathtools 扩展 → MathJax 自带写法)
SAFE_REWRITES = [
    (re.compile(r'\\begin\{psmallmatrix\}([\s\S]*?)\\end\{psmallmatrix\}'),
     r'\\left(\\begin{smallmatrix}\1\\end{smallmatrix}\\right)'),
    (re.compile(r'\\begin\{bsmallmatrix\}([\s\S]*?)\\end\{bsmallmatrix\}'),
     r'\\left[\\begin{smallmatrix}\1\\end{smallmatrix}\\right]'),
    (re.compile(r'\\begin\{vsmallmatrix\}([\s\S]*?)\\end\{vsmallmatrix\}'),
     r'\\left|\\begin{smallmatrix}\1\\end{smallmatrix}\\right|'),
]

ENV_RE = re.compile(r'\\begin\{([A-Za-z*]+)\}')


def scan(con):
    hits = {}
    for row in con.execute(
            "SELECT id, COALESCE(source,''), " + ', '.join(
                f"COALESCE({f},'')" for f in FIELDS) + " FROM questions ORDER BY id"):
        qid, source = row[0], row[1]
        text = '\n'.join(row[2:])
        for env in set(ENV_RE.findall(text)):
            if env not in KNOWN_ENVS:
                hits.setdefault(env, []).append((qid, source))
    return hits


def fix(con, path):
    changed = 0
    rows = con.execute(
        "SELECT id, " + ', '.join(f"COALESCE({f},'')" for f in FIELDS)
        + " FROM questions").fetchall()
    for row in rows:
        qid, values = row[0], list(row[1:])
        new = []
        touched = False
        for v in values:
            out = v
            for pat, rep in SAFE_REWRITES:
                out = pat.sub(rep, out)
            touched = touched or (out != v)
            new.append(out)
        if touched:
            con.execute(
                "UPDATE questions SET " + ', '.join(f"{f}=?" for f in FIELDS)
                + " WHERE id=?", (*new, qid))
            changed += 1
    con.commit()
    print(f"已改写 {changed} 道题({path})")
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('db')
    ap.add_argument('--fix', action='store_true', help='应用已知安全替换(会写库,先备份)')
    args = ap.parse_args()

    mode = '' if args.fix else '?mode=ro'
    con = sqlite3.connect(f'file:{args.db}{mode}', uri=True)

    hits = scan(con)
    if not hits:
        print('✓ 未发现 MathJax 不认的环境')
    else:
        print(f'发现 {len(hits)} 种 MathJax 不认的环境:')
        for env, rows in sorted(hits.items(), key=lambda kv: -len(kv[1])):
            fixable = any(env in pat.pattern for pat, _ in SAFE_REWRITES)
            print(f"  \\begin{{{env}}}  {len(rows)} 道 {'(有安全替换)' if fixable else '(需人工)'}")
            for qid, src in rows[:6]:
                print(f"      id={qid:<4} {src[:44]}")

    if args.fix:
        fix(con, args.db)
        left = scan(con)
        print('改写后仍不认的环境:', sorted(left) or '无')
        return 1 if left else 0
    return 1 if hits else 0


if __name__ == '__main__':
    sys.exit(main())
