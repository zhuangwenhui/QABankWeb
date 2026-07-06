"""LaTeX 试卷生成。

流程:读取白名单内的 .tex 模板 → 以 ((KEY)) 占位符注入内容(用户输入经
escape_latex 转义,题目 LaTeX 原样注入)→ 探测 xelatex/pdflatex 编译两遍。
系统未安装 LaTeX 引擎时优雅降级:只输出 .tex 源文件并置 engine_missing=True。

对外接口:
    generate_pdf(template_name, context, questions, output_basename) -> dict
    返回 {'ok': bool, 'pdf_path' 或 'tex_path', 'engine_missing': bool, 'error': str|None}
"""
import os
import shutil
import subprocess

import config

# 模板中的占位符键(替换形式为 ((KEY)),避免与 LaTeX 花括号冲突)
PLACEHOLDER_KEYS = ('TITLE', 'SUBTITLE', 'EXAM_DATE', 'SUBJECT',
                    'DURATION', 'TOTAL_SCORE', 'NOTICE', 'QUESTIONS')

# 编译超时(秒)与失败时提取的日志尾部行数
COMPILE_TIMEOUT = 60
LOG_TAIL_LINES = 30

# LaTeX 特殊字符转义表(注意:反斜杠必须最先处理,这里用逐字符映射天然规避二次转义)
_LATEX_SPECIAL = {
    '\\': r'\textbackslash{}',
    '#': r'\#',
    '$': r'\$',
    '%': r'\%',
    '&': r'\&',
    '_': r'\_',
    '{': r'\{',
    '}': r'\}',
    '~': r'\textasciitilde{}',
    '^': r'\textasciicircum{}',
}


def escape_latex(text):
    """转义用户输入中的 LaTeX 特殊字符(# $ % & _ { } ~ ^ \\)。"""
    if text is None:
        return ''
    return ''.join(_LATEX_SPECIAL.get(ch, ch) for ch in str(text))


def _escape_multiline(text):
    """多行用户文本 → 逐行转义并以 \\par 连接(用于注意事项、备注)。"""
    lines = [escape_latex(line.strip()) for line in str(text or '').splitlines()]
    lines = [line for line in lines if line]
    return '\\par '.join(lines)


def _build_questions_block(questions, include_solutions, with_notes):
    """把题目列表拼装为注入 ((QUESTIONS)) 的 LaTeX 片段。

    每题以 \\section*{第 n 题} 开头(有分值时附注);题目/解答 LaTeX 原样注入,
    元信息(科目/来源/难度)与备注为用户数据,一律转义。
    """
    blocks = []
    for idx, q in enumerate(questions or [], 1):
        header = f'第 {idx} 题'
        score = q.get('score')
        if score:
            header += f'(共 {score} 分)'
        lines = [f'\\section*{{{header}}}']

        meta = []
        if q.get('subject'):
            meta.append('科目:' + escape_latex(q['subject']))
        if q.get('source'):
            meta.append('来源:' + escape_latex(q['source']))
        if q.get('difficulty'):
            meta.append('难度:' + escape_latex(q['difficulty']))
        if meta:
            lines.append('\\noindent{\\small\\itshape\\color[gray]{0.45} '
                         + ' \\quad '.join(meta) + '}\\par\\smallskip')

        body = (q.get('question_latex') or '').strip()
        lines.append(body if body else '{\\itshape (本题内容为图片,请参见系统原题。)}')

        if include_solutions:
            lines.append('\\par\\medskip')
            lines.append('\\noindent\\rule{\\linewidth}{0.4pt}\\par\\nopagebreak')
            lines.append('\\noindent\\textbf{【解答】}\\par\\smallskip')
            solution = (q.get('solution_latex') or '').strip()
            lines.append(solution if solution else '{\\itshape (本题暂无文字解答。)}')

        if with_notes:
            notes = (q.get('notes') or '').strip()
            notes_tex = _escape_multiline(notes) if notes else '{\\itshape (未填写备注)}'
            lines.append('\\par\\medskip')
            lines.append('\\noindent\\fbox{\\parbox{'
                         '\\dimexpr\\linewidth-2\\fboxsep-2\\fboxrule\\relax}{'
                         '\\textbf{我的备注}\\par\\smallskip ' + notes_tex + '}}')

        lines.append('\\par\\bigskip')
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)


