"""采点判题引擎(可插拔)。

学生手写作答照片 → 多模态 LLM 按题目采点 rubric 逐项给分 + 转写 + 反馈。

- Grader.grade(...) 返回统一结构:
    {total_score, max_score, breakdown:[{label,awarded,max,comment}],
     transcription, feedback, model}
- ClaudeVisionGrader:门控 ANTHROPIC_API_KEY,stdlib urllib 直调 Anthropic /v1/messages
  (base64 传图),免第三方依赖。
- StubGrader:无 key 兜底,诚实占位(不编造分)。
- get_grader(config):有 key → Claude,否则 Stub。
"""
import base64
import json
import os
import urllib.error
import urllib.request

DEFAULT_MODEL = 'claude-opus-4-8'
DEFAULT_BASE_URL = 'https://api.anthropic.com'
ANTHROPIC_VERSION = '2023-06-01'
REQUEST_TIMEOUT = 60  # 秒

_MEDIA = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
          'gif': 'image/gif', 'webp': 'image/webp'}


class GradingError(Exception):
    """评分过程不可恢复错误(网络/解析/上游 4xx-5xx)。"""


def _media_type(path):
    ext = os.path.splitext(path)[1].lstrip('.').lower()
    return _MEDIA.get(ext, 'image/jpeg')


def _encode_image(path):
    """(media_type, base64_data);读文件失败抛 GradingError。"""
    try:
        with open(path, 'rb') as f:
            return _media_type(path), base64.b64encode(f.read()).decode('ascii')
    except OSError as exc:
        raise GradingError(f'读取作答图失败:{exc}')


def _extract_json(text):
    """从模型输出中抽出 JSON 对象:容忍 ```json 围栏与前后噪声。"""
    s = (text or '').strip()
    if s.startswith('```'):
        s = s.split('```', 2)[1] if s.count('```') >= 2 else s.strip('`')
        if s.lstrip().lower().startswith('json'):
            s = s.lstrip()[4:]
    # 退而求其次:截取第一个 { 到最后一个 }
    lo, hi = s.find('{'), s.rfind('}')
    if lo != -1 and hi != -1 and hi > lo:
        s = s[lo:hi + 1]
    try:
        return json.loads(s)
    except (ValueError, TypeError) as exc:
        raise GradingError(f'模型输出非合法 JSON:{exc}')


def _num(v, default=0.0):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return default


def _normalize(parsed, model):
    """把模型 JSON 裁剪为统一结构,缺失项补齐,total/max 缺则由 breakdown 求和。"""
    if not isinstance(parsed, dict):
        raise GradingError('模型输出不是 JSON 对象')
    raw_bd = parsed.get('breakdown') or []
    breakdown = []
    for item in raw_bd if isinstance(raw_bd, list) else []:
        if not isinstance(item, dict):
            continue
        breakdown.append({
            'label': str(item.get('label', ''))[:120],
            'awarded': _num(item.get('awarded')),
            'max': _num(item.get('max')),
            'comment': str(item.get('comment', ''))[:800],
        })
    total = parsed.get('total_score')
    mx = parsed.get('max_score')
    total = _num(total) if total is not None else round(sum(b['awarded'] for b in breakdown), 2)
    mx = _num(mx) if mx is not None else round(sum(b['max'] for b in breakdown), 2)
    return {
        'total_score': total,
        'max_score': mx,
        'breakdown': breakdown,
        'transcription': str(parsed.get('transcription', ''))[:8000],
        'feedback': str(parsed.get('feedback', ''))[:4000],
        'model': model,
    }


class Grader:
    name = 'base'

    def grade(self, *, question_text, reference_solution, rubric, image_paths):
        raise NotImplementedError


class StubGrader(Grader):
    """未配置 AI 阅卷引擎时的诚实占位:保存作答,不编造分数。"""
    name = 'stub'

    def grade(self, *, question_text, reference_solution, rubric, image_paths):
        return {
            'total_score': 0.0,
            'max_score': 0.0,
            'breakdown': [],
            'transcription': '',
            'feedback': ('⚠️ AI 阅卷引擎未配置(未设 ANTHROPIC_API_KEY)。'
                         '你的作答照片已保存,配置引擎后可重新批改。'),
            'model': 'stub',
        }


