"""数学排版链路的源码级护栏(便宜、每次 pytest 都跑)。

真正的端到端验证在 scripts/e2e_math_render.py(需要 Chrome,CI 单独一个 job)。
这里只钉住那条让 2026-07-25 线上事故成立的前提:排版不能只依赖 MathJax 的 Promise 版 API。
"""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(p):
    return (ROOT / p).read_text(encoding='utf-8')


def _slice(src, start, end, where):
    """按源码文本切出 [start, end) 之间那段,供下面几条做文本级断言。

    为什么按源码文本切、而不是执行代码:这些断言盯的是**正则怎么写的**(代码段有没有在
    数学之前挡开、定界符有没有排除转义的 \\$),而 pytest 环境里没有 JS 运行时。

    为什么不直接用 str.index:找不到时它抛的是 `ValueError: substring not found`,
    一坨 traceback 里看不出「是 qd_render.js 里的函数被改名了」。这里换成显式断言,
    让改名的人第一眼就知道该去哪儿看。切片保护的说明写在 qd_render.js 对应函数上方。
    """
    i = src.find(start)
    assert i != -1, (
        f'{where}:在 static/js/qd_render.js 里找不到 `{start}`。'
        f'这段被本测试按源码文本切片保护,改名或内联前请先读本文件的 _slice 说明。')
    j = src.find(end, i)
    assert j != -1, (
        f'{where}:找到了 `{start}` 但其后没有 `{end}`,切片边界失效。'
        f'同上,这两个标记是接口的一部分,不只是实现细节。')
    return src[i:j]


def test_startup_wait_is_bounded():
    """可以礼让 MathJax 启动,但不能无限等 —— startup.promise 常被未完成操作占住而不 settle,
    无上限地等它就等于全站没有数学。"""
    src = _read('static/js/qd_render.js')
    assert 'STARTUP_WAIT_MS' in src, '等待 startup 必须有上限'
    assert 'typesetClear' in src, '动态替换 innerHTML 后必须先 typesetClear,否则 splitText 报错'


def test_single_typeset_queue_site_wide():
    """全站只能有一条排版队列:两条并发会在同一批文本节点上打架。"""
    utils = _read('static/js/utils.js')
    assert 'window.QDRender.typeset' in utils, 'utils.typesetMath 未委托给共享管线'


def test_typeset_whole_document_with_clear_and_autotypeset_off():
    """整页排版 + 先 typesetClear();并关掉 MathJax 的开场自动排版。

    逐块排版试过三种写法都不可靠(同页只有第一块排得出、失败的块每次还不一样);
    开场自动排版若留着,它的初始扫描会与我们的首次调用抢同一批文本节点。
    """
    src = _read('static/js/qd_render.js')
    assert 'DEBOUNCE_MS' in src and 'typesetAll' in src
    assert 'typesetClear()' in src
    assert 'typeset: false' in _read('templates/base.html')


def test_code_spans_are_shielded_before_math_extraction():
    """抽取数学之前必须先把代码段挡开。

    代码段里的 `$` 不是数学。少了这一步,`)$` 这类代码段里的美元号会跟后面真正的公式
    配上对,把中间整段正文吞进"公式"里 —— 页面上表现为文字被拆成一行一个字的碎片
    (2026-07-26 id=266「以 `)$` 收」即此)。
    """
    src = _read('static/js/qd_render.js')
    protect = _slice(src, 'function protectMath', 'function restoreMath', 'protectMath')
    code_at = protect.find('```[\\s\\S]*?```')
    math_at = protect.find('\\$\\$([\\s\\S]+?)')
    assert code_at != -1, 'protectMath 没有挡开代码段'
    assert math_at != -1, 'protectMath 找不到行间公式的匹配'
    assert code_at < math_at, '代码段必须在数学之前挡开,否则代码里的 $ 会跟公式配对'


