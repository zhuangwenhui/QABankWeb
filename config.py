"""全局配置与固定枚举:按 APP_ENV 分层(development / production / testing)。"""
import os
import secrets
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """公共基础配置。"""
    ENV_NAME = 'base'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'question_bank.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    GENERATED_PDF_FOLDER = os.path.join(BASE_DIR, 'generated_pdfs')
    LATEX_TEMPLATE_FOLDER = os.path.join(BASE_DIR, 'latex_templates')
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 上传体积上限 20MB
    # 不含 svg:SVG 会以 image/svg+xml 内联渲染,可携带脚本构成存储型 XSS
    ALLOWED_UPLOAD_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf'}
    # 会话与 Cookie 安全基线(Secure 仅生产开启,见 ProdConfig)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    # 部署层开关(阶段三使用)
    USE_PROXYFIX = False
    USE_X_ACCEL = False
    TALISMAN_FORCE_HTTPS = False


class DevConfig(Config):
    """开发:无 SECRET_KEY 时随机生成(每次重启会话失效),不打印告警避免测试噪音。"""
    ENV_NAME = 'development'
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)


class ProdConfig(Config):
    """生产:SECRET_KEY 必须由环境变量注入,缺失时 create_app 拒绝启动。"""
    ENV_NAME = 'production'
    SECRET_KEY = os.environ.get('SECRET_KEY')  # 可能为 None,由 create_app 校验
    SESSION_COOKIE_SECURE = True
    USE_PROXYFIX = True
    USE_X_ACCEL = os.environ.get('USE_X_ACCEL', '1') == '1'
    TALISMAN_FORCE_HTTPS = True


class TestingConfig(Config):
    """测试:内存库、固定密钥。"""
    ENV_NAME = 'testing'
    TESTING = True
    SECRET_KEY = 'test-secret-key'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


def get_config():
    """按 APP_ENV 环境变量返回配置类,默认开发。"""
    env = os.environ.get('APP_ENV', 'development')
    return {
        'development': DevConfig,
        'production': ProdConfig,
        'testing': TestingConfig,
    }.get(env, DevConfig)


# 课程为固定分类(见技术文档 §4)
SUBJECTS = ['向量解析', '备注', '复变函数', '微分方程', '微积分', '概率统计', '线性代数']
DIFFICULTIES = ['简单', '中等', '困难']
PER_PAGE_OPTIONS = [10, 20, 50, 100]
FEEDBACK_STATUSES = ['待处理', '已处理']
# 三套试卷模板,对应 latex_templates/ 下同名 .tex 文件
PDF_TEMPLATES = ['custom_exam_template', '试卷模板', 'error_book_template']
# 密码最小长度(改密/建号接口校验)
MIN_PASSWORD_LEN = 12
