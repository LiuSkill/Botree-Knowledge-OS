"""expand page index text fields to longtext

Revision ID: 20260702_expand_page_index_text_longtext
Revises: 20260630_user_soft_delete
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260702_expand_page_index_text_longtext"
down_revision: str | None = "20260630_user_soft_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in set(inspector.get_table_names())


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def _alter_longtext(table_name: str, column_name: str, comment: str, *, nullable: bool) -> None:
    if not _is_mysql() or not _has_column(table_name, column_name):
        return
    op.alter_column(
        table_name,
        column_name,
        type_=mysql.LONGTEXT(),
        existing_nullable=nullable,
        existing_comment=comment,
        comment=comment,
    )


def upgrade() -> None:
    # 页级解析内容会包含整页表格/图纸 OCR 文本，可能超过 MySQL TEXT 的 64KB 上限。
    for column_name, comment, nullable in (
        ("page_text", "页原始正文文本", False),
        ("clean_content", "清洗后页文本", True),
        ("filtered_content", "过滤后页文本", True),
        ("cleaning_metadata_json", "清洗摘要JSON", True),
        ("corrected_text", "人工修正后的文本", True),
    ):
        _alter_longtext("document_pages", column_name, comment, nullable=nullable)

    for column_name, comment in (
        ("text", "块原始文本"),
        ("clean_text", "清洗后块文本"),
        ("metadata_json", "块扩展元数据JSON"),
    ):
        _alter_longtext("document_page_blocks", column_name, comment, nullable=True)

    _alter_longtext("page_indexes", "index_text", "用于页面索引的文本", nullable=False)


def downgrade() -> None:
    # 不自动降级，避免已写入的大页解析文本被 TEXT 截断。
    pass
