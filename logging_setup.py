"""结构化日志:JSON 输出、请求日志中间件(request_id)、审计辅助。

审计红线:绝不记录密码、会话 token、验证码答案(CWE-532)。
"""
import json
import logging
import logging.config
import time
import uuid
from datetime import datetime, timezone

from flask import g, has_request_context, request

# 附加到 LogRecord 的扩展字段(JsonFormatter 按存在与否输出)
_EXTRA_FIELDS = ('request_id', 'user_id', 'ip', 'event', 'target', 'detail',
                 'method', 'path', 'status', 'duration_ms')


class JsonFormatter(logging.Formatter):
    """把日志渲染成单行 JSON,供 journalctl / 日志采集直接解析。

    _EXTRA_FIELDS 里的字段**存在才输出**(值为 None 的整个键都不出现),
    所以同一个 logger 打出来的行字段数可能不同 —— 下游别假设 schema 固定。
    """

    def format(self, record):
        """LogRecord → 单行 JSON 串。

        exc_info 存在时额外塞一个 exc 字段(格式化后的完整栈)。
        ensure_ascii=False:中文日志直接可读,不然 journalctl 里全是 \\uXXXX。
        """
        entry = {
            'ts': datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec='milliseconds'),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        for key in _EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = value
        if record.exc_info:
            entry['exc'] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def request_extra():
    """当前请求上下文的通用日志字段(request_id/ip/user_id)。公开:异常兜底也用它。"""
    if not has_request_context():
        return {}
    extra = {'request_id': getattr(g, 'request_id', None),
             'ip': request.remote_addr}
    user = g.get('user')
    if user is not None:
        extra['user_id'] = user.id
    return {k: v for k, v in extra.items() if v is not None}


def audit(event, target=None, detail=None):
    """记录安全审计事件(login_success/login_failed/access_denied/question_delete/...)。"""
    extra = request_extra()
    extra['event'] = event
    if target is not None:
        extra['target'] = str(target)
    if detail is not None:
        extra['detail'] = str(detail)
    logging.getLogger('audit').info(event, extra=extra)


def setup_logging(app):
    """dictConfig 输出 JSON 到 stdout + 每请求一行访问日志。"""
    if not app.testing:  # 测试下保留 pytest caplog 的默认 handler 结构
        logging.config.dictConfig({
            'version': 1,
            'disable_existing_loggers': False,
            'formatters': {'json': {'()': JsonFormatter}},
            'handlers': {'stdout': {
                'class': 'logging.StreamHandler',
                'stream': 'ext://sys.stdout',
                'formatter': 'json',
            }},
            'root': {'level': 'INFO', 'handlers': ['stdout']},
        })

    # 防御:同进程内若曾调用 logging.config.fileConfig(...)(如 Alembic env.py 的
    # flask db upgrade)且未显式 disable_existing_loggers=False,会把当时已存在的
    # 具名 logger .disabled 置 True 且不可逆。审计/请求日志与 Flask 自身的 app.logger
    # 都是本应用的关键可观测性通道,显式复位,不受第三方一次性 fileConfig 调用影响。
    logging.getLogger('audit').disabled = False
    logging.getLogger('request').disabled = False
    app.logger.disabled = False

    @app.before_request
    def _assign_request_id():
        """给每个请求发一个短 id 与起始计时点,供全链路日志关联。

        必须**先于** app.py 的 load_user_and_csrf 注册 —— 那个 hook 里的 audit() 要用
        g.request_id,注册晚了就关联不上(setup_logging 的调用位置已保证这一点)。
        """
        g.request_id = uuid.uuid4().hex[:12]
        g._req_start = time.perf_counter()

    @app.after_request
    def _log_request(response):
        """每个请求收尾时打一行访问日志:方法 / 路径 / 状态码 / 耗时。

        整块包在 try/except 里且吞掉一切异常:日志绝不能影响业务响应 ——
        打不出日志顶多是少一行记录,抛出去就是用户看到 500。
        """
        try:
            duration_ms = round((time.perf_counter() - getattr(g, '_req_start', time.perf_counter())) * 1000, 1)
            extra = request_extra()
            extra.update({'method': request.method, 'path': request.path,
                          'status': response.status_code, 'duration_ms': duration_ms})
            logging.getLogger('request').info(
                f'{request.method} {request.path} {response.status_code}', extra=extra)
        except Exception:  # 日志绝不能影响业务响应
            pass
        return response
