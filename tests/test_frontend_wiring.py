"""前端接线护栏(rank13):自托管 vendor + MathJax 锁版 + 无 CDN 回退 + CodeMirror 门控。

后端 pytest 抓不到 JS 运行时,但能抓"模板是否又引了 CDN / 版本是否被解锁 / vendor 资源是否
真存在"这类回归 —— 这正是历史上 MathJax 版本类问题只能人肉走查的盲区。
"""
import glob
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(p):
    return (ROOT / p).read_text(encoding='utf-8')


def test_mathjax_version_locked():
    assert 'mathjax@4.1.3' in _read('templates/base.html'), 'MathJax 必须锁精确版,禁浮动 @4'


def test_core_libs_self_hosted():
    base = _read('templates/base.html')
    assert 'vendor/css/bootstrap.min.css' in base
    assert 'vendor/js/bootstrap.bundle.min.js' in base
    assert 'vendor/css/fontawesome.min.css' in base
    for tpl in ('templates/question_detail.html', 'templates/review.html'):
        t = _read(tpl)
        assert 'vendor/js/markdown-it.min.js' in t
        assert 'vendor/js/purify.min.js' in t
        assert 'js/qd_render.js' in t   # 共享渲染管线(自研,static/js/)


def test_no_cdnjs_and_jsdelivr_only_mathjax():
    for tpl in glob.glob(str(ROOT / 'templates' / '*.html')):
        html = pathlib.Path(tpl).read_text(encoding='utf-8')
        assert 'cdnjs.cloudflare.com' not in html, f'{tpl} 仍引 cdnjs(应已自托管)'
        for line in html.splitlines():
            if 'cdn.jsdelivr.net' in line:
                assert 'mathjax' in line, f'{tpl} 的 jsdelivr 引用非 MathJax:{line.strip()}'


def test_vendor_assets_exist():
    for f in ('static/vendor/js/markdown-it.min.js',
              'static/vendor/js/markdown-it-container.min.js',
              'static/vendor/js/purify.min.js',
              'static/vendor/js/bootstrap.bundle.min.js',
              'static/vendor/js/codemirror.min.js',
              'static/vendor/js/codemirror-stex.min.js',
              'static/vendor/css/bootstrap.min.css',
              'static/vendor/css/fontawesome.min.css',
              'static/vendor/css/codemirror.min.css',
              'static/vendor/webfonts/fa-solid-900.woff2'):
        assert (ROOT / f).exists(), f'缺自托管资源:{f}'


def test_codemirror_self_hosted_and_login_gated():
    # CodeMirror 自托管;按 current_user 加载(编辑=login_required,任何登录用户可用,不误报加载失败)。
    q = _read('templates/questions.html')
    assert 'vendor/js/codemirror.min.js' in q
    assert 'cdnjs' not in q
    assert 'current_user' in q       # 登录用户加载(非 is_admin,避免非管理员编辑者被误降级)


def test_shared_render_pipeline_single_source():
    """qd_render.js 存在,且详情/复习页脚本不再各自内联管线副本(防再次分叉)。"""
    assert (ROOT / 'static/js/qd_render.js').exists()
    qd = _read('static/js/qd_render.js')
    assert 'window.QDRender' in qd and 'renderStructuredInto' in qd
    # 两页脚本改为委托 QDRender(不再各自定义 protectMath/registerContainer)
    for js in ('static/js/question_detail.js', 'static/js/review.js'):
        s = _read(js)
        assert 'QDRender' in s, f'{js} 应委托共享管线'
