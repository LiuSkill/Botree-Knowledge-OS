"""协调 1.0 运行时建表与 Alembic 历史之间的已知差异。"""

import logging

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app.core.database import SessionLocal, engine, seed_sensitive_content

logger = logging.getLogger(__name__)

V1_REVISION = "20260714_node_output_waste_fields"
SENSITIVE_REVISION = "20260721_table_sensitive_rules"
SENSITIVE_TABLE_COLUMNS = {
    "sensitive_type": {"id", "code", "name", "default_mask_text", "enabled", "created_at", "updated_at"},
    "sensitive_filter_rule": {
        "id", "code", "name", "sensitive_type_code", "match_type", "pattern", "context_keywords",
        "window_size", "mask_text", "priority", "enabled", "version", "created_at", "updated_at",
    },
    "role_sensitive_permission": {
        "id", "role_id", "sensitive_type_code", "can_view", "created_at", "updated_at",
    },
    "sensitive_redaction_audit": {
        "id", "user_id", "role_ids", "message_id", "chat_type", "project_id", "redaction_types",
        "redaction_count", "final_answer_redacted", "created_at", "updated_at",
    },
}


def main() -> None:
    with engine.connect() as connection:
        current_revision = MigrationContext.configure(connection).get_current_revision()
    if current_revision != V1_REVISION:
        logger.info("无需协调 1.0 敏感内容表: current_revision=%s", current_revision)
        return

    inspector = inspect(engine)
    existing = set(inspector.get_table_names()).intersection(SENSITIVE_TABLE_COLUMNS)
    if not existing:
        logger.info("敏感内容表尚未创建，交由 Alembic 正常升级")
        return
    if existing != set(SENSITIVE_TABLE_COLUMNS):
        missing = sorted(set(SENSITIVE_TABLE_COLUMNS) - existing)
        raise RuntimeError(f"检测到不完整的敏感内容表，拒绝自动升级: missing={missing}")
    for table_name, required_columns in SENSITIVE_TABLE_COLUMNS.items():
        actual_columns = {item["name"] for item in inspector.get_columns(table_name)}
        missing_columns = sorted(required_columns - actual_columns)
        if missing_columns:
            raise RuntimeError(f"敏感内容表结构不完整: table={table_name} missing={missing_columns}")

    with SessionLocal() as db:
        seed_sensitive_content(db)
        db.commit()
    command.stamp(Config("alembic.ini"), SENSITIVE_REVISION)
    logger.info("已确认运行时敏感内容表结构并同步 Alembic 版本: revision=%s", SENSITIVE_REVISION)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
