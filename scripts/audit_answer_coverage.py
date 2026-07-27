#!/usr/bin/env python3
"""小问覆盖盘查:题面问了几问,题解就得答几问。

这是"题解是否对应完整题目"里**机器能判定**的那一半 —— 把题面中的小问编号抽出来,
再看每一轨的题解里有没有出现过。判断力的那一半(答得对不对、答的是不是这一问)
交给逐题审计。

只在"题面里有、某一轨题解里从头到尾一次都没出现"时才报,所以误报主要来自
题解用了别的写法指代同一小问;逐条看一眼即可分辨。

用法:
    python scripts/audit_answer_coverage.py <db 路径>
    python scripts/audit_answer_coverage.py <db 路径> --track ja
"""
import argparse
import re
import sqlite3
import sys

NOTICE = re.compile(r'(転載|掲載しません|公式アーカイブ|原題面)')
MATH = re.compile(r'\$[^$]*\$')
RESTATE = re.compile(r'(?m)^##[ \t]*(?:問題文|問題重述)[ \t]*$')
NEXT_H2 = re.compile(r'(?m)^##[ \t]')

CODE = re.compile(r'```[\s\S]*?```|`[^`\n]*`')
BLOCK_MATH = re.compile(r'\$\$[\s\S]*?\$\$')
INLINE_MATH = re.compile(r'\$(?:\\.|[^$\\\n])+?\$')

# 小问编号只在"结构位置"上算数:行首、列表项开头、或紧跟在 **/加粗标记之后。
# 不加这个限制,句子中间的 $f(1)$、(90) 通 都会被当成编号。
LEAD = r'(?:^|\n)[ \t>*\-]*(?:\*\*)?[ \t]*'
NUM = re.compile(LEAD + r'[（(\[【]\s*(\d{1,2})\s*[)）\]】]')
ROMAN = re.compile(LEAD + r'[（(]\s*(i{1,3}|iv|vi{0,3}|ix|x)\s*[)）]')
KANJI = re.compile(LEAD + r'(?:設問|問)\s*(\d{1,2})')


def stem_labels(text):
    """返回 (顶层数字编号, 次级罗马编号);数学与代码先剔除,否则函数自变量会被当成编号。"""
    t = CODE.sub(' ', text or '')
    t = BLOCK_MATH.sub(' ', t)
    t = INLINE_MATH.sub(' ', t)
    nums, romans = [], []
    for m in NUM.finditer(t):
        n = int(m.group(1))
        if n <= 12 and n not in nums:
            nums.append(n)
    for m in KANJI.finditer(t):
        n = int(m.group(1))
        # 开头的「問9.」是这道大题在原卷里的编号,不是小问 —— 题解自然不会去"答第 9 问"
        if m.start() < 40:
            continue
        if n <= 12 and n not in nums:
            nums.append(n)
    for m in ROMAN.finditer(t):
        r = m.group(1)
        if r and r not in romans:
            romans.append(r)
    return sorted(nums), romans


def stem_of(question_latex, solution_ja):
    """题面文本:优先用 question_latex;它只是转载声明时改用日文轨的問題文段。"""
    q = (question_latex or '').strip()
    if q and not (NOTICE.search(q) and len(re.sub(r'\s', '', MATH.sub('', q))) < 220):
        return q
    m = RESTATE.search(solution_ja or '')
    if not m:
        return q
    rest = solution_ja[m.end():]
    nxt = NEXT_H2.search(rest)
    return rest[:nxt.start()] if nxt else rest


def has_num(n, solution):
    """题解里有没有提到第 n 小问。

    同一件事有很多写法,都算数:
      · `(n)` `[n]` `【n】` `問n` `設問n` `第n问`
      · `(na)` `(1a，b)` —— 中文轨常把 (1) 的 (a)(b)(c) 合起来写成 (1a)(1b)
      · 结构位置上的 `n)` / `**n)**` —— 中文轨列举分小问时的写法
    只认这些**明确带编号**的形式;`### 1 求行列式` 这种标题序号不算,它是解题步骤的
    序号,与小问并非一一对应,认了会把盘查变成永远全绿。
    """
    pats = (
        r'[（(\[【]\s*%d\s*[)）\]】]' % n,
        r'(?:設問|小?問|小?问)\s*%d(?!\d)' % n,                  # 問3 / 小问4 / 问2
        r'第\s*%d\s*[问問題]' % n,
        r'[（(\[【]\s*%d\s*[a-hａ-ｈ]' % n,                       # (1a) / (1a，b)
        r'(?m)^#{2,6}[ \t]*%d[a-hａ-ｈ](?![0-9a-z])' % n,         # ### 1a 频域微分
        r'(?m)^[ \t>*\-]*(?:\*\*)?\s*%d\s*[)）]' % n,            # 2)  /  **2)**
    )
    return any(re.search(p, solution or '') for p in pats)


def has_roman(r, solution):
    return re.search(r'[（(]\s*%s\s*[)）]' % re.escape(r), solution or '') is not None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('db')
    # 默认只查日文轨。中文轨按设计是「速览」,常常不逐一标号而是叙述着把各问答完
    # (id=48 三问全答但一个编号也没写),编号在场与否根本判定不了它答没答 —— 那部分
    # 只能靠逐题审计。日文轨是详解,标号体例稳定,机器查得准。
    ap.add_argument('--track', choices=['zh', 'ja', 'both'], default='ja')
    ap.add_argument('--limit', type=int, default=40)
    args = ap.parse_args()

    con = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    rows = con.execute(
        "SELECT id, COALESCE(source,''), COALESCE(question_latex,''), "
        "COALESCE(solution_latex,''), COALESCE(solution_ja,'') FROM questions ORDER BY id"
    ).fetchall()

    hits, no_label = [], 0
    for qid, source, ql, zh, ja in rows:
        nums, romans = stem_labels(stem_of(ql, ja))
        if not nums and not romans:
            no_label += 1
            continue
        for track, sol, label in (('zh', zh, '中文轨'), ('ja', ja, '日文轨')):
            if args.track not in (track, 'both') or not sol.strip():
                continue
            miss = [f'({n})' for n in nums if not has_num(n, sol)]
            # 中文轨按设计是"速览",不要求逐一列出 (i)(ii) 这一级;日文轨是详解,要求覆盖
            if track == 'ja':
                miss += [f'({r})' for r in romans if not has_roman(r, sol)]
            if miss:
                hits.append((qid, source, label, len(nums) + len(romans), miss))

    print(f'=== 小问覆盖盘查:{len(rows)} 道,其中 {no_label} 道题面没有可识别的小问编号 ===')
    print(f'    题解里找不到对应编号的:{len(hits)} 处\n')
    for qid, source, label, total, missing in hits[:args.limit]:
        print(f'  id={qid:<4} {source[:26]:<28} {label}  题面 {total} 问,缺 {missing}')
    if len(hits) > args.limit:
        print(f'  … 另有 {len(hits) - args.limit} 处')
    return 1 if hits else 0


if __name__ == '__main__':
    sys.exit(main())
