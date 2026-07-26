"""数学排版链路的源码级护栏(便宜、每次 pytest 都跑)。

真正的端到端验证在 scripts/e2e_math_render.py(需要 Chrome,CI 单独一个 job)。
这里只钉住那条让 2026-07-25 线上事故成立的前提:排版不能只依赖 MathJax 的 Promise 版 API。
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(p):
    return (ROOT / p).read_text(encoding='utf-8')


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
