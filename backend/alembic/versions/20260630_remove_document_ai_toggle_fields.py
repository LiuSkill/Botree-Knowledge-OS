"""remove document AI toggle fields

Revision ID: 20260630_remove_document_ai_toggle_fields
Revises: 20260626_project_document_rbac_fields
Create Date: 2026-06-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260630_remove_document_ai_toggle_fields"
down_revision: str | None = "20260626_project_document_rbac_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOCUMENT_TOGGLE_COLUMN = "ai" + "_enabled"
DIRECTORY_TOGGLE_COLUMN = "default_" + DOCUMENT_TOGGLE_COLUMN
DOCUMENT_TOGGLE_INDEX = "idx_documents_" + DOCUMENT_TOGGLE_COLUMN


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return table_name in set(_inspector().get_table_names())


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return column_name in {column["name"] for column in _inspector().get_columns(table_name)}


def _drop_index_if_exists(table_name: str, index_name: str) -> None:
    if not _has_table(table_name):
        return
    if index_name not in {index["name"] for index in _inspector().get_indexes(table_name)}:
        return
    op.drop_index(index_name, table_name=table_name)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if not _has_column(table_name, column_name):
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.drop_column(column_name)


def upgrade() -> None:
    _drop_index_if_exists("documents", DOCUMENT_TOGGLE_INDEX)
    _drop_column_if_exists("knowledge_categories", DIRECTORY_TOGGLE_COLUMN)
    _drop_column_if_exists("documents", DOCUMENT_TOGGLE_COLUMN)
    _drop_column_if_exists("document_versions", DOCUMENT_TOGGLE_COLUMN)


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported for removing document AI toggle fields")
