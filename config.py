"""全局配置与固定枚举。"""
import os
import secrets
import sys

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _resolve_secret_key():
    """会话签名密钥。

    优先取环境变量 SECRET_KEY;未配置时进程启动随机生成一次(每次重启旧会话失效),
    绝不在代码里保留可用的硬编码回退密钥,避免默认密钥被用来伪造会话冒充管理员。
    """
    key = os.environ.get('SECRET_KEY')
    if key:
        return key
    print('[配置警告] 未设置环境变量 SECRET_KEY,已随机生成临时密钥;'
          '生产环境请务必通过 SECRET_KEY 注入固定密钥。', file=sys.stderr)
    return secrets.token_hex(32)


class Config:
    SECRET_KEY = _resolve_secret_key()
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'question_bank.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    GENERATED_PDF_FOLDER = os.path.join(BASE_DIR, 'generated_pdfs')
    LATEX_TEMPLATE_FOLDER = os.path.join(BASE_DIR, 'latex_templates')
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 上传体积上限 20MB
    # 不含 svg:SVG 会以 image/svg+xml 内联渲染,可携带脚本构成存储型 XSS
    ALLOWED_UPLOAD_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf'}


# 课程为固定分类(见技术文档 §4)
SUBJECTS = ['向量解析', '备注', '复变函数', '微分方程', '微积分', '概率统计', '线性代数']
DIFFICULTIES = ['简单', '中等', '困难']
PER_PAGE_OPTIONS = [10, 20, 50, 100]
FEEDBACK_STATUSES = ['待处理', '已处理']
# 三套试卷模板,对应 latex_templates/ 下同名 .tex 文件
PDF_TEMPLATES = ['custom_exam_template', '试卷模板', 'error_book_template']
