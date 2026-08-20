"""add complete route semantics to process config

Revision ID: 20260813_process_route_semantics
Revises: 20260812_knowledge_category_i18n_names
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_process_route_semantics"
down_revision: str | None = "20260812_knowledge_category_i18n_names"
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


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _has_table(table_name) and not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if _has_column(table_name, column_name):
        op.drop_column(table_name, column_name)


def upgrade() -> None:
    _add_column_if_missing(
        "process_products",
        sa.Column("target_output_category", sa.String(length=30), nullable=True, comment="产品需求分类: li/ni/co/mn/cu/graphite"),
    )
    _add_column_if_missing(
        "process_products",
        sa.Column("is_product_form", sa.Boolean(), nullable=False, server_default=sa.true(), comment="是否达到产品形态"),
    )
    _add_column_if_missing(
        "process_route_nodes",
        sa.Column("option_group_code", sa.String(length=100), nullable=True, comment="互斥工艺选项组编码"),
    )
    _add_column_if_missing(
        "process_route_nodes",
        sa.Column("option_code", sa.String(length=100), nullable=True, comment="已选工艺选项编码"),
    )


def downgrade() -> None:
    for column_name in ("option_code", "option_group_code"):
        _drop_column_if_exists("process_route_nodes", column_name)
    for column_name in ("is_product_form", "target_output_category"):
        _drop_column_if_exists("process_products", column_name)