def test_escaped_dollar_cannot_open_math():
    """`\\$` 是字面美元号,不能充当定界符。

    少了这个判断,`$(L)\\$$` 里「\\$ 的 $ + 收尾的 $」会被当成一对 display 定界符,
    从那里到下一个 \\$ 之间的整段正文都被吞进"公式",页面上表现为文字碎成一行一个字
    (2026-07-26 id=266 即此)。
    """
    src = _read('static/js/qd_render.js')
    protect = _slice(src, 'function protectMath', 'function restoreMath', 'protectMath')
    assert protect.count('(?<!\\\\)') >= 2, 'protectMath 的定界符没有排除转义的 \\$'


def test_inline_math_regex_forbids_newline():
    """行内 `$…$` 的正则必须排除换行 —— 允许跨行,一个漏写的 `$` 就能吞掉后面整段正文。

    这条约束反过来要求**内容侧**不能把块级公式写成跨行的行内公式,由下一条测试盯住。
    """
    src = _read('static/js/qd_render.js')
    protect = _slice(src, 'function protectMath', 'function restoreMath', 'protectMath')
    assert '[^\\$\\\\\\n]' in protect, '行内公式正则没有排除换行'


def test_lint_catches_cross_line_inline_math():
    """盘查必须认出"跨行的行内 `$…$`"。

    前端的 protectMath 保护不到它:markdown 先把 `\\\\[4pt]` 转义成 `\\[`,MathJax 再把
    `\\[` 当成 display 公式的起始符,整块 cases 不排版,正文里只留下一个孤零零的 `\\[`
    (2026-07-27 q136 / q344 线上即此)。按行数奇偶的老判法说不清病因、且每篇只报一条。
    """
    audit = _load('audit_language', 'scripts/audit_language.py')
    broken = ('**(2)** $\\displaystyle\n'
              'P(Z\\le u)=\n\\begin{cases}\n0, & u<-2,\\\\[4pt]\n1, & u>2.\n\\end{cases}$\n')
    fixed = broken.replace('**(2)** $\\displaystyle\n', '**(2)**\n$$\n').replace('\\end{cases}$',
                                                                                '\\end{cases}\n$$')
    assert audit.check_delimiters(broken), '盘查没有认出跨行的行内公式'
    assert not audit.check_delimiters(fixed), '改成 $$…$$ 之后不该再报'
    assert not audit.check_delimiters('文字 $a+b$ と $$c$$ と `$5` と \\$100。'), \
        '行内/行间/代码/转义美元号都不该误报'


def test_markdown_emphasis_is_cjk_aware():
    """`**` 的收尾判定必须对 CJK 放宽,否则三分之一的题会在页面上露出字面 `**`。

    CommonMark 的 flanking 规则按"标点/空白/其它"三分类,CJK 落在"其它"。于是
    「**答えは「存在する」**である。」的收尾 `**` —— 前是「(标点)、后是 で(其它)——
    被判成"不是右侧贴合",收不了尾。全库 358 道里 122 道栽在这上面。
    另外本管线把数学换成了字母数字占位符,而原文那里是 `$`(标点),同样会让收尾失败。
    """
    src = _read('static/js/qd_render.js')
    assert 'scanDelims' in src, '没有放宽 flanking 判定'
    assert 'CJK_FOR_FLANK' in src, '放宽规则里没有认 CJK'
    assert 'PH_HEAD' in src and 'PH_TAIL' in src, '数学占位符没有按标点处理'
    patch = _slice(src, 'function makeCjkFriendly',
                   'State.prototype.__cjkFriendly = true', 'makeCjkFriendly')
    assert 'cjk(last)' in patch and 'cjk(next)' in patch, \
        'CJK 只该放宽"是否标点/空白"这一条,不该直接当成标点'
    assert 'CJK_FOR_FLANK.test(ch)' in patch


