"""financial calculator data model extensions

Revision ID: 20260709_financial_calculator_data_models
Revises: 20260708_process_config_models
Create Date: 2026-07-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

revision: str = "20260709_financial_calculator_data_models"
down_revision: str | None = "20260708_process_config_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TEXT = sa.Text().with_variant(LONGTEXT(), "mysql")


def _ensure_alembic_version_capacity() -> None:
    """Widen Alembic's default revision column before storing long revision IDs."""

    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return
    version_columns = {
        column["name"]: column
        for column in sa.inspect(bind).get_columns("alembic_version")
    }
    version_column = version_columns.get("version_num")
    current_length = getattr(version_column.get("type"), "length", None) if version_column else None
    if current_length is not None and current_length < 128:
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=current_length),
            type_=sa.String(length=128),
            existing_nullable=False,
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


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="更新时间"),
    ]


def _soft_delete_columns() -> list[sa.Column]:
    return [
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false(), comment="是否删除"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="删除时间"),
    ]


def _operator_columns(include_updated: bool = True) -> list[sa.Column]:
    columns = [sa.Column("created_by", sa.Integer(), nullable=True, comment="创建人ID，关联users.id")]
    if include_updated:
        columns.append(sa.Column("updated_by", sa.Integer(), nullable=True, comment="更新人ID，关联users.id"))
    return columns


