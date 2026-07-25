"""数学排版链路的源码级护栏(便宜、每次 pytest 都跑)。

真正的端到端验证在 scripts/e2e_math_render.py(需要 Chrome,CI 单独一个 job)。
这里只钉住那条让 2026-07-25 线上事故成立的前提:排版不能只依赖 MathJax 的 Promise 版 API。
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(p):
    return (ROOT / p).read_text(encoding='utf-8')


def test_typeset_does_not_gate_on_startup_promise():
    """MathJax v4.1.3 的 startup.promise 实测会永不 settle,拿它当闸门=公式永远不排版。"""
    src = _read('static/js/qd_render.js')
    code = '\n'.join(ln for ln in src.splitlines()
                     if not ln.strip().startswith(('//', '/*', '*')))
    assert 'startup.promise' not in code, \
        'qd_render 不得再以 MathJax.startup.promise 作为排版前置条件'


def test_typeset_has_sync_fallback_and_retry():
    """typesetPromise 可能永不 settle;同步版遇按需加载会抛 retry。二者都要兜住。"""
    src = _read('static/js/qd_render.js')
    assert 'MathJax.typeset(' in src, '缺同步排版兜底'
    assert "indexOf('retry')" in src, '缺对 “retry -- asynchronous action required” 的识别'
    assert 'MAX_SYNC_TRIES' in src, '缺按需资源到位后的重试收敛'


def test_utils_typeset_math_has_sync_fallback():
    """列表/总览页走 utils.typesetMath,同样不能只依赖 Promise 版。"""
    src = _read('static/js/utils.js')
    assert 'MathJax.typeset(' in src, 'utils.typesetMath 缺同步兜底'
    assert "includes('retry')" in src, 'utils.typesetMath 缺 retry 识别'


def test_e2e_guard_script_exists_and_injects_latency():
    """端到端护栏必须注入延迟并压后 API,否则零延迟下永远绿(正是本次漏网的原因)。"""
    src = _read('scripts/e2e_math_render.py')
    assert 'emulateNetworkConditions' in src
    assert 'Fetch.enable' in src and 'API_HOLD_SECONDS' in src
    assert 'JAM_SCRIPT' in src
