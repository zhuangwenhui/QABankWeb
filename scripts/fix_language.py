#!/usr/bin/env python3
"""题解语言的**机械修正**:只做规则明确、逐字可复核、不需要判断力的那部分。

需要判断力的(措辞是否严谨、日文是否地道、术语选得对不对)不在这里,交给逐题评审。
这里只处理两类:

  1. 日文轨的结构小标题整套是中文 —— 全库 323 道一模一样:
       問題重述→問題文  思路→方針  分步推導→詳細な導出  関連題目→関連問題
       第一步→第一段階(「步」不是日文用字,日语作「歩」)
  2. 句読点体例 —— 半角标点被当作中日文的句読点使用,以及一篇之内混用多套体例:
       中文轨统一为全角 ,;:!?
       日文轨的 、。 与 ,. 是**两套都对**的体例,故不一刀切:按每篇的多数派统一,
       只有半角一律纠正。
     覆盖四个字段:solution_latex / solution_ja,以及同样是中文正文、同样有这个问题的
     solution_structured(采点结构化)与 hints(渐进提示)—— 后两者存的是 JSON,
     只改字符串值,结构原样不动。

改写只发生在**自然语言区**:数学($…$/$$…$$)、代码、链接、容器标记(:::)、表格行一律屏蔽。

用法:
    python scripts/fix_language.py <db>              # 只报告(默认)
    python scripts/fix_language.py <db> --apply      # 写库(先备份!)
    python scripts/fix_language.py <db> --diff 3     # 抽 3 道看逐行 diff

配对与生命周期:与 scripts/audit_language.py 成对 —— 那个报告问题,这个修。
**不是跑完就作废的一次性脚本**:每批新内容入库后 audit 会重新报同类问题,这里就是解药。
另见 scripts/repair_ordered_lists.py,它修的是本脚本早期版本的越界。
"""
import argparse
import difflib
import json
import re
import sqlite3
import sys
from collections import Counter

# ---------------------------------------------------------------- 屏蔽区

PROTECT = re.compile(
    r'```[\s\S]*?```'            # 围栏代码
    r'|`[^`\n]*`'                # 行内代码
    r'|(?<!\\)\$\$[\s\S]*?(?<!\\)\$\$'   # 行间(内部可嵌 \tag{$\ast$},故不排除 $)
    r'|(?<!\\)\$(?:\\.|[^$\\\n])+?\$'    # 行内(`\$` 是字面美元号,不能当定界符)
    r'|\\\[[\s\S]*?\\\]'
    r'|\\\([\s\S]*?\\\)'
    r'|!?\[[^\]]*\]\([^)]*\)'    # 链接/图片
    r'|https?://\S+'
    r'|^:::.*$'                  # 容器标记行
    r'|^\|.*\|$',                # 表格行(分隔符 :---: 会被误伤)
    re.MULTILINE
)


# 屏蔽区用一个私用区字符占位,而不是把文本切成碎片再逐块处理 —— 后者会把
# 「$v_2$,$v_3$」这种"标点两侧都是公式"的情形整片漏掉(两边都不是汉字)。
# 占位符参与上下文判定,视同一个汉字/日文字符。
SENT = '\ue000'


def on_prose(text, fn):
    """只对自然语言区施加 fn;屏蔽区先换成占位符,处理完再还原。"""
    parts = []

    def grab(m):
        parts.append(m.group(0))
        return SENT
    masked = PROTECT.sub(grab, text)
    done = fn(masked)
    if done.count(SENT) != len(parts):
        raise RuntimeError('屏蔽占位符数量对不上,拒绝改写')
    it = iter(parts)
    return re.sub(SENT, lambda m: next(it), done)


# ---------------------------------------------------------------- 规则

JA_HEADING_MAP = {
    '問題重述': '問題文',
    '思路': '方針',
    '分步推導': '詳細な導出',
    '関連題目': '関連問題',
}
JA_HEADING_RE = re.compile(
    r'(?m)^(#{2,4}[ \t]*)(' + '|'.join(map(re.escape, JA_HEADING_MAP)) + r')([ \t]*)$')
# 「第一步」→「第一段階」:步 在日语里不是这个字(日语作「歩」),而数学文章讲阶段用「段階」
JA_STEP_RE = re.compile(r'第([一二三四五六七八九十百零〇\d]+)步')

ZH_PUNCT_MAP = {',': '，', ';': '；', ':': '：', '!': '！', '?': '？'}
JA_PUNCT_SETS = {',': '，、', '.': '．。'}     # 半角 → 两套全角体例里的对应字符


ORDERED_ITEM = re.compile(r'(?m)^[ \t]*\d{1,2}\.[ \t]')


def real_halfwidth(text, i):
    """这个半角标点是不是**真的**半角用法(不该改成全角)?

    只有这几类:千分位 1,000、小数 0.5、拉丁缩写/文件名 e.g. / foo.txt、时刻 12:30,
    以及 **markdown 有序列表的项目符号**「1. 」—— 它不是句点,改成全角既读着别扭,
    又让 markdown 不再把它当列表渲染。其余出现在中日文行文里的半角标点都是输入法遗留。
    """
    ch = text[i]
    prev = text[i - 1] if i else ''
    nxt = text[i + 1] if i + 1 < len(text) else ''
    if ch in ',.:' and prev.isdigit() and nxt.isdigit():
        return True
    if ch == '.' and prev.isascii() and prev.isalpha() and nxt.isascii() and nxt.isalpha():
        return True
    if ch == '.' and prev.isdigit() and nxt in ' \t':
        line_start = text.rfind('\n', 0, i) + 1
        if ORDERED_ITEM.match(text, line_start):
            return True
    return False


