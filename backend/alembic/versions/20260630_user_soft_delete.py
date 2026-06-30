"""user soft delete

Revision ID: 20260630_user_soft_delete
Revises: 20260630_department_management
Create Date: 2026-06-30
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260630_user_soft_delete"
down_revision: str | None = "20260630_department_management"
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


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return index_name in {index["name"] for index in _inspector().get_indexes(table_name)}


def _add_column_if_missing(table_name: str, column_factory: Callable[[], sa.Column]) -> None:
    column = column_factory()
    if _has_table(table_name) and not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    _add_column_if_missing(
        "users",
        lambda: sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false(), comment="是否删除"),
    )
    _add_column_if_missing(
        "users",
        lambda: sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="删除时间"),
    )
    if _has_table("users"):
        op.execute(sa.text("UPDATE users SET is_deleted = COALESCE(is_deleted, 0)"))
        _create_index_if_missing("users", "idx_users_is_deleted", ["is_deleted"])


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported for user soft delete migration")
