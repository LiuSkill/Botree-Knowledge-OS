"""upsert mixed acid residue downstream routes

Revision ID: 20260814_mixed_acid_residue_routes
Revises: 20260813_process_route_semantics
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_mixed_acid_residue_routes"
down_revision: str | None = "20260813_process_route_semantics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MIXED_ACID_RESIDUE_PREFIXES = (
    "A1-B1-B2-B8",
)


def _bind() -> sa.Connection:
    return op.get_bind()


def _inspector() -> sa.Inspector:
    return sa.inspect(_bind())


def _has_table(table_name: str) -> bool:
    return table_name in set(_inspector().get_table_names())


def _table(table_name: str) -> sa.Table:
    return sa.Table(table_name, sa.MetaData(), autoload_with=_bind())


def _optional_values(table: sa.Table, values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if key in table.c}


def _decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def _load_default_config() -> dict[str, Any]:
    defaults_path = Path(__file__).resolve().parents[2] / "app" / "core" / "process_config_defaults.json"
    return json.loads(defaults_path.read_text(encoding="utf-8"))


def _load_default_routes() -> list[dict[str, Any]]:
    return list(_load_default_config().get("routes", []))


def _load_default_nodes() -> list[dict[str, Any]]:
    return list(_load_default_config().get("nodes", []))


def _load_default_products() -> list[dict[str, Any]]:
    return list(_load_default_config().get("products", []))


def _id_by_code(table: sa.Table) -> dict[str, int]:
    rows = _bind().execute(
        sa.select(table.c.id, table.c.code).where(table.c.is_deleted.is_(False))
    )
    return {str(row.code): int(row.id) for row in rows}


def _insert_product_region_prices(
    product_row: dict[str, Any],
    *,
    product_id: int,
    region_prices: sa.Table | None,
    now: datetime,
) -> None:
    if region_prices is None:
        return
    for child in product_row.get("region_prices", []):
        values = _optional_values(
            region_prices,
            {
                "owner_type": "product",
                "owner_id": product_id,
                "region_code": child["region_code"],
                "region_name": child["region_name"],
                "currency": child["currency"],
                "unit_price": _decimal(child.get("unit_price")),
                "unit": child["unit"],
                "status": child.get("status") or "enabled",
                "created_at": now,
                "updated_at": now,
                "created_by": None,
                "updated_by": None,
                "is_deleted": False,
                "deleted_at": None,
            },
        )
        _bind().execute(region_prices.insert().values(**values))


def _upsert_missing_product(
    product_row: dict[str, Any],
    *,
    products: sa.Table,
    region_prices: sa.Table | None,
    now: datetime,
) -> int:
    product_code = str(product_row["code"])
    existing = _bind().execute(
        sa.select(products.c.id, products.c.is_deleted).where(products.c.code == product_code).limit(1)
    ).first()
    product_values = _optional_values(
        products,
        {
            "code": product_code,
            "name": product_row["name"],
            "type": product_row["type"],
            "description": product_row.get("description"),
            "unit": product_row.get("unit") or "",
            "status": product_row.get("status") or "enabled",
            "sort_order": int(product_row.get("sort_order") or 0),
            "remark": product_row.get("remark"),
            "output_type": product_row.get("output_type") or "product",
            "target_output_category": product_row.get("target_output_category"),
            "is_product_form": bool(product_row.get("is_product_form", True)),
            "spec": product_row.get("spec"),
            "treatment_cost": _decimal(product_row.get("treatment_cost")),
            "is_deleted": False,
            "deleted_at": None,
            "updated_at": now,
            "updated_by": None,
        },
    )
    if existing is None:
        product_values = _optional_values(
            products,
            {
                **product_values,
                "created_at": now,
                "created_by": None,
            },
        )
        result = _bind().execute(products.insert().values(**product_values))
        product_id = int(result.inserted_primary_key[0])
        _insert_product_region_prices(product_row, product_id=product_id, region_prices=region_prices, now=now)
        return product_id
    product_id = int(existing.id)
    if bool(existing.is_deleted):
        _bind().execute(products.update().where(products.c.id == product_id).values(**product_values))
    return product_id


def _soft_delete_children(table: sa.Table, route_id: int, now: datetime) -> None:
    values = _optional_values(
        table,
        {
            "is_deleted": True,
            "deleted_at": now,
            "updated_at": now,
        },
    )
    if values:
        _bind().execute(
            table.update()
            .where(table.c.route_id == route_id, table.c.is_deleted.is_(False))
            .values(**values)
        )


def _soft_delete_legacy_invalid_mixed_acid_routes(
    *,
    routes: sa.Table,
    route_nodes: sa.Table,
    nodes: sa.Table,
    calculation_outputs: sa.Table,
    now: datetime,
) -> None:
    route_rows = list(_bind().execute(
        sa.select(routes.c.id).where(
            routes.c.is_deleted.is_(False),
            routes.c.status == "enabled",
        )
    ))
    for route_row in route_rows:
        node_rows = _bind().execute(
            sa.select(nodes.c.code)
            .select_from(route_nodes.join(nodes, route_nodes.c.node_id == nodes.c.id))
            .where(
                route_nodes.c.route_id == route_row.id,
                route_nodes.c.is_deleted.is_(False),
                nodes.c.is_deleted.is_(False),
            )
        )
        node_codes = {str(row.code) for row in node_rows}
        if "A1" not in node_codes:
            continue
        if "A2" not in node_codes and "B1" in node_codes and "B2" in node_codes:
            continue
        _bind().execute(
            routes.update()
            .where(routes.c.id == route_row.id)
            .values(**_optional_values(routes, {"is_deleted": True, "deleted_at": now, "updated_at": now}))
        )
        _soft_delete_children(route_nodes, int(route_row.id), now)
        _soft_delete_children(calculation_outputs, int(route_row.id), now)


def _is_generated_default_route_code(route_code: str) -> bool:
    parts = route_code.split("-")
    return len(parts) > 1 and all(part[:1].isalpha() and part[1:].isdigit() for part in parts)


def _soft_delete_obsolete_generated_routes(
    *,
    routes: sa.Table,
    route_nodes: sa.Table,
    calculation_outputs: sa.Table,
    default_route_codes: set[str],
    now: datetime,
) -> None:
    route_rows = list(_bind().execute(
        sa.select(routes.c.id, routes.c.code).where(
            routes.c.is_deleted.is_(False),
            routes.c.status == "enabled",
        )
    ))
    for route_row in route_rows:
        route_code = str(route_row.code)
        if route_code in default_route_codes or not _is_generated_default_route_code(route_code):
            continue
        _bind().execute(
            routes.update()
            .where(routes.c.id == route_row.id)
            .values(**_optional_values(routes, {"is_deleted": True, "deleted_at": now, "updated_at": now}))
        )
        _soft_delete_children(route_nodes, int(route_row.id), now)
        _soft_delete_children(calculation_outputs, int(route_row.id), now)


def _upsert_route(
    route_row: dict[str, Any],
    *,
    routes: sa.Table,
    route_nodes: sa.Table,
    calculation_outputs: sa.Table,
    material_ids: dict[str, int],
    product_ids: dict[str, int],
    node_ids: dict[str, int],
    now: datetime,
) -> None:
    material_id = material_ids.get(route_row.get("input_material_code"))
    final_product_id = product_ids.get(route_row.get("final_product_code"))
    if material_id is None or final_product_id is None:
        return

    route_code = str(route_row["code"])
    existing = _bind().execute(
        sa.select(routes.c.id).where(routes.c.code == route_code).limit(1)
    ).first()
    route_values = _optional_values(
        routes,
        {
            "code": route_code,
            "name": route_row["name"],
            "input_material_id": material_id,
            "final_product_id": final_product_id,
            "version": route_row.get("version") or "V1",
            "description": route_row.get("description"),
            "status": route_row.get("status") or "enabled",
            "sort_order": int(route_row.get("sort_order") or 0),
            "remark": route_row.get("remark"),
            "is_deleted": False,
            "deleted_at": None,
            "updated_at": now,
        },
    )
    if existing is None:
        route_values = _optional_values(
            routes,
            {
                **route_values,
                "created_at": now,
                "created_by": None,
                "updated_by": None,
            },
        )
        result = _bind().execute(routes.insert().values(**route_values))
        route_id = int(result.inserted_primary_key[0])
    else:
        route_id = int(existing.id)
        _bind().execute(routes.update().where(routes.c.id == route_id).values(**route_values))
        _soft_delete_children(route_nodes, route_id, now)
        _soft_delete_children(calculation_outputs, route_id, now)

    for child in route_row.get("nodes", []):
        node_id = node_ids.get(child.get("node_code"))
        if node_id is None:
            continue
        values = _optional_values(
            route_nodes,
            {
                "route_id": route_id,
                "node_id": node_id,
                "sort_order": int(child.get("sort_order") or 0),
                "option_group_code": child.get("option_group_code"),
                "option_code": child.get("option_code"),
                "node_params_json": child.get("node_params_json"),
                "remark": child.get("remark"),
                "created_at": now,
                "updated_at": now,
                "is_deleted": False,
                "deleted_at": None,
            },
        )
        _bind().execute(route_nodes.insert().values(**values))

    for child in route_row.get("calculation_outputs", []):
        output_product_id = product_ids.get(child.get("product_code")) if child.get("product_code") else None
        values = _optional_values(
            calculation_outputs,
            {
                "route_id": route_id,
                "output_type": child["output_type"],
                "product_id": output_product_id,
                "output_name": child["output_name"],
                "spec": child.get("spec"),
                "formula_type": child.get("formula_type") or "fixed",
                "recovery_rate": _decimal(child.get("recovery_rate")),
                "balance_weight": _decimal(child.get("balance_weight")),
                "unit": child.get("unit") or "",
                "output_ratio": _decimal(child.get("output_ratio")),
                "expression": child.get("expression"),
                "scale_param": child.get("scale_param"),
                "treatment_cost": _decimal(child.get("treatment_cost")),
                "sort_order": int(child.get("sort_order") or 0),
                "remark": child.get("remark"),
                "created_at": now,
                "updated_at": now,
                "created_by": None,
                "updated_by": None,
                "is_deleted": False,
                "deleted_at": None,
            },
        )
        _bind().execute(calculation_outputs.insert().values(**values))


def _insert_node_outputs(
    node_row: dict[str, Any],
    *,
    node_id: int,
    node_outputs: sa.Table,
    product_ids: dict[str, int],
    now: datetime,
) -> None:
    for child in node_row.get("outputs", []):
        product_id = product_ids.get(child.get("product_code"))
        if product_id is None:
            continue
        values = _optional_values(
            node_outputs,
            {
                "node_id": node_id,
                "product_id": product_id,
                "output_type": child.get("output_type") or "product",
                "output_per_ton": _decimal(child.get("output_per_ton")),
                "formula_type": child.get("formula_type") or "fixed",
                "expression": child.get("expression"),
                "scale_param": child.get("scale_param"),
                "balance_weight": _decimal(child.get("balance_weight")),
                "treatment_cost": _decimal(child.get("treatment_cost")),
                "unit": child.get("unit") or "",
                "is_main_product": bool(child.get("is_main_product")),
                "sort_order": int(child.get("sort_order") or 0),
                "remark": child.get("remark"),
                "created_at": now,
                "updated_at": now,
                "created_by": None,
                "updated_by": None,
                "is_deleted": False,
                "deleted_at": None,
            },
        )
        _bind().execute(node_outputs.insert().values(**values))


def _upsert_missing_node(
    node_row: dict[str, Any],
    *,
    nodes: sa.Table,
    node_outputs: sa.Table,
    product_ids: dict[str, int],
    now: datetime,
) -> int | None:
    node_code = str(node_row["code"])
    existing = _bind().execute(
        sa.select(nodes.c.id, nodes.c.is_deleted).where(nodes.c.code == node_code).limit(1)
    ).first()
    if existing is not None and not bool(existing.is_deleted):
        return int(existing.id)

    node_values = _optional_values(
        nodes,
        {
            "code": node_code,
            "name": node_row["name"],
            "node_type": node_row.get("node_type") or "hydrometallurgy",
            "staff": _decimal(node_row.get("staff")),
            "area": _decimal(node_row.get("area")),
            "description": node_row.get("description"),
            "status": node_row.get("status") or "enabled",
            "version": node_row.get("version") or "V1",
            "sort_order": int(node_row.get("sort_order") or 0),
            "remark": node_row.get("remark"),
            "is_deleted": False,
            "deleted_at": None,
            "created_at": now,
            "updated_at": now,
            "created_by": None,
            "updated_by": None,
        },
    )
    if existing is None:
        result = _bind().execute(nodes.insert().values(**node_values))
        node_id = int(result.inserted_primary_key[0])
    else:
        node_id = int(existing.id)
        _bind().execute(nodes.update().where(nodes.c.id == node_id).values(**node_values))
    _insert_node_outputs(node_row, node_id=node_id, node_outputs=node_outputs, product_ids=product_ids, now=now)
    return node_id


def upgrade() -> None:
    required_tables = {
        "process_materials",
        "process_products",
        "process_nodes",
        "process_node_outputs",
        "process_routes",
        "process_route_nodes",
        "process_calculation_outputs",
    }
    if not all(_has_table(table_name) for table_name in required_tables):
        return

    materials = _table("process_materials")
    products = _table("process_products")
    nodes = _table("process_nodes")
    node_outputs = _table("process_node_outputs")
    routes = _table("process_routes")
    route_nodes = _table("process_route_nodes")
    calculation_outputs = _table("process_calculation_outputs")
    region_prices = _table("process_region_prices") if _has_table("process_region_prices") else None

    material_ids = _id_by_code(materials)
    node_ids = _id_by_code(nodes)
    if not material_ids:
        return

    now = datetime.now(UTC).replace(tzinfo=None)
    product_ids = _id_by_code(products)
    for product_row in _load_default_products():
        product_id = _upsert_missing_product(
            product_row,
            products=products,
            region_prices=region_prices,
            now=now,
        )
        product_ids[str(product_row["code"])] = product_id

    for node_row in _load_default_nodes():
        node_id = _upsert_missing_node(
            node_row,
            nodes=nodes,
            node_outputs=node_outputs,
            product_ids=product_ids,
            now=now,
        )
        if node_id is not None:
            node_ids[str(node_row["code"])] = node_id

    default_routes = _load_default_routes()
    for route_row in default_routes:
        _upsert_route(
            route_row,
            routes=routes,
            route_nodes=route_nodes,
            calculation_outputs=calculation_outputs,
            material_ids=material_ids,
            product_ids=product_ids,
            node_ids=node_ids,
            now=now,
        )
    _soft_delete_legacy_invalid_mixed_acid_routes(
        routes=routes,
        route_nodes=route_nodes,
        nodes=nodes,
        calculation_outputs=calculation_outputs,
        now=now,
    )
    _soft_delete_obsolete_generated_routes(
        routes=routes,
        route_nodes=route_nodes,
        calculation_outputs=calculation_outputs,
        default_route_codes={row["code"] for row in default_routes},
        now=now,
    )


def downgrade() -> None:
    if not all(_has_table(table_name) for table_name in ("process_routes", "process_route_nodes", "process_calculation_outputs")):
        return
    routes = _table("process_routes")
    route_nodes = _table("process_route_nodes")
    calculation_outputs = _table("process_calculation_outputs")
    now = datetime.now(UTC).replace(tzinfo=None)
    route_rows = _bind().execute(
        sa.select(routes.c.id, routes.c.code).where(
            routes.c.is_deleted.is_(False),
            sa.or_(*(routes.c.code.like(f"{prefix}%") for prefix in MIXED_ACID_RESIDUE_PREFIXES)),
        )
    ).all()
    for route_row in route_rows:
        route_id = int(route_row.id)
        _soft_delete_children(route_nodes, route_id, now)
        _soft_delete_children(calculation_outputs, route_id, now)
        _bind().execute(
            routes.update()
            .where(routes.c.id == route_id)
            .values(**_optional_values(routes, {"is_deleted": True, "deleted_at": now, "updated_at": now}))
        )
