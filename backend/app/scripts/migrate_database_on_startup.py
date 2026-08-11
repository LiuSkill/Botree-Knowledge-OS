"""服务启动前安全同步数据库结构。"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.database import engine, init_database

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = BACKEND_ROOT / "alembic.ini"


def _alembic_config() -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


def migrate_database_on_startup() -> None:
    """区分未纳管数据库与已版本化数据库，并同步到当前 Alembic head。"""

    config = _alembic_config()
    table_names = set(inspect(engine).get_table_names())

    if "alembic_version" not in table_names:
        # 本项目早期通过 SQLAlchemy create_all 和轻量迁移维护数据库，首条 Alembic
        # 迁移因此不是基础建表迁移。先复用原有兼容初始化补齐当前结构，再纳入版本管理。
        logger.info("数据库尚未纳入 Alembic，正在建立兼容基线")
        init_database()
        command.stamp(config, "head")
    else:
        command.upgrade(config, "head")

    command.current(config, check_heads=True)
    logger.info("数据库结构已同步到 Alembic head")


if __name__ == "__main__":
    migrate_database_on_startup()