def test_a11y_render_actions_are_removed():
    """必须摘掉 MathJax v4 的 enrich / attachSpeech / explorable 渲染动作。

    这三个动作把 SRE 放进 Web Worker 跑,Worker 要从 cdn.jsdelivr.net 拉规则;本站 CSP 的
    connect-src 只有 'self',请求发不出去,Worker 永不回话,于是 renderPromise() 里的
    actionPromises() 永不 settle。它又包在 whenReady() 里 —— 那是个滚动闸门,一次不 settle,
    **此后每一次排版都卡在闸门前连跑都跑不到**。首渲的 DOM 更新在挂起前已完成,页面"看着是好的",
    故障要等第二批内容注入才现形(2026-07-26 列表页详情弹窗满屏 $…$ 源码即此)。
    """
    src = _read('templates/base.html')
    assert 'removeRenderAction' in src, 'base.html 未摘掉 a11y 渲染动作'
    for action in ('enrich', 'attachSpeech', 'explorable'):
        assert f"'{action}'" in src, f'未摘掉渲染动作 {action}'
    assert 'defaultReady' in src, 'startup.ready 覆盖了默认初始化却没调 defaultReady()'


def test_e2e_guard_checks_second_typeset_settles():
    """端到端护栏必须验证"第二次排版能 settle" —— 只看首屏永远发现不了闸门被堵。"""
    src = _read('scripts/e2e_math_render.py')
    assert 'SECOND_TYPESET' in src, 'e2e 护栏缺少二次排版回归'


def test_render_audit_asserts_modal_actually_typeset():
    """巡检对弹窗不能只看"有没有裸 $",还必须断言真的排出了 mjx-container。

    弹窗内容曾经既没有裸 $ 计数(文本被截断)也没有公式,靠文本规则漏了整整一轮。
    """
    src = _read('scripts/audit_render.py')
    assert 'detailModal mjx-container' in src, '巡检未断言弹窗内真的有排版产物'


def test_typeset_is_serialized_with_timeout():
    """排版必须串行且带超时。

    并发排版同一批文本节点会让 MathJax 抛
    "Failed to execute 'splitText' … offset is larger than the Text node's length",
    该次 Promise 未处理地 reject,整块公式停在源码态(2026-07-26 题面区空白即此)。
    """
    src = _read('static/js/qd_render.js')
    assert 'chain = chain.then' in src, 'qd_render 排版未串行'
    assert 'TYPESET_TIMEOUT_MS' in src, 'qd_render 排版缺超时,一次卡死会堵住整页'


def test_no_sync_typeset_racing_the_promise():
    """不得再出现"同步排版 + 促发异步"的兜底 —— 它正是上面那个并发竞态的来源。"""
    for name in ('static/js/qd_render.js', 'static/js/utils.js'):
        code = '\n'.join(ln for ln in _read(name).splitlines()
                          if not ln.strip().startswith(('//', '*', '/*')))
        assert 'MathJax.typeset(' not in code, f'{name} 又用回了同步 MathJax.typeset'


def test_utils_typeset_math_is_serialized():
    """列表/总览页走 utils.typesetMath,同样必须串行。"""
    src = _read('static/js/utils.js')
    assert '__mathChain' in src, 'utils.typesetMath 未串行'
    assert 'typesetPromise' in src


def test_e2e_guard_script_exists_and_injects_latency():
    """端到端护栏必须注入延迟并压后 API,否则零延迟下永远绿(正是本次漏网的原因)。"""
    src = _read('scripts/e2e_math_render.py')
    assert 'emulateNetworkConditions' in src
    assert 'Fetch.enable' in src and 'API_HOLD_SECONDS' in src
    assert 'JAM_SCRIPT' in src


CONTENT_PAGES = ['questions', 'question_detail', 'review', 'error_book', 'overview', 'list_detail']
CONTENT_JS = ['questions.js', 'question_detail.js', 'review.js', 'error_book.js',
              'overview.js', 'list_detail.js']


def test_all_content_pages_load_pipeline():
    """凡是会把题目内容写进 DOM 的页面,都必须 include 渲染管线。

    详情弹窗、错题本、总览、题单详情都曾各自漏网 —— 用户是靠肉眼一个个发现的。
    """
    for name in CONTENT_PAGES:
        src = _read(f'templates/{name}.html')
        assert "_render_pipeline.html" in src, f'{name}.html 未 include 渲染管线'


