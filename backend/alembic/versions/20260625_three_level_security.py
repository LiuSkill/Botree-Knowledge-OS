"""introduce three-level security access control

Revision ID: 20260625_three_level_security
Revises: 20260625_chat_visible_progress
Create Date: 2026-06-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260625_three_level_security"
down_revision: str | None = "20260625_chat_visible_progress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SECURITY_TABLES = (
    ("roles", "角色最高密级"),
    ("projects", "项目密级"),
    ("documents", "文档密级"),
    ("document_versions", "文档版本密级"),
    ("document_chunks", "Chunk密级"),
    ("document_pages", "文档页密级"),
    ("page_indexes", "PageIndex密级"),
)


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return table_name in set(_inspector().get_table_names())


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return column_name in {column["name"] for column in _inspector().get_columns(table_name)}


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return index_name in {index["name"] for index in _inspector().get_indexes(table_name)}


def _add_security_column(table_name: str, comment: str) -> None:
    if not _has_table(table_name) or _has_column(table_name, "security_level"):
        return
    op.add_column(
        table_name,
        sa.Column(
            "security_level",
            sa.String(length=30),
            nullable=False,
            server_default="internal",
            comment=f"{comment}: public/internal/confidential",
        ),
    )


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if not _has_column(table_name, column_name):
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.drop_column(column_name)


def _create_index_if_missing(table_name: str, column_name: str) -> None:
    index_name = f"idx_{table_name}_{column_name}"
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, [column_name])


def _drop_index_if_exists(table_name: str, column_name: str) -> None:
    index_name = f"idx_{table_name}_{column_name}"
    if _has_table(table_name) and _has_index(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _sync_from_documents(table_name: str) -> None:
    if not _has_table(table_name) or not _has_column(table_name, "security_level"):
        return
    op.execute(
        sa.text(
            f"""
            UPDATE {table_name}
            SET security_level = COALESCE(
                (SELECT documents.security_level FROM documents WHERE documents.id = {table_name}.document_id),
                'internal'
            )
            WHERE security_level IS NULL OR security_level = ''
            """
        )
    )


def upgrade() -> None:
    if _has_table("knowledge_base_permissions"):
        op.drop_table("knowledge_base_permissions")
    _drop_column_if_exists("knowledge_bases", "visibility")

    for table_name, comment in SECURITY_TABLES:
        _add_security_column(table_name, comment)
        _create_index_if_missing(table_name, "security_level")

    if _has_table("roles") and _has_column("roles", "security_level"):
        op.execute(
            sa.text(
                """
                UPDATE roles
                SET security_level = CASE
                    WHEN code = 'admin' THEN 'confidential'
                    WHEN code = 'engineer' THEN 'internal'
                    WHEN code = 'viewer' THEN 'public'
                    ELSE COALESCE(NULLIF(security_level, ''), 'internal')
                END
                WHERE security_level IS NULL
                   OR security_level = ''
                   OR code IN ('admin', 'engineer', 'viewer')
                """
            )
        )

    for table_name in ("projects", "documents"):
        if _has_table(table_name) and _has_column(table_name, "security_level"):
            op.execute(
                sa.text(
                    f"""
                    UPDATE {table_name}
                    SET security_level = COALESCE(NULLIF(security_level, ''), 'internal')
                    WHERE security_level IS NULL OR security_level = ''
                    """
                )
            )

    for table_name in ("document_versions", "document_chunks", "document_pages", "page_indexes"):
        _sync_from_documents(table_name)


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported after removing legacy knowledge-base authorization")