def convert_halfwidth(text, mapping, on_hit):
    """把 text 里该转全角的半角标点按 mapping 转掉;on_hit(ch) 用于计数。"""
    out = []
    for i, ch in enumerate(text):
        if ch in mapping and not real_halfwidth(text, i):
            on_hit(ch)
            out.append(mapping[ch])
        else:
            out.append(ch)
    return ''.join(out)


def ja_dominant_style(text):
    """这一篇用的是哪套全角体例:('、','。') 还是 ('，','．')。半角不计入投票。"""
    kana_style = text.count('、') + text.count('。')
    latin_style = text.count('，') + text.count('．')
    return ('，', '．') if latin_style > kana_style else ('、', '。')


def fix_ja(text):
    counts = Counter()
    comma, period = ja_dominant_style(text)

    out = JA_HEADING_RE.sub(lambda m: m.group(1) + JA_HEADING_MAP[m.group(2)] + m.group(3), text)
    counts['标题'] = len(JA_HEADING_RE.findall(text))

    def steps(s):
        def rep(m):
            counts['第N步'] += 1
            return '第' + m.group(1) + '段階'
        return JA_STEP_RE.sub(rep, s)

    # ①半角 , . 一律转成该篇的主体例;②同一篇混用两套全角时,少数派并入多数派
    mapping = {',': comma, '.': period}
    minority = {c: comma for c in JA_PUNCT_SETS[','] if c != comma}
    minority.update({c: period for c in JA_PUNCT_SETS['.'] if c != period})

    def punct(s):
        s = convert_halfwidth(s, mapping, lambda ch: counts.__setitem__(
            '半角' + ('読点' if ch == ',' else '句点'),
            counts['半角' + ('読点' if ch == ',' else '句点')] + 1))
        if minority:
            def rep(ch):
                counts['统一体例'] += 1
                return minority[ch]
            s = ''.join(rep(ch) if ch in minority else ch for ch in s)
        return s

    return on_prose(out, lambda s: punct(steps(s))), counts


def fix_zh(text):
    counts = Counter()

    def punct(s):
        return convert_halfwidth(s, ZH_PUNCT_MAP,
                                 lambda ch: counts.__setitem__('标点', counts['标点'] + 1))

    return on_prose(text, punct), counts


def fix_zh_json(raw, counts, label):
    """采点结构化(dict)与渐进提示(list)存的是 JSON,正文同样是中文,同样要修标点。

    只改字符串**值**,JSON 结构原样不动;解析不了就整条跳过,不冒险。
    """
    if not (raw or '').strip():
        return raw
    try:
        data = json.loads(raw)
    except Exception:
        counts[label + '·解析失败'] += 1
        return raw

    def walk(node):
        if isinstance(node, str):
            new, c = fix_zh(node)
            counts[label] += c['标点']
            return new
        if isinstance(node, list):
            return [walk(x) for x in node]
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        return node

    fixed = walk(data)
    return json.dumps(fixed, ensure_ascii=False) if fixed != data else raw


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('db')
    ap.add_argument('--apply', action='store_true', help='写库(务必先备份)')
    ap.add_argument('--diff', type=int, default=0, help='打印前 N 道的逐行 diff')
    args = ap.parse_args()

    con = sqlite3.connect(f'file:{args.db}{"" if args.apply else "?mode=ro"}', uri=True)
    rows = con.execute("SELECT id, COALESCE(solution_latex,''), COALESCE(solution_ja,''), "
                       "COALESCE(solution_structured,''), COALESCE(hints,'') "
                       "FROM questions ORDER BY id").fetchall()

    total = Counter()
    touched_zh = touched_ja = 0
    shown = 0
    updates = []
    for qid, zh, ja, structured, hints in rows:
        new_zh, czh = fix_zh(zh)
        new_ja, cja = (fix_ja(ja) if ja.strip() else (ja, Counter()))
        new_st = fix_zh_json(structured, total, '采点结构化·标点')
        new_hi = fix_zh_json(hints, total, '渐进提示·标点')
        for k, v in czh.items():
            total['中文轨·' + k] += v
        for k, v in cja.items():
            total['日文轨·' + k] += v
        if new_zh != zh:
            touched_zh += 1
        if new_ja != ja:
            touched_ja += 1
        if (new_zh, new_ja, new_st, new_hi) != (zh, ja, structured, hints):
            updates.append((new_zh, new_ja, new_st, new_hi, qid))
            if shown < args.diff:
                shown += 1
                for label, old, new in (('中文轨', zh, new_zh), ('日文轨', ja, new_ja)):
                    if old == new:
                        continue
                    print(f'\n────── id={qid} {label} ──────')
                    d = list(difflib.unified_diff(old.split('\n'), new.split('\n'),
                                                  lineterm='', n=0))
                    for line in d[2:22]:
                        print('  ' + line)

    print('\n=== 机械修正统计 ===')
    for k, v in sorted(total.items()):
        print(f'  {k:<16} {v}')
    print(f'  中文轨改动 {touched_zh} 道 / 日文轨改动 {touched_ja} 道')

    if args.apply:
        con.executemany("UPDATE questions SET solution_latex=?, solution_ja=?, "
                        "solution_structured=?, hints=? WHERE id=?", updates)
        con.commit()
        print(f'✓ 已写入 {len(updates)} 道')
    else:
        print('(未写库;加 --apply 才落盘)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