def test_all_content_js_use_shared_pipeline():
    """这些脚本必须把富文本交给 QDRender,而不是只做 escapeHtml。"""
    for name in CONTENT_JS:
        src = _read(f'static/js/{name}')
        assert 'QDRender' in src, f'{name} 未使用共享渲染管线'


def test_pipeline_include_is_single_source():
    """管线只能有一份定义,避免再次出现"改了一处漏了另一处"。"""
    inc = _read('templates/_render_pipeline.html')
    assert 'qd_render.js' in inc and 'markdown-it' in inc and 'purify' in inc
    for name in CONTENT_PAGES:
        src = _read(f'templates/{name}.html')
        assert 'vendor/js/markdown-it.min.js' not in src, \
            f'{name}.html 又自己内联了管线脚本,应统一走 include'


# ============================================================ 预览截断不得剖开公式
# 2026-07-28 线上事故:列表预览按字符数硬切到 240,把 $$…$$ 剖成两半,落单的定界符
# MathJax 认不出,于是整段 LaTeX 源码显示在题目管理页上。358 道题里命中 33 道。
# 巡检当时报「裸公式=0」——它的判据 /\$[^$\n]{2,120}\$/ 只认**配对且单行**的公式,
# 对"落单的 $$"结构性失明,而那恰恰是截断能造成的唯一形态。

def test_preview_clip_avoids_math():
    """renderPreviewInto 必须走 clipOutsideMath,不能再自己按字符数硬切。"""
    src = _read('static/js/qd_render.js')
    body = _slice(src, 'function renderPreviewInto', 'function renderInto',
                  'renderPreviewInto')
    assert 'clipOutsideMath' in body, \
        'renderPreviewInto 必须用 clipOutsideMath 求截断点,否则会把 $$…$$ 剖开'
    assert "lastIndexOf('\\n')" not in body, \
        '截断点的选取应留在 clipOutsideMath 里,别在这儿再切一次'


def test_math_spans_uses_same_delimiters_as_protect():
    """mathSpans 的定界符正则必须与 protectMath 逐字一致。

    这是本次修复的**要害不变量**:clipOutsideMath 靠 mathSpans 判断"哪里是公式内部",
    两边一旦对定界符的看法分叉,算出来的"安全截断点"就是假的 —— 切口又会落进公式里,
    而且这次不会有任何测试变红。改 protectMath 的定界符时,这条会强制你同步改 mathSpans。
    """
    src = _read('static/js/qd_render.js')
    spans = _slice(src, 'function mathSpans', 'function clipOutsideMath', 'mathSpans')
    protect = _slice(src, 'function protectMath', 'function restoreMath', 'protectMath')

    display = r'/(?<!\\)\$\$([\s\S]+?)(?<!\\)\$\$/g'
    inline = r'/(?<!\\)\$((?:\\.|[^\$\\\n])+?)\$/g'
    for name, pattern in (('display', display), ('inline', inline)):
        assert pattern in protect, f'protectMath 的 {name} 定界符变了,请同步本测试与 mathSpans'
        assert pattern in spans, \
            f'mathSpans 的 {name} 定界符与 protectMath 不一致,截断点会重新落进公式里'

    # 代码段必须先挡掉:代码里的 $ 不是数学。protectMath 自己写了这条正则,
    # mathSpans 则委托给 codeSpans —— 两边认的东西必须还是同一个。
    code = r'/```[\s\S]*?```|`[^`\n]*`/g'
    assert code in protect, 'protectMath 的代码段正则变了,请同步 codeSpans 与本测试'
    code_fn = _slice(src, 'function codeSpans', 'function mathSpans', 'codeSpans')
    assert code in code_fn, 'codeSpans 的代码段正则与 protectMath 不一致'
    assert 'codeSpans(' in spans, \
        'mathSpans 必须先用 codeSpans 挡开代码段,否则会把代码里的 $ 当公式'
