#!/usr/bin/env python3
"""题解语言盘查:中文轨与日文轨各按各自的标准做**机器可判定**的全量检查。

两轨标准本就不同:
  · 中文轨 —— 正文必须是正统、严谨的数学汉语;`## 思路` 段允许通俗形象的比喻,不按正文标准苛求。
  · 日文轨 —— **全篇**都必须是地道且严谨的日语,术语必须是该学科的日语专业名词。

本脚本只管"机器能判定"的那部分:混入他语的字词、术语对照、标点体例、数学记法。
判断力的部分(措辞是否严谨、比喻是否得当、有无冗词)交给 LLM 评审那一步,
本脚本顺带产出它要吃的 JSON。

跨语言字符判定用标准字符集,不依赖任何第三方库:
    仅 GB2312 能编码 → 简体中文专有字(出现在日文轨即为缺陷)
    仅 Shift_JIS 能编码 → 日文/旧字体专有字(出现在中文轨即为缺陷)

用法:
    python scripts/audit_language.py <db 路径>                  # 人读报告
    python scripts/audit_language.py <db 路径> --json out.json   # 逐题清单(供 LLM 评审)
    python scripts/audit_language.py <db 路径> --rule ja-cn-word --limit 40
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict

# ---------------------------------------------------------------- 文本切分

MATH_BLOCK = re.compile(r'\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]')
MATH_INLINE = re.compile(r'\$[^$\n]*?\$|\\\([\s\S]*?\\\)')
CODE = re.compile(r'```[\s\S]*?```|`[^`\n]*`')
LINK = re.compile(r'!?\[[^\]]*\]\([^)]*\)|https?://\S+')
HEADING = re.compile(r'(?m)^(#{2,6})[ \t]*(.+?)[ \t]*$')

CJK = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
KANA = re.compile(r'[\u3040-\u309f\u30a0-\u30fa\u30fc]')     # 不含 ・(U+30FB),它两语通用
CJK_OR_KANA = r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]'


def strip_noise(text):
    """去掉数学/代码/链接,只留自然语言;用等长空白替换以保留偏移。"""
    def blank(m):
        return ' ' * len(m.group(0))
    out = CODE.sub(blank, text or '')
    out = MATH_BLOCK.sub(blank, out)
    out = MATH_INLINE.sub(blank, out)
    return LINK.sub(blank, out)


def math_spans(text):
    body = CODE.sub(lambda m: ' ' * len(m.group(0)), text or '')
    return [m.group(0) for m in MATH_BLOCK.finditer(body)] + \
           [m.group(0) for m in MATH_INLINE.finditer(body)]


def sections(text):
    """按 `## 标题` 切段,返回 [(标题, 正文)];标题前的引言归到 '' 段。"""
    src = text or ''
    marks = [(m.start(), m.end(), m.group(2)) for m in HEADING.finditer(src)
             if len(m.group(1)) == 2]
    if not marks:
        return [('', src)]
    out = []
    if marks[0][0] > 0:
        out.append(('', src[:marks[0][0]]))
    for i, (_s, e, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(src)
        out.append((title, src[e:end]))
    return out


# 中文轨里允许通俗表达的段落(用户明确豁免的引导部分)
ZH_CASUAL_SECTIONS = ('思路',)


def snippet(text, start, end, w=22):
    return text[max(0, start - w):end + w].replace('\n', '⏎').strip()


def _encodable(ch, codec):
    try:
        ch.encode(codec)
        return True
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False


_CACHE = {}


def script_of(ch):
    """'cn' = 简体专有,'ja' = 日文/旧字体专有,'both' = 两语通用。"""
    if ch not in _CACHE:
        g, s = _encodable(ch, 'gb2312'), _encodable(ch, 'shift_jis')
        _CACHE[ch] = 'cn' if (g and not s) else ('ja' if (s and not g) else 'both')
    return _CACHE[ch]


# ---------------------------------------------------------------- 词表

# 全库统一套用的中文小标题 —— 日文轨里最扎眼的一类,机械可改
JA_HEADINGS = {
    '問題重述': '問題文', '思路': '方針', '分步推導': '段階的な導出',
    '関連題目': '関連問題', '関連問題': None,
}
JA_STEP = re.compile(r'第([一二三四五六七八九十]+)步')

# 日文轨里的中文措辞 → 该学科的日语正词。只收"整词命中即为错"的,
# 像「域」(定義域/値域/整域 均合法)这类会误伤的一律不收。
CN_WORDS_IN_JA = {
    '推導': '導出', '題目': '問題', '步驟': '手順', '重述': '再掲',
    '矩阵': '行列', '矩陣': '行列', '向量': 'ベクトル',
    '特征值': '固有値', '特徵值': '固有値', '特征向量': '固有ベクトル',
    '映射': '写像', '单射': '単射', '满射': '全射', '双射': '全単射',
    '收敛': '収束', '一致収束': '一様収束', '导数': '導関数', '導数': '導関数',
    '积分': '積分', '极限': '極限', '概率': '確率', '期望': '期待値',
    '方程组': '連立方程式', '连续': '連続',
    '可微': '微分可能', '可积': '積分可能', '可導': '微分可能',
    '反函数': '逆関数', '複合関数': '合成関数', '正交': '直交',
    '转置': '転置', '逆矩阵': '逆行列', '内积': '内積', '范数': 'ノルム',
    '维数': '次元', '线性': '線形', '線性': '線形',
    '无穷': '無限', '無窮': '無限', '邻域': '近傍', '鄰域': '近傍',
    '递归': '再帰', '遞迴': '再帰', '复杂度': '計算量', '時間複雑度': '時間計算量',
    '队列': 'キュー', '顶点': '頂点', '迹': '跡',
    '素域': '素体', '有限域': '有限体', '扩域': '拡大体',
    '因为': 'なぜならば', '所以': 'よって', '可以': '〜できる',
    '这个': 'この', '那个': 'その', '我们': '(主語を省く)',
    '但是': 'しかし', '如果': 'もし', '因此': 'したがって',
}

# 中文轨里的日语措辞 → 中文正词
JA_WORDS_IN_ZH = {
    '固有値': '特征值', '固有ベクトル': '特征向量', '固有多項式': '特征多项式',
    '収束': '收敛', '一様収束': '一致收敛',
    '関数': '函数', '逆関数': '反函数', '合成関数': '复合函数',
    '線形': '线性', '写像': '映射', '階数': '秩', '転置': '转置', '逆行列': '逆矩阵',
    '積分': '积分', '導関数': '导数', '極限': '极限', '極大': '极大', '極小': '极小',
    '確率': '概率', '期待値': '期望', '棄却': '拒绝', '設問': '小问',
    '単射': '单射', '全射': '满射', '全単射': '双射',
    '方程式': '方程', '連立方程式': '方程组', '連続': '连续',
    '微分可能': '可微', '積分可能': '可积', '近傍': '邻域', '無限': '无穷',
    '次元': '维数', '直交': '正交', '内積': '内积',
    '再帰': '递归', '計算量': '复杂度', '頂点': '顶点', '対角化': '对角化',
    '行列': '矩阵',
}
# 「行列式」在中文里完全正当,不能算作「行列」的日文残留
JA_WORD_GUARD = {'行列': ('行列式',)}

# ---------------------------------------------------------------- 数学记法

MATHBB_WRAP = re.compile(r'\\math(?:bb|bf|cal|rm|scr|frak)\s*\{\s*[RNZQC]\s*\}')
BARE_SET = re.compile(r'\\(?:in|notin|subset|subseteq|supset|supseteq|to|times|colon)\s*'
                      r'(?![\\{])([RNZQC])(?![A-Za-z])')
BARE_OPS = re.compile(r'(?<![\\A-Za-z])(sin|cos|tan|cot|sec|csc|log|ln|exp|lim|max|min|sup|inf|'
                      r'det|dim|ker|deg|gcd|arg|rank|tr|mod)(?![A-Za-z])')
OP_NEEDS_OPERATORNAME = {'rank', 'tr'}     # MathJax 无同名宏,不加 \operatorname 会排成变量连乘
WRAPPED = re.compile(r'\\(?:operatorname\*?|mathrm|text|mathop)\s*\{[^{}]*$')
ASCII_REL = re.compile(r'(?<![<>!=\\])(<=|>=|!=|=<)(?![<>=])')
ASCII_ARROW = re.compile(r'(?<![<\-=\\])(->|=>)(?![>])')
CJK_IN_MATH = re.compile(CJK_OR_KANA)
TEXTISH = re.compile(r'\\(?:text|mathrm|mbox|textbf|textit|operatorname\*?|hbox)\s*\{[^{}]*\}')

# ---------------------------------------------------------------- 标点

ZH_HALF_PUNCT = re.compile(r'(?:[\u4e00-\u9fff][,;:!?](?=[\u4e00-\u9fff\s])'
                           r'|[,;:!?][\u4e00-\u9fff])')
JA_COMMA_STYLES = {'、': '、。(かな体)', '，': '，．(全角ラテン体)', ',': ',.(半角)'}
JA_PERIOD_STYLES = {'。': '、。(かな体)', '．': '，．(全角ラテン体)', '.': ',.(半角)'}
CN_QUOTE = re.compile(r'[“”‘’]')

DESU_MASU = re.compile(r'(?:です|ます|ました|ません|でした)(?=[。.．,、，\n]|$)')
DEARU = re.compile(r'(?:である|であり|だ)(?=[。.．,、，\n]|$)')


# ---------------------------------------------------------------- 规则

def check_ja(text):
    hits = []
    plain = strip_noise(text)

    # 1. 结构小标题用的是中文
    heads = []
    for m in HEADING.finditer(text or ''):
        t = m.group(2).strip()
        if t in JA_HEADINGS and JA_HEADINGS[t]:
            heads.append(f'{t}→{JA_HEADINGS[t]}')
    steps = JA_STEP.findall(text or '')
    if heads or steps:
        ev = ';'.join(heads)
        if steps:
            ev += (';' if ev else '') + f'第N步×{len(steps)}→第N段階/ステップN(「步」は日本語の字ではない)'
        hits.append(('ja-heading-cn', '日文轨的结构小标题写的是中文', ev))

    # 2. 简体中文专有字
    bad = Counter(ch for ch in CJK.findall(plain) if script_of(ch) == 'cn')
    if bad:
        m = re.search('[' + ''.join(bad) + ']', plain)
        hits.append(('ja-cn-char', '日文正文里混入简体中文专有字',
                     ' '.join(f'{c}×{n}' for c, n in bad.most_common(10))
                     + (' | ' + snippet(plain, m.start(), m.end()) if m else '')))

    # 3. 中文措辞/非日语术语
    words = []
    for w, good in CN_WORDS_IN_JA.items():
        n = plain.count(w)
        if n:
            words.append(f'{w}×{n}→{good}')
    if words:
        hits.append(('ja-cn-word', '日文正文里使用中文措辞/非日语术语', ';'.join(words[:12])))

    # 4. 引号
    if CN_QUOTE.search(plain):
        hits.append(('ja-quote', '用了中文引号,日语应为「」',
                     ''.join(sorted(set(CN_QUOTE.findall(plain))))))

    # 5. 句读体例:同一篇里混用两种以上逗号/句点体例
    commas = Counter(ch for ch in plain if ch in JA_COMMA_STYLES)
    periods = Counter(ch for ch in plain if ch in JA_PERIOD_STYLES)
    # ASCII 的 , . 只有紧贴日文字符时才算句读(否则多半是 (1), (2) 或小数)
    for ch, pat in ((',', r'%s\s*,' % CJK_OR_KANA), ('.', r'%s\s*\.' % CJK_OR_KANA)):
        n = len(re.findall(pat, plain))
        if ch in commas:
            commas[ch] = n
        if ch in periods:
            periods[ch] = n
    commas = {k: v for k, v in commas.items() if v}
    periods = {k: v for k, v in periods.items() if v}
    if len(commas) > 1 or len(periods) > 1:
        hits.append(('ja-punct-mix', '同一篇里混用多种句読点体例',
                     '読点 ' + ' '.join(f'{k}×{v}' for k, v in commas.items())
                     + ' / 句点 ' + ' '.join(f'{k}×{v}' for k, v in periods.items())))
    elif commas.get(',') or periods.get('.'):
        hits.append(('ja-punct-ascii', '日文句読点用了半角 , . (日文字后应为「、。」或「,.」全角)',
                     f"读点 ,×{commas.get(',', 0)} / 句点 .×{periods.get('.', 0)}"))

    # 6. 文体
    desu, dearu = len(DESU_MASU.findall(plain)), len(DEARU.findall(plain))
    if desu and dearu:
        hits.append(('ja-style-mix', '敬体(です・ます)与常体(である)混用;数学の論述は常体に統一すべき',
                     f'です・ます×{desu} / である×{dearu}'))
    elif desu:
        hits.append(('ja-style-desumasu', '通篇敬体;数学の論述は常体(である体)が標準',
                     f'です・ます×{desu}'))
    return hits


def check_zh(text):
    hits = []
    for title, body in sections(text):
        strict = not any(k in title for k in ZH_CASUAL_SECTIONS)
        plain = strip_noise(body)
        where = f'[{title or "开头"}]'

        bad = Counter(ch for ch in CJK.findall(plain) if script_of(ch) == 'ja')
        if bad:
            m = re.search('[' + ''.join(bad) + ']', plain)
            hits.append(('zh-ja-char', f'{where} 中文正文里混入日文/旧字体专有字',
                         ' '.join(f'{c}×{n}' for c, n in bad.most_common(10))
                         + (' | ' + snippet(plain, m.start(), m.end()) if m else '')))

        m = KANA.search(plain)
        if m:
            n = len(KANA.findall(plain))
            hits.append(('zh-kana', f'{where} 中文正文里出现假名',
                         f'×{n} | ' + snippet(plain, m.start(), m.end())))

        words = []
        for w, good in JA_WORDS_IN_ZH.items():
            n = plain.count(w)
            for guard in JA_WORD_GUARD.get(w, ()):
                n -= plain.count(guard)
            if n > 0:
                words.append(f'{w}×{n}→{good}')
        if words:
            hits.append(('zh-ja-word', f'{where} 中文正文里使用日语术语', ';'.join(words[:12])))

        if strict:
            found = ZH_HALF_PUNCT.findall(plain)
            if found:
                m = ZH_HALF_PUNCT.search(plain)
                hits.append(('zh-punct-half', f'{where} 中文句子里用了半角标点(应为,;:!?)',
                             f'×{len(found)} | ' + snippet(plain, m.start(), m.end())))
    return hits


def check_math(text, track):
    hits = []
    spans = math_spans(text)
    if not spans:
        return hits
    bare_sets, bare_ops, ascii_rel, ascii_arrow, cjk_raw = [], Counter(), set(), set(), []
    for s in spans:
        inner = s.strip('$').strip()
        masked = MATHBB_WRAP.sub(lambda m: ' ' * len(m.group(0)), inner)
        for m in BARE_SET.finditer(masked):
            bare_sets.append(m.group(0).strip())
        for m in BARE_OPS.finditer(inner):
            if WRAPPED.search(inner[max(0, m.start() - 20):m.start()]):
                continue
            bare_ops[m.group(1)] += 1
        ascii_rel |= set(ASCII_REL.findall(inner))
        ascii_arrow |= set(ASCII_ARROW.findall(inner))
        stripped = TEXTISH.sub(' ', inner)
        if CJK_IN_MATH.search(stripped):
            cjk_raw.append(inner[:70])

    if bare_sets:
        hits.append(('math-bare-set', '数集用了裸字母而非 \\mathbb{}',
                     f'×{len(bare_sets)} | ' + ' '.join(sorted(set(bare_sets))[:6])))
    strong = {k: v for k, v in bare_ops.items() if k in OP_NEEDS_OPERATORNAME}
    weak = {k: v for k, v in bare_ops.items() if k not in OP_NEEDS_OPERATORNAME}
    if strong:
        hits.append(('math-op-broken', '算子名缺 \\operatorname,会被排成变量连乘',
                     ' '.join(f'{k}×{v}' for k, v in strong.items())))
    if weak:
        hits.append(('math-op-plain', '算子名缺反斜杠(排成斜体变量)',
                     ' '.join(f'{k}×{v}' for k, v in sorted(weak.items()))[:110]))
    if ascii_rel:
        hits.append(('math-ascii-rel', '关系符用 ASCII 写法,应为 \\le \\ge \\ne',
                     ' '.join(sorted(ascii_rel))))
    if ascii_arrow:
        hits.append(('math-ascii-arrow', '箭头用 ASCII 写法,应为 \\to / \\Rightarrow',
                     ' '.join(sorted(ascii_arrow))))
    if cjk_raw:
        hits.append(('math-raw-cjk', '公式里的中日文没有 \\text{} 包住(字体与间距会错)',
                     ' | '.join(cjk_raw[:2])))
    return hits


# ---------------------------------------------------------------- 主流程

def audit(con):
    findings = defaultdict(list)
    for qid, source, zh, ja in con.execute(
            "SELECT id, COALESCE(source,''), COALESCE(solution_latex,''), "
            "COALESCE(solution_ja,'') FROM questions ORDER BY id"):
        for rule, desc, ev in check_zh(zh) + check_math(zh, 'zh'):
            findings[qid].append(('zh', rule, desc, ev, source))
        if ja.strip():
            for rule, desc, ev in check_ja(ja) + check_math(ja, 'ja'):
                findings[qid].append(('ja', rule, desc, ev, source))
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('db')
    ap.add_argument('--json', help='逐题清单写成 JSON(供 LLM 评审阶段消费)')
    ap.add_argument('--rule', help='只显示某条规则')
    ap.add_argument('--limit', type=int, default=6)
    args = ap.parse_args()

    con = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    total = con.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
    findings = audit(con)

    by_rule = defaultdict(list)
    for qid, items in findings.items():
        for track, rule, desc, ev, source in items:
            by_rule[(track, rule)].append((qid, desc, ev, source))

    print(f'=== 题解语言盘查:共 {total} 道,{len(findings)} 道有命中 ===\n')
    for (track, rule), rows in sorted(by_rule.items(), key=lambda kv: -len(kv[1])):
        if args.rule and rule != args.rule:
            continue
        label = {'zh': '中文轨', 'ja': '日文轨'}[track]
        print(f'[{label}] {rule} —— {rows[0][1].split("] ")[-1]}   命中 {len(rows)} 处')
        for qid, _d, ev, source in rows[:args.limit]:
            print(f'    id={qid:<4} {source[:24]:<26} {ev[:110]}')
        if len(rows) > args.limit:
            print(f'    … 另有 {len(rows) - args.limit} 处')
        print()

    if args.json:
        out = {str(qid): [{'track': t, 'rule': r, 'desc': d, 'evidence': e}
                          for t, r, d, e, _s in items]
               for qid, items in sorted(findings.items())}
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
        print(f'逐题清单已写入 {args.json}')
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