def _operator_foreign_keys(include_updated: bool = True) -> list[sa.ForeignKeyConstraint]:
    constraints = [sa.ForeignKeyConstraint(["created_by"], ["users.id"])]
    if include_updated:
        constraints.append(sa.ForeignKeyConstraint(["updated_by"], ["users.id"]))
    return constraints


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(table_name: str, index_name: str) -> None:
    if _has_index(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _has_table(table_name) and not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if _has_column(table_name, column_name):
        op.drop_column(table_name, column_name)


def _drop_table_if_exists(table_name: str) -> None:
    if _has_table(table_name):
        op.drop_table(table_name)


def _create_material_compositions_table() -> None:
    if _has_table("process_material_compositions"):
        return
    op.create_table(
        "process_material_compositions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
        sa.Column("material_id", sa.Integer(), nullable=False, comment="原料ID"),
        sa.Column("element_code", sa.String(length=30), nullable=False, comment="元素编码"),
        sa.Column("element_name", sa.String(length=100), nullable=False, comment="元素名称"),
        sa.Column("content_ratio", sa.Numeric(18, 6), nullable=False, server_default="0", comment="含量比例"),
        sa.Column("unit", sa.String(length=50), nullable=False, server_default="%", comment="单位"),
        sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
        *_operator_columns(),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        *_operator_foreign_keys(),
        sa.ForeignKeyConstraint(["material_id"], ["process_materials.id"]),
        comment="工艺配置原料元素组成",
    )


def _create_calculation_outputs_table() -> None:
    if _has_table("process_calculation_outputs"):
        return
    op.create_table(
        "process_calculation_outputs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
        sa.Column("route_id", sa.Integer(), nullable=False, comment="工艺路线ID"),
        sa.Column("output_type", sa.String(length=30), nullable=False, comment="产出类型：product/byproduct/solid_waste/wastewater"),
        sa.Column("product_id", sa.Integer(), nullable=True, comment="产品库ID"),
        sa.Column("output_name", sa.String(length=150), nullable=False, comment="产出物名称"),
        sa.Column("spec", sa.String(length=100), nullable=True, comment="规格"),
        sa.Column("formula_type", sa.String(length=30), nullable=False, server_default="fixed", comment="系数类型：fixed/expression"),
        sa.Column("recovery_rate", sa.Numeric(18, 6), nullable=False, server_default="0", comment="收率"),
        sa.Column("balance_weight", sa.Numeric(18, 6), nullable=False, server_default="0", comment="水平衡权重值"),
        sa.Column("unit", sa.String(length=50), nullable=False, comment="单位"),
        sa.Column("output_ratio", sa.Numeric(18, 6), nullable=False, server_default="0", comment="产出系数"),
        sa.Column("expression", JSON_TEXT, nullable=True, comment="表达式系数"),
        sa.Column("scale_param", JSON_TEXT, nullable=True, comment="规模修正参数JSON"),
        sa.Column("treatment_cost", sa.Numeric(18, 6), nullable=False, server_default="0", comment="处理成本"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序值"),
        sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
        *_operator_columns(),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        *_operator_foreign_keys(),
        sa.ForeignKeyConstraint(["route_id"], ["process_routes.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["process_products.id"]),
        comment="快速财务计算器路线产出系数",
    )


def _create_calculation_import_batches_table() -> None:
    if _has_table("process_calculation_import_batches"):
        return
    op.create_table(
        "process_calculation_import_batches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
        sa.Column("file_name", sa.String(length=255), nullable=False, comment="原始文件名"),
        sa.Column("file_path", sa.String(length=500), nullable=True, comment="文件保存路径"),
        sa.Column("import_type", sa.String(length=50), nullable=False, comment="导入类型"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending", comment="状态：pending/success/failed/partial_success"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0", comment="成功数量"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0", comment="失败数量"),
        sa.Column("error_message", JSON_TEXT, nullable=True, comment="错误信息"),
        *_operator_columns(),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        *_operator_foreign_keys(),
        comment="快速财务计算器Excel导入批次",
    )


def _extend_products_table() -> None:
    _add_column_if_missing(
        "process_products",
        sa.Column("output_type", sa.String(length=30), nullable=False, server_default="product", comment="产出物类型：product/byproduct/solid_waste/wastewater"),
    )
    _add_column_if_missing("process_products", sa.Column("spec", sa.String(length=100), nullable=True, comment="规格"))
    _add_column_if_missing(
        "process_products",
        sa.Column("treatment_cost", sa.Numeric(18, 6), nullable=False, server_default="0", comment="处理成本"),
    )


def _extend_node_consumption_table(table_name: str) -> None:
    _add_column_if_missing(table_name, sa.Column("formula_type", sa.String(length=30), nullable=False, server_default="fixed", comment="系数类型：fixed/expression"))
    _add_column_if_missing(table_name, sa.Column("amount_per_ton_bm", sa.Numeric(18, 6), nullable=False, server_default="0", comment="每吨黑粉BM消耗系数"))
    _add_column_if_missing(table_name, sa.Column("expression", JSON_TEXT, nullable=True, comment="表达式系数"))
    _add_column_if_missing(table_name, sa.Column("scale_param", JSON_TEXT, nullable=True, comment="规模修正参数JSON"))
    _add_column_if_missing(table_name, sa.Column("source_template_id", sa.Integer(), nullable=True, comment="来源测算模板/导入批次ID"))
    _add_column_if_missing(table_name, sa.Column("balance_weight", sa.Numeric(18, 6), nullable=False, server_default="0", comment="水平衡权重值"))


def _backfill_node_bm_amount(table_name: str) -> None:
    if _has_column(table_name, "amount_per_ton") and _has_column(table_name, "amount_per_ton_bm"):
        op.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET amount_per_ton_bm = amount_per_ton
                WHERE amount_per_ton_bm IS NULL OR amount_per_ton_bm = 0
                """
            )
        )


def upgrade() -> None:
    _ensure_alembic_version_capacity()
    _create_material_compositions_table()
    _create_calculation_outputs_table()
    _create_calculation_import_batches_table()
    _extend_products_table()
    _extend_node_consumption_table("process_node_consumables")
    _extend_node_consumption_table("process_node_public_services")
    _backfill_node_bm_amount("process_node_consumables")
    _backfill_node_bm_amount("process_node_public_services")

    for table_name, index_name, columns in (
        ("process_products", "idx_process_products_output_type", ["output_type"]),
        ("process_material_compositions", "idx_process_material_compositions_material_id", ["material_id"]),
        ("process_material_compositions", "idx_process_material_compositions_element_code", ["element_code"]),
        ("process_material_compositions", "idx_process_material_compositions_is_deleted", ["is_deleted"]),
        ("process_material_compositions", "idx_process_material_compositions_deleted_at", ["deleted_at"]),
        ("process_calculation_outputs", "idx_process_calculation_outputs_route_id", ["route_id"]),
        ("process_calculation_outputs", "idx_process_calculation_outputs_product_id", ["product_id"]),
        ("process_calculation_outputs", "idx_process_calculation_outputs_output_type", ["output_type"]),
        ("process_calculation_outputs", "idx_process_calculation_outputs_sort_order", ["sort_order"]),
        ("process_calculation_outputs", "idx_process_calculation_outputs_is_deleted", ["is_deleted"]),
        ("process_calculation_outputs", "idx_process_calculation_outputs_deleted_at", ["deleted_at"]),
        ("process_calculation_import_batches", "idx_process_calculation_import_batches_import_type", ["import_type"]),
        ("process_calculation_import_batches", "idx_process_calculation_import_batches_status", ["status"]),
        ("process_calculation_import_batches", "idx_process_calculation_import_batches_created_by", ["created_by"]),
        ("process_calculation_import_batches", "idx_process_calculation_import_batches_is_deleted", ["is_deleted"]),
        ("process_calculation_import_batches", "idx_process_calculation_import_batches_deleted_at", ["deleted_at"]),
    ):
        _create_index_if_missing(table_name, index_name, columns)


def downgrade() -> None:
    for table_name, index_name in (
        ("process_products", "idx_process_products_output_type"),
        ("process_material_compositions", "idx_process_material_compositions_material_id"),
        ("process_material_compositions", "idx_process_material_compositions_element_code"),
        ("process_material_compositions", "idx_process_material_compositions_is_deleted"),
        ("process_material_compositions", "idx_process_material_compositions_deleted_at"),
        ("process_calculation_outputs", "idx_process_calculation_outputs_route_id"),
        ("process_calculation_outputs", "idx_process_calculation_outputs_product_id"),
        ("process_calculation_outputs", "idx_process_calculation_outputs_output_type"),
        ("process_calculation_outputs", "idx_process_calculation_outputs_sort_order"),
        ("process_calculation_outputs", "idx_process_calculation_outputs_is_deleted"),
        ("process_calculation_outputs", "idx_process_calculation_outputs_deleted_at"),
        ("process_calculation_import_batches", "idx_process_calculation_import_batches_import_type"),
        ("process_calculation_import_batches", "idx_process_calculation_import_batches_status"),
        ("process_calculation_import_batches", "idx_process_calculation_import_batches_created_by"),
        ("process_calculation_import_batches", "idx_process_calculation_import_batches_is_deleted"),
        ("process_calculation_import_batches", "idx_process_calculation_import_batches_deleted_at"),
    ):
        _drop_index_if_exists(table_name, index_name)

    _drop_table_if_exists("process_calculation_import_batches")
    _drop_table_if_exists("process_calculation_outputs")
    _drop_table_if_exists("process_material_compositions")

    for table_name in ("process_node_public_services", "process_node_consumables"):
        for column_name in ("balance_weight", "source_template_id", "scale_param", "expression", "amount_per_ton_bm", "formula_type"):
            _drop_column_if_exists(table_name, column_name)

    for column_name in ("treatment_cost", "spec", "output_type"):
        _drop_column_if_exists("process_products", column_name)
