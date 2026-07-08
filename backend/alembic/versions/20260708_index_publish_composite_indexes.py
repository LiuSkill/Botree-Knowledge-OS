"""add composite indexes for index publishing

Revision ID: 20260708_index_publish_composite_indexes
Revises: 20260702_expand_page_index_text_longtext
Create Date: 2026-07-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260708_index_publish_composite_indexes"
down_revision: str | None = "20260702_expand_page_index_text_longtext"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    ("page_indexes", "idx_page_indexes_doc_status_ver", ["document_id", "status", "version_no"]),
    ("graph_entities", "idx_graph_entities_doc_status_ver", ["document_id", "status", "version_no"]),
    ("graph_relations", "idx_graph_relations_doc_status_ver", ["document_id", "status", "version_no"]),
)


def _has_table(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in set(inspector.get_table_names())


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    inspector = sa.inspect(op.get_bind())
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    for table_name, index_name, column_names in INDEXES:
        if not _has_table(table_name) or _has_index(table_name, index_name):
            continue
        op.create_index(index_name, table_name, column_names)


def downgrade() -> None:
    for table_name, index_name, _column_names in reversed(INDEXES):
        if _has_index(table_name, index_name):
            op.drop_index(index_name, table_name=table_name)
