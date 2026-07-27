#!/usr/bin/env python3
"""把**数学模式里裸露的中日文**用 `\\text{}` 包起来。

数学模式把每个字符当变量排:字形取数学斜体(CJK 没有对应字形,只能退回系统字体)、
字符之间还会插入变量间距。填空题的「ア」「い」这类记号、cases 里的「その他」都属于
文本而非变量,包进 `\\text{}` 才是它们本来的意思,排出来也才与正文一致。

判定用真正的括号配对扫描,而不是正则:
  · 进入 `\\text{ \\mathrm{ \\mbox{ \\textbf{ \\textit{ \\operatorname{` 的花括号 = 文本域;
  · 文本域里再遇到 `$…$` = 又回到数学域;
  · 只有**数学域**里的中日文才包。
`\\begin{cases}` 这类环境名、`\\text` 自身的命令名都不会被误判(命令与其后的 `{` 一起跳过)。

落库前逐处自检:同一趟循环另存一份"不加包裹"的对照串,它必须与原文**逐字相等** ——
除了插进这一对 `\\text{}`,不允许有任何别的改动;对不上就整段放弃改写。
(不能改用正则去脱 `\\text{…}` 来对照:那会把**原本就有**的 `\\text{自己ループ}` 一起脱掉,
于是好端端的一段被误判成"改坏了"。)

用法:
    python scripts/fix_math_text.py <db>            # 只报告
    python scripts/fix_math_text.py <db> --apply    # 写库(先备份)

配对与生命周期:与 scripts/audit_latex.py 成对 —— 那个报告 MathJax 认不出的写法,这个修其中一类。
**不是跑完就作废的一次性脚本**:每批新内容入库后同类问题会再出现。
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter

CJK = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]')
TEXTCMD = re.compile(r'\\(?:text|textbf|textit|textrm|mathrm|mbox|hbox|operatorname\*?)\s*\{')
CMD = re.compile(r'\\[A-Za-z]+\s*')

MATH_BLOCK = re.compile(r'(?<!\\)\$\$[\s\S]*?(?<!\\)\$\$|\\\[[\s\S]*?\\\]')
MATH_INLINE = re.compile(r'(?<!\\)\$(?:\\.|[^$\\\n])+?\$|\\\([\s\S]*?\\\)')
CODE = re.compile(r'```[\s\S]*?```|`[^`\n]*`')

COLUMNS = ('question_latex', 'solution_latex', 'solution_ja')
JSON_COLUMNS = ('solution_structured', 'hints')


def text_mode_mask(math):
    """等长布尔表:True = 该字符位于文本域(已被 \\text{} 之类包住)。"""
    mask = [False] * len(math)
    stack, depth, i = [], 0, 0
    while i < len(math):
        m = TEXTCMD.match(math, i)
        if m:
            for k in range(i, m.end()):
                mask[k] = depth > 0
            stack.append('text')
            depth += 1
            i = m.end()
            continue
        m = CMD.match(math, i)           # 其它控制序列整体跳过,命令名不算内容
        if m:
            for k in range(i, m.end()):
                mask[k] = depth > 0
            i = m.end()
            continue
        ch = math[i]
        if ch == '\\' and i + 1 < len(math):     # \{ \} \$ 等转义
            mask[i] = mask[i + 1] = depth > 0
            i += 2
            continue
        if ch == '{':
            stack.append('plain')
        elif ch == '}':
            if stack and stack.pop() == 'text':
                depth -= 1
        elif ch == '$' and depth > 0:
            j = math.find('$', i + 1)
            j = len(math) - 1 if j == -1 else j
            i = j + 1                    # 内层 $…$ 回到数学域,保持 mask=False
            continue
        mask[i] = depth > 0
        i += 1
    return mask


def wrap_span(span):
    """把一段公式里数学域的中日文连续段包进 \\text{}。

    返回 (新公式, 处理段数, 对照串)。对照串是"把本次加的包裹去掉"的结果 —— 它由
    同一趟循环另存一份原样片段拼成,与原文逐字相等才说明除了这对包裹没动别的。
    不能改用正则脱 `\\text{…}`:那会把**原本就有**的 `\\text{自己ループ}` 一起脱掉,
    于是整段被误判成"改坏了"而放弃改写(这正是 q186 的 `\\xrightarrow{(ア)}` 漏网的原因)。
    """
    mask = text_mode_mask(span)
    out, recon, i, n = [], [], 0, 0
    while i < len(span):
        if CJK.match(span[i]) and not mask[i]:
            j = i
            while j < len(span) and CJK.match(span[j]) and not mask[j]:
                j += 1
            out.append('\\text{' + span[i:j] + '}')
            recon.append(span[i:j])
            n += 1
            i = j
        else:
            out.append(span[i])
            recon.append(span[i])
            i += 1
    return ''.join(out), n, ''.join(recon)


def fix_text(text):
    """只改公式内部;代码段与正文一字不动。"""
    if not (text or '').strip():
        return text, 0
    holes = []

    def stash(m):
        holes.append(m.group(0))
        return '\x00%d\x00' % (len(holes) - 1)

    body = CODE.sub(stash, text)
    count = [0]

    def repl(m):
        new, n, recon = wrap_span(m.group(0))
        if not n:
            return m.group(0)
        if recon != m.group(0):      # 自检不过就整段放弃改写
            return m.group(0)
        count[0] += n
        return new

    # 行间公式先处理并挡掉,再找行内 —— 否则 `$$…\text{$A$ 中の…}…$$` 的内层 $
    # 会被当成一对行内定界符,把本在文本域里的日文误判成裸露。
    blocks = []

    def hide(m):
        blocks.append(repl(m))
        return '\x01%d\x01' % (len(blocks) - 1)

    body = MATH_BLOCK.sub(hide, body)
    body = MATH_INLINE.sub(repl, body)
    for i, b in enumerate(blocks):
        body = body.replace('\x01%d\x01' % i, b)
    for i, h in enumerate(holes):
        body = body.replace('\x00%d\x00' % i, h)
    return body, count[0]


def fix_json(raw, counter):
    if not (raw or '').strip():
        return raw
    try:
        data = json.loads(raw)
    except Exception:
        return raw
    n = [0]

    def walk(node):
        if isinstance(node, str):
            out, k = fix_text(node)
            n[0] += k
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        return node

    fixed = walk(data)
    counter['JSON 列'] += n[0]
    return json.dumps(fixed, ensure_ascii=False) if n[0] else raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('db')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--show', type=int, default=8)
    args = ap.parse_args()

    con = sqlite3.connect(f'file:{args.db}{"" if args.apply else "?mode=ro"}', uri=True)
    cols = COLUMNS + JSON_COLUMNS
    rows = con.execute('SELECT id, ' + ', '.join(f"COALESCE({c},'')" for c in cols)
                       + ' FROM questions ORDER BY id').fetchall()
    counter, updates, shown = Counter(), [], 0
    for row in rows:
        qid, vals, new = row[0], list(row[1:]), []
        hit = 0
        for c, v in zip(cols, vals):
            if c in JSON_COLUMNS:
                before = counter['JSON 列']
                out = fix_json(v, counter)
                hit += counter['JSON 列'] - before
            else:
                out, k = fix_text(v)
                counter[c] += k
                hit += k
            new.append(out)
        if hit:
            updates.append((*new, qid))
            if shown < args.show:
                shown += 1
                print(f'  id={qid} ×{hit}')
    print('\n=== 数学模式里的裸中日文 ===')
    for k, v in sorted(counter.items()):
        print(f'  {k:<22} {v}')
    print(f'  涉及 {len(updates)} 道题')
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
