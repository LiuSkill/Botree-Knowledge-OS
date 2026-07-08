"""process configuration models

Revision ID: 20260708_process_config_models
Revises: 20260708_index_publish_composite_indexes
Create Date: 2026-07-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

revision: str = "20260708_process_config_models"
down_revision: str | None = "20260708_index_publish_composite_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROCESS_STATUS_COMMENT = "状态：enabled/draft/disabled"
JSON_TEXT = sa.Text().with_variant(LONGTEXT(), "mysql")

LIBRARY_TABLES: tuple[tuple[str, str, str], ...] = (
    ("process_materials", "uk_process_materials_code", "工艺配置原料库"),
    ("process_products", "uk_process_products_code", "工艺配置产品库"),
    ("process_consumables", "uk_process_consumables_code", "工艺配置消耗品库"),
    ("process_public_services", "uk_process_public_services_code", "工艺配置公共服务库"),
)

INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    ("process_materials", "idx_process_materials_type", ["type"]),
    ("process_materials", "idx_process_materials_status", ["status"]),
    ("process_materials", "idx_process_materials_sort_order", ["sort_order"]),
    ("process_materials", "idx_process_materials_is_deleted", ["is_deleted"]),
    ("process_materials", "idx_process_materials_deleted_at", ["deleted_at"]),
    ("process_products", "idx_process_products_type", ["type"]),
    ("process_products", "idx_process_products_status", ["status"]),
    ("process_products", "idx_process_products_sort_order", ["sort_order"]),
    ("process_products", "idx_process_products_is_deleted", ["is_deleted"]),
    ("process_products", "idx_process_products_deleted_at", ["deleted_at"]),
    ("process_consumables", "idx_process_consumables_type", ["type"]),
    ("process_consumables", "idx_process_consumables_status", ["status"]),
    ("process_consumables", "idx_process_consumables_sort_order", ["sort_order"]),
    ("process_consumables", "idx_process_consumables_is_deleted", ["is_deleted"]),
    ("process_consumables", "idx_process_consumables_deleted_at", ["deleted_at"]),
    ("process_public_services", "idx_process_public_services_type", ["type"]),
    ("process_public_services", "idx_process_public_services_status", ["status"]),
    ("process_public_services", "idx_process_public_services_sort_order", ["sort_order"]),
    ("process_public_services", "idx_process_public_services_is_deleted", ["is_deleted"]),
    ("process_public_services", "idx_process_public_services_deleted_at", ["deleted_at"]),
    ("process_region_prices", "idx_process_region_prices_owner", ["owner_type", "owner_id"]),
    ("process_region_prices", "idx_process_region_prices_region", ["region_code"]),
    ("process_region_prices", "idx_process_region_prices_status", ["status"]),
    ("process_region_prices", "idx_process_region_prices_is_deleted", ["is_deleted"]),
    ("process_region_prices", "idx_process_region_prices_deleted_at", ["deleted_at"]),
    ("process_nodes", "idx_process_nodes_node_type", ["node_type"]),
    ("process_nodes", "idx_process_nodes_status", ["status"]),
    ("process_nodes", "idx_process_nodes_sort_order", ["sort_order"]),
    ("process_nodes", "idx_process_nodes_is_deleted", ["is_deleted"]),
    ("process_nodes", "idx_process_nodes_deleted_at", ["deleted_at"]),
    ("process_node_material_inputs", "idx_process_node_material_inputs_node_id", ["node_id"]),
    ("process_node_material_inputs", "idx_process_node_material_inputs_material_id", ["material_id"]),
    ("process_node_material_inputs", "idx_process_node_material_inputs_is_deleted", ["is_deleted"]),
    ("process_node_material_inputs", "idx_process_node_material_inputs_deleted_at", ["deleted_at"]),
    ("process_node_consumables", "idx_process_node_consumables_node_id", ["node_id"]),
    ("process_node_consumables", "idx_process_node_consumables_consumable_id", ["consumable_id"]),
    ("process_node_consumables", "idx_process_node_consumables_is_deleted", ["is_deleted"]),
    ("process_node_consumables", "idx_process_node_consumables_deleted_at", ["deleted_at"]),
    ("process_node_public_services", "idx_process_node_public_services_node_id", ["node_id"]),
    ("process_node_public_services", "idx_process_node_public_services_service_id", ["public_service_id"]),
    ("process_node_public_services", "idx_process_node_public_services_is_deleted", ["is_deleted"]),
    ("process_node_public_services", "idx_process_node_public_services_deleted_at", ["deleted_at"]),
    ("process_node_equipment", "idx_process_node_equipment_node_id", ["node_id"]),
    ("process_node_equipment", "idx_process_node_equipment_is_deleted", ["is_deleted"]),
    ("process_node_equipment", "idx_process_node_equipment_deleted_at", ["deleted_at"]),
    ("process_node_outputs", "idx_process_node_outputs_node_id", ["node_id"]),
    ("process_node_outputs", "idx_process_node_outputs_product_id", ["product_id"]),
    ("process_node_outputs", "idx_process_node_outputs_is_deleted", ["is_deleted"]),
    ("process_node_outputs", "idx_process_node_outputs_deleted_at", ["deleted_at"]),
    ("process_routes", "idx_process_routes_input_material_id", ["input_material_id"]),
    ("process_routes", "idx_process_routes_final_product_id", ["final_product_id"]),
    ("process_routes", "idx_process_routes_status", ["status"]),
    ("process_routes", "idx_process_routes_sort_order", ["sort_order"]),
    ("process_routes", "idx_process_routes_is_deleted", ["is_deleted"]),
    ("process_routes", "idx_process_routes_deleted_at", ["deleted_at"]),
    ("process_route_nodes", "idx_process_route_nodes_route_id", ["route_id"]),
    ("process_route_nodes", "idx_process_route_nodes_node_id", ["node_id"]),
    ("process_route_nodes", "idx_process_route_nodes_sort_order", ["sort_order"]),
    ("process_route_nodes", "idx_process_route_nodes_is_deleted", ["is_deleted"]),
    ("process_route_nodes", "idx_process_route_nodes_deleted_at", ["deleted_at"]),
    ("process_route_versions", "idx_process_route_versions_route_id", ["route_id"]),
    ("process_route_versions", "idx_process_route_versions_version_no", ["version_no"]),
    ("process_route_versions", "idx_process_route_versions_is_deleted", ["is_deleted"]),
    ("process_route_versions", "idx_process_route_versions_deleted_at", ["deleted_at"]),
)


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return table_name in set(_inspector().get_table_names())


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


def _drop_table_if_exists(table_name: str) -> None:
    if _has_table(table_name):
        op.drop_table(table_name)


def _create_library_table(table_name: str, unique_name: str, comment: str) -> None:
    if _has_table(table_name):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
        sa.Column("code", sa.String(length=100), nullable=False, comment="编码"),
        sa.Column("name", sa.String(length=150), nullable=False, comment="名称"),
        sa.Column("type", sa.String(length=100), nullable=False, comment="类型"),
        sa.Column("description", sa.Text(), nullable=True, comment="描述信息"),
        sa.Column("unit", sa.String(length=50), nullable=False, comment="单位"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="enabled", comment=PROCESS_STATUS_COMMENT),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序值"),
        sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
        *_operator_columns(),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        *_operator_foreign_keys(),
        sa.UniqueConstraint("code", name=unique_name),
        comment=comment,
    )


def _create_region_prices_table() -> None:
    if _has_table("process_region_prices"):
        return
    op.create_table(
        "process_region_prices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
        sa.Column("owner_type", sa.String(length=30), nullable=False, comment="归属类型：material/product/consumable/public_service"),
        sa.Column("owner_id", sa.Integer(), nullable=False, comment="归属基础库ID"),
        sa.Column("region_code", sa.String(length=30), nullable=False, comment="区域编码：asia/europe/americas"),
        sa.Column("region_name", sa.String(length=100), nullable=False, comment="区域名称"),
        sa.Column("currency", sa.String(length=10), nullable=False, comment="币种：CNY/EUR/USD"),
        sa.Column("unit_price", sa.Numeric(18, 6), nullable=False, server_default="0", comment="单位价格"),
        sa.Column("unit", sa.String(length=50), nullable=False, comment="计价单位"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="enabled", comment=PROCESS_STATUS_COMMENT),
        *_operator_columns(),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        *_operator_foreign_keys(),
        comment="工艺配置区域单价表",
    )


def _create_nodes_table() -> None:
    if _has_table("process_nodes"):
        return
    op.create_table(
        "process_nodes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
        sa.Column("code", sa.String(length=100), nullable=False, comment="节点编码"),
        sa.Column("name", sa.String(length=150), nullable=False, comment="节点名称"),
        sa.Column(
            "node_type",
            sa.String(length=50),
            nullable=False,
            comment="节点类型：pretreatment/hydrometallurgy/pyrometallurgy/post_treatment",
        ),
        sa.Column("staff", sa.Numeric(12, 4), nullable=False, server_default="0", comment="人员数量"),
        sa.Column("area", sa.Numeric(18, 4), nullable=False, server_default="0", comment="占地面积"),
        sa.Column("description", sa.Text(), nullable=True, comment="描述信息"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft", comment=PROCESS_STATUS_COMMENT),
        sa.Column("version", sa.String(length=50), nullable=False, server_default="1.0", comment="版本号"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序值"),
        sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
        *_operator_columns(),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        *_operator_foreign_keys(),
        sa.UniqueConstraint("code", name="uk_process_nodes_code"),
        comment="工艺节点库",
    )


def _create_node_relation_tables() -> None:
    if not _has_table("process_node_material_inputs"):
        op.create_table(
            "process_node_material_inputs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
            sa.Column("node_id", sa.Integer(), nullable=False, comment="工艺节点ID"),
            sa.Column("material_id", sa.Integer(), nullable=False, comment="原料ID"),
            sa.Column("amount_per_ton", sa.Numeric(18, 6), nullable=False, server_default="0", comment="每吨原料投入量"),
            sa.Column("unit", sa.String(length=50), nullable=False, comment="单位"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序值"),
            sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
            *_timestamp_columns(),
            *_soft_delete_columns(),
            sa.ForeignKeyConstraint(["node_id"], ["process_nodes.id"]),
            sa.ForeignKeyConstraint(["material_id"], ["process_materials.id"]),
            comment="工艺节点输入原料",
        )

    if not _has_table("process_node_consumables"):
        op.create_table(
            "process_node_consumables",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
            sa.Column("node_id", sa.Integer(), nullable=False, comment="工艺节点ID"),
            sa.Column("consumable_id", sa.Integer(), nullable=False, comment="消耗品ID"),
            sa.Column("amount_per_ton", sa.Numeric(18, 6), nullable=False, server_default="0", comment="每吨原料消耗量"),
            sa.Column("unit", sa.String(length=50), nullable=False, comment="单位"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序值"),
            sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
            *_timestamp_columns(),
            *_soft_delete_columns(),
            sa.ForeignKeyConstraint(["node_id"], ["process_nodes.id"]),
            sa.ForeignKeyConstraint(["consumable_id"], ["process_consumables.id"]),
            comment="工艺节点消耗品用量",
        )

    if not _has_table("process_node_public_services"):
        op.create_table(
            "process_node_public_services",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
            sa.Column("node_id", sa.Integer(), nullable=False, comment="工艺节点ID"),
            sa.Column("public_service_id", sa.Integer(), nullable=False, comment="公共服务ID"),
            sa.Column("amount_per_ton", sa.Numeric(18, 6), nullable=False, server_default="0", comment="每吨原料消耗量"),
            sa.Column("unit", sa.String(length=50), nullable=False, comment="单位"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序值"),
            sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
            *_timestamp_columns(),
            *_soft_delete_columns(),
            sa.ForeignKeyConstraint(["node_id"], ["process_nodes.id"]),
            sa.ForeignKeyConstraint(["public_service_id"], ["process_public_services.id"]),
            comment="工艺节点公共服务消耗",
        )

    if not _has_table("process_node_equipment"):
        op.create_table(
            "process_node_equipment",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
            sa.Column("node_id", sa.Integer(), nullable=False, comment="工艺节点ID"),
            sa.Column("equipment_name", sa.String(length=150), nullable=False, comment="设备名称"),
            sa.Column("equipment_type", sa.String(length=100), nullable=True, comment="设备类型"),
            sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0", comment="设备数量"),
            sa.Column("investment_amount", sa.Numeric(18, 2), nullable=False, server_default="0", comment="投资金额"),
            sa.Column("currency", sa.String(length=10), nullable=False, server_default="CNY", comment="币种"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序值"),
            sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
            *_timestamp_columns(),
            *_soft_delete_columns(),
            sa.ForeignKeyConstraint(["node_id"], ["process_nodes.id"]),
            comment="工艺节点设备投资",
        )

    if not _has_table("process_node_outputs"):
        op.create_table(
            "process_node_outputs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
            sa.Column("node_id", sa.Integer(), nullable=False, comment="工艺节点ID"),
            sa.Column("product_id", sa.Integer(), nullable=False, comment="产品ID"),
            sa.Column("output_per_ton", sa.Numeric(18, 6), nullable=False, server_default="0", comment="每吨原料产出量"),
            sa.Column("unit", sa.String(length=50), nullable=False, comment="单位"),
            sa.Column("is_main_product", sa.Boolean(), nullable=False, server_default=sa.false(), comment="是否主产品"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序值"),
            sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
            *_timestamp_columns(),
            *_soft_delete_columns(),
            sa.ForeignKeyConstraint(["node_id"], ["process_nodes.id"]),
            sa.ForeignKeyConstraint(["product_id"], ["process_products.id"]),
            comment="工艺节点输出产品",
        )


def _create_routes_table() -> None:
    if _has_table("process_routes"):
        return
    op.create_table(
        "process_routes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
        sa.Column("code", sa.String(length=100), nullable=False, comment="路线编码"),
        sa.Column("name", sa.String(length=150), nullable=False, comment="路线名称"),
        sa.Column("input_material_id", sa.Integer(), nullable=False, comment="输入原料ID"),
        sa.Column("final_product_id", sa.Integer(), nullable=False, comment="最终产品ID"),
        sa.Column("version", sa.String(length=50), nullable=False, server_default="1.0", comment="版本号"),
        sa.Column("description", sa.Text(), nullable=True, comment="描述信息"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft", comment=PROCESS_STATUS_COMMENT),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序值"),
        sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
        *_operator_columns(),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        *_operator_foreign_keys(),
        sa.ForeignKeyConstraint(["input_material_id"], ["process_materials.id"]),
        sa.ForeignKeyConstraint(["final_product_id"], ["process_products.id"]),
        sa.UniqueConstraint("code", name="uk_process_routes_code"),
        comment="工艺路线库",
    )


def _create_route_relation_tables() -> None:
    if not _has_table("process_route_nodes"):
        op.create_table(
            "process_route_nodes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
            sa.Column("route_id", sa.Integer(), nullable=False, comment="工艺路线ID"),
            sa.Column("node_id", sa.Integer(), nullable=False, comment="工艺节点ID"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序值"),
            sa.Column("node_params_json", JSON_TEXT, nullable=True, comment="节点参数JSON"),
            sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
            *_timestamp_columns(),
            *_soft_delete_columns(),
            sa.ForeignKeyConstraint(["route_id"], ["process_routes.id"]),
            sa.ForeignKeyConstraint(["node_id"], ["process_nodes.id"]),
            comment="工艺路线节点链路",
        )

    if not _has_table("process_route_versions"):
        op.create_table(
            "process_route_versions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
            sa.Column("route_id", sa.Integer(), nullable=False, comment="工艺路线ID"),
            sa.Column("version_no", sa.Integer(), nullable=False, comment="版本序号"),
            sa.Column("snapshot_json", JSON_TEXT, nullable=False, comment="路线快照JSON"),
            sa.Column("change_log", sa.Text(), nullable=True, comment="变更说明"),
            sa.Column("created_by", sa.Integer(), nullable=True, comment="创建人ID，关联users.id"),
            *_timestamp_columns(),
            *_soft_delete_columns(),
            sa.ForeignKeyConstraint(["route_id"], ["process_routes.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            comment="工艺路线版本快照",
        )


def upgrade() -> None:
    for table_name, unique_name, comment in LIBRARY_TABLES:
        _create_library_table(table_name, unique_name, comment)
    _create_region_prices_table()
    _create_nodes_table()
    _create_node_relation_tables()
    _create_routes_table()
    _create_route_relation_tables()

    for table_name, index_name, column_names in INDEXES:
        _create_index_if_missing(table_name, index_name, column_names)


def downgrade() -> None:
    for table_name in (
        "process_route_versions",
        "process_route_nodes",
        "process_routes",
        "process_node_outputs",
        "process_node_equipment",
        "process_node_public_services",
        "process_node_consumables",
        "process_node_material_inputs",
        "process_nodes",
        "process_region_prices",
        "process_public_services",
        "process_consumables",
        "process_products",
        "process_materials",
    ):
        _drop_table_if_exists(table_name)
