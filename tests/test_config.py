"""配置分层测试:APP_ENV 选择、生产 fail-fast、Cookie 安全属性。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config as config_module


def test_get_config_by_env(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'development')
    assert config_module.get_config() is config_module.DevConfig
    monkeypatch.setenv('APP_ENV', 'production')
    assert config_module.get_config() is config_module.ProdConfig
    monkeypatch.setenv('APP_ENV', 'testing')
    assert config_module.get_config() is config_module.TestingConfig
    monkeypatch.delenv('APP_ENV', raising=False)
    assert config_module.get_config() is config_module.DevConfig  # 默认开发
    monkeypatch.setenv('APP_ENV', 'prod')  # 拼写错误必须拒绝而非静默回落
    with pytest.raises(RuntimeError, match='APP_ENV'):
        config_module.get_config()


def test_prod_config_requires_secret_key(monkeypatch):
    """生产配置 + 无 SECRET_KEY → create_app 必须拒绝启动。

    直接 monkeypatch 类属性,不依赖 import 时机与 importlib.reload。
    """
    from app import create_app
    monkeypatch.setattr(config_module.ProdConfig, 'SECRET_KEY', None)
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        create_app(config_module.ProdConfig)


def test_prod_config_rejects_blank_secret_key(monkeypatch):
    """空白(纯空格)SECRET_KEY 视同缺失,同样拒绝启动。"""
    from app import create_app
    monkeypatch.setattr(config_module.ProdConfig, 'SECRET_KEY', '   ')
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        create_app(config_module.ProdConfig)


def test_prod_config_cookie_flags(monkeypatch):
    from app import create_app
    monkeypatch.setattr(config_module.ProdConfig, 'SECRET_KEY', 'x' * 32)
    application = create_app(config_module.ProdConfig)
    assert application.config['SESSION_COOKIE_SECURE'] is True
    assert application.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
    assert application.config['SESSION_COOKIE_HTTPONLY'] is True
    assert application.config['PERMANENT_SESSION_LIFETIME'].total_seconds() == 12 * 3600


def test_dev_config_no_secure_cookie():
    from app import create_app
    application = create_app(config_module.DevConfig)
    assert not application.config.get('SESSION_COOKIE_SECURE')


def test_testing_config_uses_memory_db():
    from app import create_app
    application = create_app(config_module.TestingConfig)
    assert application.config['TESTING'] is True
    assert 'memory' in application.config['SQLALCHEMY_DATABASE_URI']
