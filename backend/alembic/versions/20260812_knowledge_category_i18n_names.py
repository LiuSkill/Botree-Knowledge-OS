"""add i18n names to knowledge categories

Revision ID: 20260812_knowledge_category_i18n_names
Revises: 20260806_qa_trace_events
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_knowledge_category_i18n_names"
down_revision: str | None = "20260806_qa_trace_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return table_name in set(_inspector().get_table_names())


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return column_name in {column["name"] for column in _inspector().get_columns(table_name)}


def _add_column_if_missing(column: sa.Column) -> None:
    if _has_column("knowledge_categories", column.name):
        return
    op.add_column("knowledge_categories", column)


def upgrade() -> None:
    if not _has_table("knowledge_categories"):
        return
    _add_column_if_missing(sa.Column("name_zh", sa.String(length=100), nullable=True, comment="分类中文名称"))
    _add_column_if_missing(sa.Column("name_en", sa.String(length=100), nullable=True, comment="分类英文名称"))
    op.execute(
        sa.text(
            """
            UPDATE knowledge_categories
            SET name_zh = COALESCE(NULLIF(name_zh, ''), name)
            WHERE name_zh IS NULL OR name_zh = ''
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported for knowledge category i18n names")
