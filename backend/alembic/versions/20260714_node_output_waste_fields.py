"""add node output waste calculation fields

Revision ID: 20260714_node_output_waste_fields
Revises: 20260709_financial_calculator_data_models
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

revision: str = "20260714_node_output_waste_fields"
down_revision: str | None = "20260709_financial_calculator_data_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TEXT = sa.Text().with_variant(LONGTEXT(), "mysql")


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


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _has_table(table_name) and not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if _has_column(table_name, column_name):
        op.drop_column(table_name, column_name)


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(table_name: str, index_name: str) -> None:
    if _has_index(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    _add_column_if_missing(
        "process_node_outputs",
        sa.Column(
            "output_type",
            sa.String(length=30),
            nullable=False,
            server_default="product",
            comment="产出物类型：product/byproduct/solid_waste/wastewater",
        ),
    )
    _add_column_if_missing(
        "process_node_outputs",
        sa.Column("formula_type", sa.String(length=30), nullable=False, server_default="fixed", comment="系数类型：fixed/expression"),
    )
    _add_column_if_missing("process_node_outputs", sa.Column("expression", JSON_TEXT, nullable=True, comment="表达式系数"))
    _add_column_if_missing("process_node_outputs", sa.Column("scale_param", JSON_TEXT, nullable=True, comment="规模修正参数JSON"))
    _add_column_if_missing("process_node_outputs", sa.Column("source_template_id", sa.Integer(), nullable=True, comment="来源测算模板/导入批次ID"))
    _add_column_if_missing(
        "process_node_outputs",
        sa.Column("balance_weight", sa.Numeric(18, 6), nullable=False, server_default="0", comment="水平衡权重值"),
    )
    _add_column_if_missing(
        "process_node_outputs",
        sa.Column("treatment_cost", sa.Numeric(18, 6), nullable=False, server_default="0", comment="节点处理成本"),
    )
    _create_index_if_missing("process_node_outputs", "idx_process_node_outputs_output_type", ["output_type"])


def downgrade() -> None:
    _drop_index_if_exists("process_node_outputs", "idx_process_node_outputs_output_type")
    for column_name in (
        "treatment_cost",
        "balance_weight",
        "source_template_id",
        "scale_param",
        "expression",
        "formula_type",
        "output_type",
    ):
        _drop_column_if_exists("process_node_outputs", column_name)
