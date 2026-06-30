"""department management

Revision ID: 20260630_department_management
Revises: 20260630_remove_document_ai_toggle_fields
Create Date: 2026-06-30
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260630_department_management"
down_revision: str | None = "20260630_remove_document_ai_toggle_fields"
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


def _create_departments_table() -> None:
    if _has_table("departments"):
        return
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
        sa.Column("name", sa.String(length=100), nullable=False, comment="部门名称"),
        sa.Column("code", sa.String(length=100), nullable=False, comment="部门编码"),
        sa.Column("parent_id", sa.Integer(), nullable=True, comment="上级部门ID"),
        sa.Column("leader_user_id", sa.Integer(), nullable=True, comment="部门负责人用户ID"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序值"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="enabled", comment="状态"),
        sa.Column("description", sa.Text(), nullable=True, comment="备注"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false(), comment="是否删除"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="删除时间"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.ForeignKeyConstraint(["parent_id"], ["departments.id"]),
        sa.ForeignKeyConstraint(["leader_user_id"], ["users.id"]),
        sa.UniqueConstraint("code", name="uk_departments_code"),
        comment="部门表",
    )


def _seed_default_department() -> None:
    if not _has_table("departments"):
        return
    op.execute(
        sa.text(
            """
            INSERT INTO departments
                (name, code, parent_id, leader_user_id, sort_order, status, description, is_deleted, created_at, updated_at)
            SELECT
                '默认部门', 'DEFAULT', NULL, NULL, 0, 'enabled', '系统初始化默认部门', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            WHERE NOT EXISTS (SELECT 1 FROM departments WHERE code = 'DEFAULT')
            """
        )
    )


def upgrade() -> None:
    _create_departments_table()
    _create_index_if_missing("departments", "idx_departments_parent_id", ["parent_id"])
    _create_index_if_missing("departments", "idx_departments_status", ["status"])
    _create_index_if_missing("departments", "idx_departments_is_deleted", ["is_deleted"])
    _add_column_if_missing("users", lambda: sa.Column("department_id", sa.Integer(), nullable=True, comment="所属部门ID"))
    _create_index_if_missing("users", "idx_users_department_id", ["department_id"])
    _seed_default_department()


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported for department management migration")
