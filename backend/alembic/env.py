"""
Alembic Environment

负责：
1. 读取 Botree Knowledge OS 运行时数据库配置
2. 暴露 SQLAlchemy Base.metadata 给 Alembic 自动迁移
3. 为后续生产迁移替代启动时轻量补丁迁移提供基础
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
# Alembic 通过 ConfigParser 保存 sqlalchemy.url，URL 中的百分号需要转义，
# 否则带有 URL 编码密码的连接串会被误判为插值表达式。
config.set_main_option("sqlalchemy.url", settings.effective_database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    离线生成迁移 SQL。

    说明：
        不创建 Engine，仅根据 URL 和 metadata 输出 SQL。
    """

    context.configure(
        url=settings.effective_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    在线执行迁移。

    说明：
        使用 Alembic 配置创建 Engine，并在事务内运行迁移。
    """

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
