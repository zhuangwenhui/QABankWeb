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

# 小问编号只认**结构位置**上的(行首、列表项开头、加粗标记之后)。
# 句子中间的「条件 (i)–(iii) を満たす」这类列举也算进去,就会把不是设问的当成设问。
LEAD = r'(?:^|\n)[ \t>*\-]*(?:\*\*)?[ \t]*'
SUBQ_PATTERNS = [
    (re.compile(LEAD + r'\((\d)\)'), lambda m: f"({m})"),
    # 要求编号后面跟分隔符,免得把「第1問 2次元平面において」里的「問 2」当成小问
    (re.compile(r'問\s*(\d)(?![0-9])(?=[\s.．、,，)）\]】:：]|$)'), lambda m: f"問{m}"),
    (re.compile(LEAD + r'\((i{1,3}|iv|v)\)'), lambda m: f"({m})"),
    (re.compile(r'([①②③④⑤⑥])'), lambda m: m),
]
# 开头的「問9.」是这道大题在原卷里的编号,不是小问。题解不会去「答第 9 问」,
# 把它当小问数,必然报未覆盖。
OWN_NUMBER = re.compile(r'^\s*問\s*(\d)')
# 收束信号:题解结尾理应有结论/答案
# 收束信号:题解结尾理应有结论段。本库题解用 :::conclusion 容器收尾,
# 也可能直接以展示公式或"答:"结束 —— 这些都算正常收束,不能一律报可疑。
CLOSING = re.compile(r'(:::conclusion|结论|結論|答案|答え|よって|したがって|故答|综上|'
                     r'以上|∎|□|\bQ\.?E\.?D|\$\$[\s\S]{0,400}\$\$\s*$)')
# 结论之后的小节(发展话题或结果一览)。判断是否收束时先把它切掉。
RELATED_SECTION = re.compile(
    r'(?m)^##[ \t]*(?:関連問題|関連題目|相关题目|拓展|まとめ|要点整理|总结)[ \t]*$')
# 转载声明式题面(实质内容在图片里)
NOTICE_ONLY = re.compile(r'(転載|転載条件|掲載しません|公式アーカイブ|原題面)')


CONCLUSION_OPEN = re.compile(r'(?m)^:::conclusion\b')
H2 = re.compile(r'(?m)^##[ \t]')
RESTATE = re.compile(r'(?m)^##[ \t]*(?:問題文|問題重述)[ \t]*$')


def restated_stem(sja):
    """日文轨里的 `## 問題文` 一节(题面再掲);没有则返回空串。"""
    m = RESTATE.search(sja or '')
    if not m:
        return ''
    rest = sja[m.end():]
    nxt = H2.search(rest)
    return rest[:nxt.start()] if nxt else rest


def ends_with_conclusion(text):
    """正文是不是以 `:::conclusion` 那一节收尾。

    只看末尾 260 字的判法,遇到结论本身很长时 `:::conclusion` 那一行会掉出窗口,
    于是被误报成「未收束」(243 条命中都是这么来的)。
    只要最后一个 `:::conclusion` 后面没有别的小标题,那一节就是结尾。
    """
    opens = list(CONCLUSION_OPEN.finditer(text))
    return bool(opens) and not H2.search(text, opens[-1].end())


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
    own = OWN_NUMBER.match(plain)
    if own:
        found.discard(f'問{own.group(1)}')
    return found


def audit(row):
    qid, subject, source, qlatex, qimg, slatex, sja, structured, hints = row
    qlatex, slatex, sja = qlatex or '', slatex or '', sja or ''
    sol = (slatex + '\n' + sja).strip()
    flags = []

    # 1. 题面本身是否只是转载声明
    body = strip_math(qlatex).strip()
    if NOTICE_ONLY.search(qlatex) and len(re.sub(r'\s', '', body)) < 220:
        # 因转载条件登不出原题面的题,本库的体例是在日文轨的 `## 問題文` 里再掲一遍
        # (前端在 question_latex 只有转载声明时,也是拿那一段当题面显示的)。
        # 有再掲就不算「题面缺失」,所以要看到那一层再判。
        # 去掉数学再量,会让以公式为主的题(「放物線 $\dots$ 上に点 $\dots$ をとる」)
        # 显得很短而漏判再掲。这里连公式一起量。
        if len(re.sub(r'\s', '', restated_stem(sja))) >= 60:
            pass
        elif not qimg:
            flags.append('题面缺失:仅转载声明,日文轨也没有题面再掲')
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
        # 本库的体例是「… → :::conclusion → ## 関連問題」。只看末尾 260 字的话
        # 结论会被后面的「関連問題」挤出窗口,所以先把那一节切掉。
        # 中文轨与日文轨是接在一起的,「関連問題」会出现两次。按第一个切会把整条
        # 日文轨都丢掉,所以留到**最后一个**「関連問題」之前。
        parts = RELATED_SECTION.split(sol)
        trimmed = (''.join(parts[:-1]) if len(parts) > 1 else sol).strip() or sol
        tail = trimmed[-260:]
        if not (CLOSING.search(tail) or ends_with_conclusion(trimmed)):
            flags.append('结尾无收束(未见结论/答案类字样)')
        # 末尾的 `:::` 是容器的闭合,不是句子的一部分。把它算进去,凡是按本库体例
        # 用容器收尾的题解就会一律被误报成「被截断」(71 条命中都是这么来的)。
        body_end = re.sub(r'(?:\s*^:::\s*$)+\Z', '', sol.strip(), flags=re.M)
        if re.search(r'[,、,;:]\s*$', body_end):
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