def _log_tail(out_dir, basename, proc=None, lines=LOG_TAIL_LINES):
    """提取编译日志尾部若干行;读不到 .log 时退回进程 stdout。"""
    text = ''
    log_path = os.path.join(out_dir, basename + '.log')
    try:
        with open(log_path, encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        if proc is not None and proc.stdout:
            text = proc.stdout.decode('utf-8', errors='replace')
    tail = text.splitlines()[-lines:]
    return '\n'.join(tail).strip() or '(无可用日志)'


def _cleanup_aux(out_dir, basename):
    """清理编译产生的辅助文件(保留 .tex 与 .pdf)。"""
    for ext in ('.aux', '.log', '.out', '.toc'):
        try:
            os.remove(os.path.join(out_dir, basename + ext))
        except OSError:
            pass


def generate_pdf(template_name, context, questions, output_basename):
    """生成 PDF 试卷(或降级生成 .tex)。

    参数:
        template_name: 模板名,必须在 config.PDF_TEMPLATES 白名单内
        context: 占位符上下文,键为 TITLE/SUBTITLE/EXAM_DATE/SUBJECT/DURATION/
                 TOTAL_SCORE/NOTICE(用户输入,内部转义);另接受布尔键
                 include_solutions 控制是否注入解答区块
        questions: 题目字典列表(question_latex/solution_latex/subject/source/
                   difficulty/notes/score)
        output_basename: 输出文件基名(由调用方用 uuid 生成,不含用户输入)

    返回:
        {'ok': bool, 'pdf_path' 或 'tex_path', 'engine_missing': bool, 'error': str|None}
    """
    result = {'ok': False, 'engine_missing': False, 'error': None}

    # ---- 模板白名单校验(防任意文件读取) ----
    if template_name not in config.PDF_TEMPLATES:
        result['error'] = '非法的模板名称'
        return result
    template_path = os.path.join(config.Config.LATEX_TEMPLATE_FOLDER,
                                 template_name + '.tex')
    if not os.path.isfile(template_path):
        result['error'] = f'模板文件不存在:{template_name}.tex'
        return result

    # ---- 输出基名校验(调用方用 uuid 生成,这里做双保险) ----
    if not output_basename or not str(output_basename).isalnum():
        result['error'] = '非法的输出文件名'
        return result
    output_basename = str(output_basename)

    try:
        with open(template_path, encoding='utf-8') as f:
            tex = f.read()
    except OSError as exc:
        result['error'] = f'读取模板失败:{exc}'
        return result

    # ---- 占位符替换 ----
    context = dict(context or {})
    include_solutions = bool(context.pop('include_solutions', False))
    with_notes = (template_name == 'error_book_template')
    questions_block = _build_questions_block(questions, include_solutions, with_notes)

    for key in PLACEHOLDER_KEYS:
        if key == 'QUESTIONS':
            value = questions_block          # 题目 LaTeX 原样注入
        elif key == 'NOTICE':
            value = _escape_multiline(context.get(key, ''))
        else:
            value = escape_latex(context.get(key, ''))
        tex = tex.replace(f'(({key}))', value)

    # ---- 写出 .tex ----
    out_dir = config.Config.GENERATED_PDF_FOLDER
    os.makedirs(out_dir, exist_ok=True)
    tex_name = output_basename + '.tex'
    tex_path = os.path.join(out_dir, tex_name)
    try:
        with open(tex_path, 'w', encoding='utf-8') as f:
            f.write(tex)
    except OSError as exc:
        result['error'] = f'写入 .tex 文件失败:{exc}'
        return result
    result['tex_path'] = tex_path

    # ---- 引擎探测:xelatex 优先,其次 pdflatex;都没有则优雅降级 ----
    engine = shutil.which('xelatex') or shutil.which('pdflatex')
    if engine is None:
        result['ok'] = True
        result['engine_missing'] = True
        return result

    # ---- 编译两遍(稳定页码等交叉引用),nonstopmode + 超时保护 ----
    # 安全加固:题目 LaTeX 为用户输入且原样注入,编译时必须禁用 shell-escape 并限制
    # 文件读写范围,防止 \write18 / \input{/etc/passwd} / \openin 等原语读取服务器任意文件。
    pdf_path = os.path.join(out_dir, output_basename + '.pdf')
    cmd = [engine, '-no-shell-escape',
           '-interaction=nonstopmode', '-halt-on-error', tex_name]
    # openin_any/openout_any=p(paranoid):禁止绝对路径与上级目录访问
    compile_env = dict(os.environ)
    compile_env['openin_any'] = 'p'
    compile_env['openout_any'] = 'p'
    proc = None
    try:
        for _ in range(2):
            proc = subprocess.run(cmd, cwd=out_dir, timeout=COMPILE_TIMEOUT,
                                  env=compile_env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if proc.returncode != 0:
                break
    except subprocess.TimeoutExpired:
        result['error'] = f'LaTeX 编译超时({COMPILE_TIMEOUT} 秒),请减少题目数量后重试'
        _cleanup_aux(out_dir, output_basename)
        return result
    except OSError as exc:
        result['error'] = f'LaTeX 编译进程启动失败:{exc}'
        return result

    if proc is None or proc.returncode != 0 or not os.path.isfile(pdf_path):
        result['error'] = ('LaTeX 编译失败,日志尾部:\n'
                           + _log_tail(out_dir, output_basename, proc))
        _cleanup_aux(out_dir, output_basename)
        return result

    _cleanup_aux(out_dir, output_basename)
    result['ok'] = True
    result['pdf_path'] = pdf_path
    return result
