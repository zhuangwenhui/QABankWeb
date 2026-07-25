#!/usr/bin/env python3
"""题解完整性盘查:题解是否覆盖了题目的全部小问,以及是否有被截断的迹象。

背景:题面多来自 PDF 截图,跨页会把题目截断;题解由模型逐题生成,若它只看到半道题,
产出的题解就只解了前半部分,而这一点从列表页完全看不出来。

判据(都只是"可疑"信号,最终仍需人工过目,故输出为待批阅清单):
  1. 小问覆盖:题面里出现的小问编号((1)(2)… / 問1 / (i)(ii))是否都在题解里出现
  2. 突然结束:题解结尾不是收束段落(无结论/答案/最后一小问),或以逗号、连接词收尾
  3. 体量失衡:题解显著短于题面,或短到不足以解一道院试题
  4. 结构缺失:没有采点四段(solution_structured),或双轨只剩一轨
  5. 题面缺失:question_latex 只是转载声明而无实质内容,且没有题面图片

用法:
    python scripts/audit_solution_completeness.py <db 路径> [--json 输出.json]
"""
import argparse
import json
import re
import sqlite3
import sys

# 小问编号的几种写法:(1) (i) 問1 問(1) [1] ①
SUBQ_PATTERNS = [
    (re.compile(r'(?<![0-9A-Za-z])\((\d)\)'), lambda m: f"({m})"),
    (re.compile(r'問\s*(\d)'), lambda m: f"問{m}"),
    (re.compile(r'(?<![0-9A-Za-z])\((i{1,3}|iv|v)\)'), lambda m: f"({m})"),
    (re.compile(r'([①②③④⑤⑥])'), lambda m: m),
]
# 收束信号:题解结尾理应有结论/答案
# 收束信号:题解结尾理应有结论段。本库题解用 :::conclusion 容器收尾,
# 也可能直接以展示公式或"答:"结束 —— 这些都算正常收束,不能一律报可疑。
CLOSING = re.compile(r'(:::conclusion|结论|結論|答案|答え|よって|したがって|故答|综上|'
                     r'以上|∎|□|\bQ\.?E\.?D|\$\$[\s\S]{0,400}\$\$\s*$)')
# 转载声明式题面(实质内容在图片里)
NOTICE_ONLY = re.compile(r'(転載|転載条件|掲載しません|公式アーカイブ|原題面)')


def strip_math(s):
    s = re.sub(r'\$\$[\s\S]+?\$\$', ' ', s)
    s = re.sub(r'\$(?:\\.|[^$\\\n])+?\$', ' ', s)
    return s


def subquestions(text):
    """题面中出现的小问标号集合(在去掉数学后的文本上找,避免把下标当小问)。"""
    plain = strip_math(text)
    found = set()
    for pat, fmt in SUBQ_PATTERNS:
        for m in pat.findall(plain):
            found.add(fmt(m) if callable(fmt) else m)
    # (1) 之类必须成序列出现才算真小问:只出现 (3) 而没有 (1)(2) 多半是引用
    nums = sorted(int(x[1]) for x in found if re.fullmatch(r'\(\d\)', x))
    if nums and nums[0] != 1:
        found = {x for x in found if not re.fullmatch(r'\(\d\)', x)}
    return found


def audit(row):
    qid, subject, source, qlatex, qimg, slatex, sja, structured, hints = row
    qlatex, slatex, sja = qlatex or '', slatex or '', sja or ''
    sol = (slatex + '\n' + sja).strip()
    flags = []

    # 1. 题面本身是否只是转载声明
    body = strip_math(qlatex).strip()
    if NOTICE_ONLY.search(qlatex) and len(re.sub(r'\s', '', body)) < 220:
        if not qimg:
            flags.append('题面缺失:仅转载声明且无题面图片')
        else:
            flags.append('题面在图片里:文字仅转载声明(无法自动核对小问)')

    # 2. 小问覆盖
    subs = subquestions(qlatex)
    if subs:
        missing = sorted(s for s in subs if s not in sol)
        if missing:
            flags.append(f'题解未覆盖小问 {" ".join(missing)}(题面共 {len(subs)} 问)')

    # 3. 题解是否存在
    if not sol:
        flags.append('无任何文字题解')
    else:
        tail = sol[-260:]
        if not CLOSING.search(tail):
            flags.append('结尾无收束(未见结论/答案类字样)')
        if re.search(r'[,、,;:]\s*$', sol.strip()):
            flags.append('题解以标点悬空结尾(疑似被截断)')
        # 4. 体量
        n_sol = len(re.sub(r'\s', '', strip_math(sol)))
        n_q = len(re.sub(r'\s', '', body))
        if n_sol < 200:
            flags.append(f'题解过短({n_sol} 字)')
        elif n_q > 200 and n_sol < n_q * 0.6:
            flags.append(f'题解显著短于题面({n_sol} vs {n_q} 字)')

    # 5. 双轨与结构化
    if slatex and not sja:
        flags.append('缺日文轨题解')
    if sja and not slatex:
        flags.append('缺中文轨题解')
    if not structured:
        flags.append('无采点结构化四段')
    if not hints:
        flags.append('无渐进提示')

    return flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('db')
    ap.add_argument('--json')
    args = ap.parse_args()

    con = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    rows = con.execute(
        "SELECT id, subject, COALESCE(source,''), COALESCE(question_latex,''), "
        "COALESCE(question_image,''), COALESCE(solution_latex,''), COALESCE(solution_ja,''), "
        "COALESCE(solution_structured,''), COALESCE(hints,'') FROM questions ORDER BY id"
    ).fetchall()

    report, tally = [], {}
    for r in rows:
        flags = audit(r)
        if flags:
            report.append({'id': r[0], 'source': r[2], 'flags': flags})
            for f in flags:
                key = f.split('(')[0].split(':')[0].strip()
                tally[key] = tally.get(key, 0) + 1

    print(f"题目 {len(rows)} 道;有可疑信号 {len(report)} 道\n")
    print("按信号归类:")
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {v:>4}  {k}")

    severe = [r for r in report
              if any(f.startswith(('题解未覆盖小问', '无任何文字题解', '题面缺失',
                                   '题解以标点悬空结尾', '题解过短')) for f in r['flags'])]
    by_kind = {}
    for r in report:
        for f in r['flags']:
            by_kind.setdefault(f.split('(')[0].split(':')[0].strip(), []).append(r['id'])
    print(f"\n需优先人工过目({len(severe)} 道):")
    for r in severe[:40]:
        print(f"  id={r['id']:<4} {r['source'][:34]:<34} {'; '.join(r['flags'])[:96]}")
    if len(severe) > 40:
        print(f"  … 还有 {len(severe) - 40} 道,完整清单见 --json")

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f"\n完整清单已写入 {args.json}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
