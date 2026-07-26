#!/usr/bin/env python3
"""把逐题语言评审产出的**替换补丁**落到题库,并在落库前做机械校验。

补丁是 (old, new) 精确替换对,而不是整篇重写 —— 整篇重写会让公式、结构、编号在不知不觉
中漂移,且无法逐条复核。这里的校验就是围绕这一点:

  · old 必须在原文中**恰好出现一次**(否则改的位置不确定,拒绝);
  · 除非补丁自己声明 math=true,否则改完之后**全部数学片段必须逐字不变**;
  · `## ` 小标题条数、`:::` 容器标记条数不得变化(结构不能被顺手改掉)。

任何一条不过,该补丁被拒并打印原因;同一道题的其余补丁照常应用。

用法:
    python scripts/apply_language_patches.py <db> <补丁目录>            # 只试算
    python scripts/apply_language_patches.py <db> <补丁目录> --apply    # 写库(先备份)
"""
import argparse
import glob
import json
import os
import re
import sqlite3
import sys
from collections import Counter

# `\$` 是字面美元号,不是定界符;不认转义会在错的位置配对,校验因此形同虚设
MATH = re.compile(r'(?<!\\)\$\$[\s\S]*?(?<!\\)\$\$|(?<!\\)\$(?:\\.|[^$\\\n])+?\$'
                  r'|```[\s\S]*?```|`[^`\n]*`')
H2 = re.compile(r'(?m)^#{2,4}[ \t]')
FENCE = re.compile(r'(?m)^:::')

# stem = question_latex。改题面要慎之又慎:它是入试原题的转写,"修正"它就可能变成另一道题。
# 只有当出错的那段本身是**录题者自撰的内容**(如照图整理的边表)时才允许改,且必须逐条复核。
COLUMN = {'zh': 'solution_latex', 'ja': 'solution_ja',
          'struct': 'solution_structured', 'hints': 'hints',
          'stem': 'question_latex'}
JSON_TRACKS = {'struct', 'hints'}   # 这两列存的是 JSON,只能改字符串**值**,不能碰结构


def json_replace(raw, old, new):
    """在 JSON 的字符串值里做一次替换。命中次数不等于 1 就返回 None(由调用方拒绝)。"""
    data = json.loads(raw)
    hits = [0]

    def walk(node):
        if isinstance(node, str):
            n = node.count(old)
            hits[0] += n
            return node.replace(old, new, 1) if n else node
        if isinstance(node, list):
            return [walk(x) for x in node]
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        return node

    out = walk(data)
    return (json.dumps(out, ensure_ascii=False), hits[0])


def structure_signature(text):
    return (Counter(MATH.findall(text)), len(H2.findall(text)), len(FENCE.findall(text)))


def apply_one(text, patches, qid, track, rejects):
    """逐条应用;返回新文本。被拒的补丁记入 rejects。"""
    out = text
    for i, p in enumerate(patches):
        old, new = p.get('old', ''), p.get('new', '')
        tag = f'{track}/q{qid}#{i}'
        if not old or old == new:
            rejects.append((tag, 'old 为空或与 new 相同'))
            continue
        if track in JSON_TRACKS:
            try:
                cand, n = json_replace(out, old, new)
            except Exception as e:
                rejects.append((tag, f'JSON 字段改写失败:{e}'))
                continue
            if n != 1:
                rejects.append((tag, f'old 在原文中出现 {n} 次(必须恰好 1 次):{old[:60]!r}'))
                continue
            out = cand
            continue
        n = out.count(old)
        if n != 1:
            rejects.append((tag, f'old 在原文中出现 {n} 次(必须恰好 1 次):{old[:60]!r}'))
            continue
        cand = out.replace(old, new, 1)
        if not p.get('math'):
            if structure_signature(cand)[0] != structure_signature(out)[0]:
                rejects.append((tag, f'未声明 math=true 却改动了公式:{old[:60]!r}'))
                continue
        before, after = structure_signature(out), structure_signature(cand)
        if before[1:] != after[1:]:
            rejects.append((tag, f'改动了标题/容器结构:{old[:60]!r}'))
            continue
        out = cand
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('db')
    ap.add_argument('patch_dir')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--show', type=int, default=6, help='打印前 N 条改动示例')
    args = ap.parse_args()

    con = sqlite3.connect(f'file:{args.db}{"" if args.apply else "?mode=ro"}', uri=True)
    files = sorted(glob.glob(os.path.join(args.patch_dir, '*.json')))
    rejects, applied, touched = [], 0, {}
    shown = 0

    for path in files:
        try:
            data = json.load(open(path, encoding='utf-8'))
        except Exception as e:
            rejects.append((os.path.basename(path), f'JSON 解析失败:{e}'))
            continue
        for entry in (data if isinstance(data, list) else [data]):
            qid, track = entry.get('id'), entry.get('track')
            patches = entry.get('patches') or []
            if track not in COLUMN or not isinstance(qid, int) or not patches:
                if patches:
                    rejects.append((os.path.basename(path), f'id/track 不合法:{qid}/{track}'))
                continue
            key = (qid, track)
            cur = touched.get(key)
            if cur is None:
                row = con.execute(
                    f'SELECT COALESCE({COLUMN[track]}, "") FROM questions WHERE id=?',
                    (qid,)).fetchone()
                if not row:
                    rejects.append((f'{track}/q{qid}', '题目不存在'))
                    continue
                cur = row[0]
            new = apply_one(cur, patches, qid, track, rejects)
            if new != cur:
                if shown < args.show:
                    for p in patches[:2]:
                        if p.get('old') and p['old'] in cur:
                            shown += 1
                            print(f"── {track} id={qid}: {p.get('why', '')[:60]}")
                            print(f"   - {p['old'][:90]!r}")
                            print(f"   + {p['new'][:90]!r}")
                touched[key] = new
                applied += 1

    print(f'\n=== 补丁文件 {len(files)} 个;实际改动 {len(touched)} 处(题×轨);'
          f'被拒 {len(rejects)} 条 ===')
    by_reason = Counter(r.split(':')[0] for _t, r in rejects)
    for reason, n in by_reason.most_common():
        print(f'  拒绝 {n:>4}  {reason}')
    for tag, reason in rejects[:12]:
        print(f'    · {tag}  {reason[:110]}')

    if args.apply:
        for (qid, track), text in touched.items():
            con.execute(f'UPDATE questions SET {COLUMN[track]}=? WHERE id=?', (text, qid))
        con.commit()
        print(f'✓ 已写入 {len(touched)} 处')
    else:
        print('(未写库;加 --apply 才落盘)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
