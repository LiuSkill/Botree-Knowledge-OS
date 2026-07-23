"""快速财务计算器批量查询仓储。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.process_config import (
    ProcessCalculationOutput,
    ProcessAsset,
    ProcessConsumable,
    ProcessLaborCost,
    ProcessMaterial,
    ProcessMaterialComposition,
    ProcessNode,
    ProcessNodeConsumable,
    ProcessNodeEquipment,
    ProcessNodeLabor,
    ProcessNodeOutput,
    ProcessNodePublicService,
    ProcessProduct,
    ProcessPublicService,
    ProcessRegionPrice,
    ProcessRoute,
    ProcessRouteNode,
)


class ProcessCalculatorRepository:
    """集中加载一次测算所需数据，查询次数不随路线或节点数量增长。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_options(self) -> dict[str, list[Any]]:
        materials = list(
            self.db.scalars(
                select(ProcessMaterial)
                .where(ProcessMaterial.is_deleted.is_(False), ProcessMaterial.status == "enabled")
                .order_by(ProcessMaterial.sort_order.asc(), ProcessMaterial.id.asc())
            ).all()
        )
        products = list(
            self.db.scalars(
                select(ProcessProduct)
                .where(
                    ProcessProduct.is_deleted.is_(False),
                    ProcessProduct.status == "enabled",
                    ProcessProduct.output_type.in_(("product", "byproduct")),
                )
                .order_by(ProcessProduct.sort_order.asc(), ProcessProduct.id.asc())
            ).all()
        )
        return {"materials": materials, "products": products}

    def load_calculation_data(self, material_ids: set[int], product_ids: set[int], region_code: str) -> dict[str, list[Any]]:
        """按输入集合批量加载全部依赖，禁止在 Service 循环内访问数据库。"""

        materials = list(
            self.db.scalars(
                select(ProcessMaterial).where(
                    ProcessMaterial.id.in_(material_ids),
                    ProcessMaterial.is_deleted.is_(False),
                    ProcessMaterial.status == "enabled",
                )
            ).all()
        )
        target_products = list(
            self.db.scalars(
                select(ProcessProduct).where(
                    ProcessProduct.id.in_(product_ids),
                    ProcessProduct.is_deleted.is_(False),
                    ProcessProduct.status == "enabled",
                    ProcessProduct.output_type.in_(("product", "byproduct")),
                )
            ).all()
        )
        routes = list(
            self.db.scalars(
                select(ProcessRoute)
                .where(
                    ProcessRoute.input_material_id.in_(material_ids),
                    ProcessRoute.final_product_id.in_(product_ids),
                    ProcessRoute.is_deleted.is_(False),
                    ProcessRoute.status == "enabled",
                )
                .order_by(ProcessRoute.sort_order.asc(), ProcessRoute.id.asc())
            ).all()
        )
        route_ids = [route.id for route in routes]
        route_nodes = self._list_route_nodes(route_ids)
        node_ids = sorted({item.node_id for item in route_nodes})
        nodes = self._list_active(ProcessNode, node_ids)
        consumptions = self._list_node_children(ProcessNodeConsumable, node_ids)
        public_services = self._list_node_children(ProcessNodePublicService, node_ids)
        equipment = self._list_node_children(ProcessNodeEquipment, node_ids)
        labor_relations = self._list_node_children(ProcessNodeLabor, node_ids)
        node_outputs = self._list_node_children(ProcessNodeOutput, node_ids)
        calculation_outputs = self._list_route_outputs(route_ids)

        consumable_ids = sorted({item.consumable_id for item in consumptions})
        public_service_ids = sorted({item.public_service_id for item in public_services})
        labor_cost_ids = sorted({item.labor_cost_id for item in labor_relations})
        asset_ids = sorted({item.asset_id for item in equipment if item.asset_id is not None})
        output_product_ids = {
            item.product_id for item in node_outputs if item.product_id is not None
        } | {item.product_id for item in calculation_outputs if item.product_id is not None}
        all_product_ids = sorted(product_ids | output_product_ids)
        products = self._list_active(ProcessProduct, all_product_ids)
        consumables = self._list_active(ProcessConsumable, consumable_ids)
        service_libraries = self._list_active(ProcessPublicService, public_service_ids)
        labor_costs = self._list_active(ProcessLaborCost, labor_cost_ids)
        assets = self._list_active(ProcessAsset, asset_ids)
        compositions = list(
            self.db.scalars(
                select(ProcessMaterialComposition).where(
                    ProcessMaterialComposition.material_id.in_(material_ids),
                    ProcessMaterialComposition.is_deleted.is_(False),
                )
            ).all()
        )
        prices = self._list_prices(
            region_code,
            material_ids,
            set(all_product_ids),
            set(consumable_ids),
            set(public_service_ids),
            set(labor_cost_ids),
            set(asset_ids),
        )
        return {
            "materials": materials,
            "target_products": target_products,
            "routes": routes,
            "route_nodes": route_nodes,
            "nodes": nodes,
            "node_consumables": consumptions,
            "node_public_services": public_services,
            "node_equipment": equipment,
            "node_labor": labor_relations,
            "node_outputs": node_outputs,
            "calculation_outputs": calculation_outputs,
            "products": products,
            "consumables": consumables,
            "public_services": service_libraries,
            "labor_costs": labor_costs,
            "assets": assets,
            "compositions": compositions,
            "prices": prices,
        }

    def _list_route_nodes(self, route_ids: list[int]) -> list[ProcessRouteNode]:
        if not route_ids:
            return []
        return list(
            self.db.scalars(
                select(ProcessRouteNode)
                .where(ProcessRouteNode.route_id.in_(route_ids), ProcessRouteNode.is_deleted.is_(False))
                .order_by(ProcessRouteNode.route_id.asc(), ProcessRouteNode.sort_order.asc(), ProcessRouteNode.id.asc())
            ).all()
        )

    def _list_route_outputs(self, route_ids: list[int]) -> list[ProcessCalculationOutput]:
        if not route_ids:
            return []
        return list(
            self.db.scalars(
                select(ProcessCalculationOutput)
                .where(ProcessCalculationOutput.route_id.in_(route_ids), ProcessCalculationOutput.is_deleted.is_(False))
                .order_by(ProcessCalculationOutput.route_id.asc(), ProcessCalculationOutput.sort_order.asc(), ProcessCalculationOutput.id.asc())
            ).all()
        )

    def _list_node_children(self, model: type[Any], node_ids: list[int]) -> list[Any]:
        if not node_ids:
            return []
        return list(
            self.db.scalars(
                select(model)
                .where(model.node_id.in_(node_ids), model.is_deleted.is_(False))
                .order_by(model.node_id.asc(), model.sort_order.asc(), model.id.asc())
            ).all()
        )

    def _list_active(self, model: type[Any], item_ids: list[int]) -> list[Any]:
        if not item_ids:
            return []
        conditions = [model.id.in_(item_ids), model.is_deleted.is_(False)]
        if hasattr(model, "status"):
            conditions.append(model.status == "enabled")
        return list(self.db.scalars(select(model).where(*conditions)).all())

    def _list_prices(
        self,
        region_code: str,
        material_ids: set[int],
        product_ids: set[int],
        consumable_ids: set[int],
        public_service_ids: set[int],
        labor_cost_ids: set[int],
        asset_ids: set[int],
    ) -> list[ProcessRegionPrice]:
        owner_filters = []
        for owner_type, owner_ids in (
            ("material", material_ids),
            ("product", product_ids),
            ("consumable", consumable_ids),
            ("public_service", public_service_ids),
            ("labor", labor_cost_ids),
            ("asset", asset_ids),
        ):
            if owner_ids:
                owner_filters.append(
                    (ProcessRegionPrice.owner_type == owner_type) & ProcessRegionPrice.owner_id.in_(owner_ids)
                )
        if not owner_filters:
            return []
        return list(
            self.db.scalars(
                select(ProcessRegionPrice).where(
                    ProcessRegionPrice.region_code == region_code,
                    ProcessRegionPrice.status == "enabled",
                    ProcessRegionPrice.is_deleted.is_(False),
                    or_(*owner_filters),
                )
            ).all()
        )