class ClaudeVisionGrader(Grader):
    """用 Claude 多模态直接阅卷:读作答照片,按采点 rubric 逐项给部分分。"""
    name = 'claude'

    def __init__(self, api_key, model=DEFAULT_MODEL, base_url=DEFAULT_BASE_URL):
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip('/')

    def _prompt(self, question_text, reference_solution, rubric):
        rub = rubric if isinstance(rubric, dict) else {}
        parts = [
            '你是日本大学院入试(院試)的资深阅卷官。学生上传了手写作答的照片。',
            '请:①逐字读出作答内容(数学式尽量转成 LaTeX);②对照【参考题解】与【采点标准】,'
            '按采点逐项判给部分分(数学上等价/殊途同归也应给分,勿只看表面);③给公允的综合反馈。',
            '',
            '【题目】\n' + (question_text or '(无题面)'),
            '',
            '【参考题解】\n' + (reference_solution or '(无参考题解)'),
            '',
            '【采点标准 rubric】',
            '解答方針:' + (rub.get('houshin') or '(无)'),
            '答案例:' + (rub.get('model') or '(无)'),
            '典型失点:' + (rub.get('shitten') or '(无)'),
            '部分点分布(配点,评分主依据):' + (rub.get('haiten') or '(无)'),
            '',
            '仅输出如下 JSON,不要任何解释或围栏:',
            '{"transcription":"读到的作答(可含 $LaTeX$)",'
            '"breakdown":[{"label":"采点项名","awarded":数值,"max":该项满分,"comment":"该项判词"}],'
            '"total_score":总得分,"max_score":总满分,"feedback":"综合反馈(中文,先肯定后改进)"}',
            '若配点未给明确分值,按各采点项均摊合理满分。若照片无法辨读,如实在 feedback 说明并给低分。',
        ]
        return '\n'.join(parts)

    def _post(self, body):
        req = urllib.request.Request(
            self.base_url + '/v1/messages',
            data=json.dumps(body).encode('utf-8'),
            headers={
                'content-type': 'application/json',
                'x-api-key': self.api_key,
                'anthropic-version': ANTHROPIC_VERSION,
            },
            method='POST')
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'replace')[:500]
            raise GradingError(f'Anthropic API {exc.code}:{detail}')
        except (urllib.error.URLError, TimeoutError) as exc:
            raise GradingError(f'请求 Anthropic 失败:{exc}')

    def grade(self, *, question_text, reference_solution, rubric, image_paths):
        if not image_paths:
            raise GradingError('无作答图可评分')
        content = [{'type': 'text', 'text': self._prompt(question_text, reference_solution, rubric)}]
        for p in image_paths:
            media, data = _encode_image(p)
            content.append({'type': 'image',
                            'source': {'type': 'base64', 'media_type': media, 'data': data}})
        body = {'model': self.model, 'max_tokens': 2000,
                'messages': [{'role': 'user', 'content': content}]}
        resp = self._post(body)
        blocks = resp.get('content') or []
        text = ''
        for b in blocks:
            if isinstance(b, dict) and b.get('type') == 'text':
                text += b.get('text', '')
        if not text:
            raise GradingError('Anthropic 返回空内容')
        return _normalize(_extract_json(text), self.model)


def get_grader(config):
    """按配置选引擎:有 ANTHROPIC_API_KEY → Claude,否则 Stub。"""
    key = (config.get('ANTHROPIC_API_KEY') or '').strip() if config else ''
    if key:
        return ClaudeVisionGrader(
            key,
            model=config.get('ANTHROPIC_GRADER_MODEL') or DEFAULT_MODEL,
            base_url=config.get('ANTHROPIC_BASE_URL') or DEFAULT_BASE_URL)
    return StubGrader()
