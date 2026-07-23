"""Process configuration repositories."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypeAlias

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.process_config import (
    ProcessCalculationImportBatch,
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
    ProcessNodeMaterialInput,
    ProcessNodeOutput,
    ProcessNodePublicService,
    ProcessProduct,
    ProcessPublicService,
    ProcessRegionPrice,
    ProcessRoute,
    ProcessRouteNode,
    ProcessRouteVersion,
)

ProcessLibraryModel: TypeAlias = (
    type[ProcessMaterial]
    | type[ProcessProduct]
    | type[ProcessConsumable]
    | type[ProcessPublicService]
    | type[ProcessLaborCost]
    | type[ProcessAsset]
)
ProcessNodeChildModel: TypeAlias = (
    type[ProcessNodeMaterialInput]
    | type[ProcessNodeConsumable]
    | type[ProcessNodePublicService]
    | type[ProcessNodeEquipment]
    | type[ProcessNodeLabor]
    | type[ProcessNodeOutput]
)


def _utc_now() -> datetime:
    """返回 naive UTC 时间，兼容项目当前数据库字段写法。"""

    return datetime.now(UTC).replace(tzinfo=None)


class ProcessLibraryRepository:
    """四类工艺基础库的通用仓储。"""

    def __init__(self, db: Session, model: ProcessLibraryModel, owner_type: str) -> None:
        self.db = db
        self.model = model
        self.owner_type = owner_type

    def list(
        self,
        keyword: str | None = None,
        type_code: str | None = None,
        output_type: str | None = None,
        status: str | None = None,
    ) -> list[Any]:
        """查询未删除基础库数据。"""

        stmt = select(self.model).where(self.model.is_deleted.is_(False))
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    self.model.code.like(like),
                    self.model.name.like(like),
                    self.model.type.like(like),
                    self.model.description.like(like),
                )
            )
        if status:
            stmt = stmt.where(self.model.status == status)
        if type_code:
            stmt = stmt.where(self.model.type == type_code)
        if output_type and hasattr(self.model, "output_type"):
            stmt = stmt.where(self.model.output_type == output_type)
        stmt = stmt.order_by(self.model.sort_order.asc(), self.model.id.desc())
        return list(self.db.scalars(stmt).all())

    def list_options(self, type_code: str | None = None, output_type: str | None = None) -> list[Any]:
        """查询启用状态的下拉选项。"""

        stmt = (
            select(self.model)
            .where(self.model.is_deleted.is_(False), self.model.status == "enabled")
            .order_by(self.model.sort_order.asc(), self.model.id.desc())
        )
        if type_code:
            stmt = stmt.where(self.model.type == type_code)
        if output_type and hasattr(self.model, "output_type"):
            stmt = stmt.where(self.model.output_type == output_type)
        return list(self.db.scalars(stmt).all())

    def get_by_id(self, item_id: int, include_deleted: bool = False) -> Any | None:
        """按 ID 查询基础库数据。"""

        item = self.db.get(self.model, item_id)
        if item is None:
            return None
        if not include_deleted and item.is_deleted:
            return None
        return item

    def get_by_code(self, code: str) -> Any | None:
        """按编码查询，包含软删除记录以满足编码全局唯一。"""

        return self.db.scalar(select(self.model).where(self.model.code == code))

    def add(self, item: Any) -> Any:
        """新增基础库数据。"""

        self.db.add(item)
        self.db.flush()
        return item

    def list_region_prices(self, owner_id: int, include_deleted: bool = False) -> list[ProcessRegionPrice]:
        """查询主数据下的区域单价。"""

        stmt = select(ProcessRegionPrice).where(
            ProcessRegionPrice.owner_type == self.owner_type,
            ProcessRegionPrice.owner_id == owner_id,
        )
        if not include_deleted:
            stmt = stmt.where(ProcessRegionPrice.is_deleted.is_(False))
        return list(self.db.scalars(stmt).all())

    def add_region_price(self, price: ProcessRegionPrice) -> ProcessRegionPrice:
        """新增区域单价。"""

        self.db.add(price)
        self.db.flush()
        return price

    def soft_delete(self, item: Any) -> None:
        """软删除主数据及其区域单价。"""

        now = _utc_now()
        item.is_deleted = True
        item.deleted_at = now
        item.status = "disabled"
        for price in self.list_region_prices(item.id):
            price.is_deleted = True
            price.deleted_at = now
            price.status = "disabled"
        if self.owner_type == "material":
            for composition in ProcessMaterialCompositionRepository(self.db).list_by_material(item.id):
                composition.is_deleted = True
                composition.deleted_at = now
                composition.updated_by = item.updated_by
        self.db.flush()

    def count_references(self, item_id: int) -> int:
        """统计当前基础库数据是否被节点或路线引用。"""

        if self.owner_type == "material":
            return self._count_active(ProcessNodeMaterialInput, "material_id", item_id) + self._count_active(ProcessRoute, "input_material_id", item_id)
        if self.owner_type == "product":
            return (
                self._count_active(ProcessNodeOutput, "product_id", item_id)
                + self._count_active(ProcessRoute, "final_product_id", item_id)
                + self._count_active(ProcessCalculationOutput, "product_id", item_id)
            )
        if self.owner_type == "consumable":
            return self._count_active(ProcessNodeConsumable, "consumable_id", item_id)
        if self.owner_type == "public_service":
            return self._count_active(ProcessNodePublicService, "public_service_id", item_id)
        if self.owner_type == "labor":
            return self._count_active(ProcessNodeLabor, "labor_cost_id", item_id)
        if self.owner_type == "asset":
            return self._count_active(ProcessNodeEquipment, "asset_id", item_id)
        return 0

    def _count_active(self, model: type[Any], column_name: str, item_id: int) -> int:
        """统计指定引用表中未软删除的引用数量。"""

        stmt = select(func.count()).select_from(model).where(
            getattr(model, column_name) == item_id,
            model.is_deleted.is_(False),
        )
        return int(self.db.scalar(stmt) or 0)


class ProcessRouteRepository:
    """Repository for process routes, route nodes, and route versions."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(
        self,
        keyword: str | None = None,
        status: str | None = None,
        input_material_id: int | None = None,
        final_product_id: int | None = None,
    ) -> list[ProcessRoute]:
        stmt = select(ProcessRoute).where(ProcessRoute.is_deleted.is_(False))
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    ProcessRoute.code.like(like),
                    ProcessRoute.name.like(like),
                    ProcessRoute.description.like(like),
                    ProcessRoute.remark.like(like),
                )
            )
        if status:
            stmt = stmt.where(ProcessRoute.status == status)
        if input_material_id is not None:
            stmt = stmt.where(ProcessRoute.input_material_id == input_material_id)
        if final_product_id is not None:
            stmt = stmt.where(ProcessRoute.final_product_id == final_product_id)
        stmt = stmt.order_by(ProcessRoute.sort_order.asc(), ProcessRoute.id.desc())
        return list(self.db.scalars(stmt).all())

    def get_tree_preview_data(self) -> dict[str, list[Any]]:
        """批量获取路线树预览所需数据，避免前端逐条路线查询详情。"""

        routes = list(
            self.db.scalars(
                select(ProcessRoute)
                .where(ProcessRoute.is_deleted.is_(False))
                .order_by(ProcessRoute.sort_order.asc(), ProcessRoute.id.asc())
            ).all()
        )
        route_ids = [route.id for route in routes]
        if not route_ids:
            return {
                "routes": [],
                "route_nodes": [],
                "nodes": [],
                "outputs": [],
                "materials": [],
                "products": [],
            }

        route_nodes = list(
            self.db.scalars(
                select(ProcessRouteNode)
                .where(
                    ProcessRouteNode.route_id.in_(route_ids),
                    ProcessRouteNode.is_deleted.is_(False),
                )
                .order_by(ProcessRouteNode.route_id.asc(), ProcessRouteNode.sort_order.asc(), ProcessRouteNode.id.asc())
            ).all()
        )
        node_ids = sorted({row.node_id for row in route_nodes})
        nodes = (
            list(
                self.db.scalars(
                    select(ProcessNode)
                    .where(
                        ProcessNode.id.in_(node_ids),
                        ProcessNode.is_deleted.is_(False),
                    )
                    .order_by(ProcessNode.sort_order.asc(), ProcessNode.id.asc())
                ).all()
            )
            if node_ids
            else []
        )
        outputs = (
            list(
                self.db.scalars(
                    select(ProcessNodeOutput)
                    .where(
                        ProcessNodeOutput.node_id.in_(node_ids),
                        ProcessNodeOutput.output_type.in_(("solid_waste", "wastewater")),
                        ProcessNodeOutput.is_deleted.is_(False),
                    )
                    .order_by(ProcessNodeOutput.node_id.asc(), ProcessNodeOutput.sort_order.asc(), ProcessNodeOutput.id.asc())
                ).all()
            )
            if node_ids
            else []
        )

        material_ids = sorted({route.input_material_id for route in routes})
        product_ids = sorted({route.final_product_id for route in routes} | {output.product_id for output in outputs})
        materials = list(
            self.db.scalars(
                select(ProcessMaterial)
                .where(
                    ProcessMaterial.id.in_(material_ids),
                    ProcessMaterial.is_deleted.is_(False),
                )
                .order_by(ProcessMaterial.sort_order.asc(), ProcessMaterial.id.asc())
            ).all()
        )
        products = list(
            self.db.scalars(
                select(ProcessProduct)
                .where(
                    ProcessProduct.id.in_(product_ids),
                    ProcessProduct.is_deleted.is_(False),
                )
                .order_by(ProcessProduct.sort_order.asc(), ProcessProduct.id.asc())
            ).all()
        )
        return {
            "routes": routes,
            "route_nodes": route_nodes,
            "nodes": nodes,
            "outputs": outputs,
            "materials": materials,
            "products": products,
        }

    def get_by_id(self, route_id: int, include_deleted: bool = False) -> ProcessRoute | None:
        route = self.db.get(ProcessRoute, route_id)
        if route is None:
            return None
        if not include_deleted and route.is_deleted:
            return None
        return route

    def get_by_code(self, code: str) -> ProcessRoute | None:
        return self.db.scalar(select(ProcessRoute).where(ProcessRoute.code == code))

    def add(self, route: ProcessRoute) -> ProcessRoute:
        self.db.add(route)
        self.db.flush()
        return route

    def list_nodes(self, route_id: int, include_deleted: bool = False) -> list[ProcessRouteNode]:
        stmt = select(ProcessRouteNode).where(ProcessRouteNode.route_id == route_id)
        if not include_deleted:
            stmt = stmt.where(ProcessRouteNode.is_deleted.is_(False))
        stmt = stmt.order_by(ProcessRouteNode.sort_order.asc(), ProcessRouteNode.id.asc())
        return list(self.db.scalars(stmt).all())

    def get_route_node(self, route_node_id: int, include_deleted: bool = False) -> ProcessRouteNode | None:
        route_node = self.db.get(ProcessRouteNode, route_node_id)
        if route_node is None:
            return None
        if not include_deleted and route_node.is_deleted:
            return None
        return route_node

    def replace_nodes(self, route_id: int, rows: list[dict[str, Any]]) -> None:
        now = _utc_now()
        for route_node in self.list_nodes(route_id):
            route_node.is_deleted = True
            route_node.deleted_at = now
        for row in rows:
            self.db.add(ProcessRouteNode(route_id=route_id, is_deleted=False, **row))
        self.db.flush()

    def add_route_node(self, route_node: ProcessRouteNode) -> ProcessRouteNode:
        self.db.add(route_node)
        self.db.flush()
        return route_node

    def soft_delete_route_node(self, route_node: ProcessRouteNode) -> None:
        route_node.is_deleted = True
        route_node.deleted_at = _utc_now()
        self.db.flush()

    def list_versions(self, route_id: int, include_deleted: bool = False) -> list[ProcessRouteVersion]:
        stmt = select(ProcessRouteVersion).where(ProcessRouteVersion.route_id == route_id)
        if not include_deleted:
            stmt = stmt.where(ProcessRouteVersion.is_deleted.is_(False))
        stmt = stmt.order_by(ProcessRouteVersion.version_no.desc(), ProcessRouteVersion.id.desc())
        return list(self.db.scalars(stmt).all())

    def add_version(self, version: ProcessRouteVersion) -> ProcessRouteVersion:
        self.db.add(version)
        self.db.flush()
        return version

    def get_version_by_no(self, route_id: int, version_no: int, include_deleted: bool = False) -> ProcessRouteVersion | None:
        stmt = select(ProcessRouteVersion).where(
            ProcessRouteVersion.route_id == route_id,
            ProcessRouteVersion.version_no == version_no,
        )
        if not include_deleted:
            stmt = stmt.where(ProcessRouteVersion.is_deleted.is_(False))
        return self.db.scalar(stmt)

    def next_version_no(self, route_id: int) -> int:
        stmt = select(func.max(ProcessRouteVersion.version_no)).where(
            ProcessRouteVersion.route_id == route_id,
            ProcessRouteVersion.is_deleted.is_(False),
        )
        return int(self.db.scalar(stmt) or 0) + 1

    def soft_delete(self, route: ProcessRoute) -> None:
        now = _utc_now()
        route.is_deleted = True
        route.deleted_at = now
        route.status = "disabled"
        for route_node in self.list_nodes(route.id):
            route_node.is_deleted = True
            route_node.deleted_at = now
        for version in self.list_versions(route.id):
            version.is_deleted = True
            version.deleted_at = now
        for output in ProcessCalculationOutputRepository(self.db).list_by_route(route.id):
            output.is_deleted = True
            output.deleted_at = now
            output.updated_by = route.updated_by
        self.db.flush()


class ProcessMaterialCompositionRepository:
    """原料元素组成仓储，子配置采用整体替换并保留软删除历史。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_material(self, material_id: int, include_deleted: bool = False) -> list[ProcessMaterialComposition]:
        stmt = select(ProcessMaterialComposition).where(ProcessMaterialComposition.material_id == material_id)
        if not include_deleted:
            stmt = stmt.where(ProcessMaterialComposition.is_deleted.is_(False))
        stmt = stmt.order_by(ProcessMaterialComposition.element_code.asc(), ProcessMaterialComposition.id.asc())
        return list(self.db.scalars(stmt).all())

    def replace(self, material_id: int, rows: list[dict[str, Any]], operator_id: int | None) -> None:
        now = _utc_now()
        for composition in self.list_by_material(material_id):
            composition.is_deleted = True
            composition.deleted_at = now
            composition.updated_by = operator_id
        for row in rows:
            self.db.add(
                ProcessMaterialComposition(
                    material_id=material_id,
                    created_by=operator_id,
                    updated_by=operator_id,
                    is_deleted=False,
                    **row,
                )
            )
        self.db.flush()


class ProcessCalculationOutputRepository:
    """路线测算产出仓储，承接产品、副产物、废固和废水系数。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_route(self, route_id: int, include_deleted: bool = False) -> list[ProcessCalculationOutput]:
        stmt = select(ProcessCalculationOutput).where(ProcessCalculationOutput.route_id == route_id)
        if not include_deleted:
            stmt = stmt.where(ProcessCalculationOutput.is_deleted.is_(False))
        stmt = stmt.order_by(ProcessCalculationOutput.sort_order.asc(), ProcessCalculationOutput.id.asc())
        return list(self.db.scalars(stmt).all())

    def replace(self, route_id: int, rows: list[dict[str, Any]], operator_id: int | None) -> None:
        now = _utc_now()
        for output in self.list_by_route(route_id):
            output.is_deleted = True
            output.deleted_at = now
            output.updated_by = operator_id
        for row in rows:
            self.db.add(
                ProcessCalculationOutput(
                    route_id=route_id,
                    created_by=operator_id,
                    updated_by=operator_id,
                    is_deleted=False,
                    **row,
                )
            )
        self.db.flush()


class ProcessCalculationImportBatchRepository:
    """快速财务计算器 Excel 导入批次仓储。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, batch: ProcessCalculationImportBatch) -> ProcessCalculationImportBatch:
        self.db.add(batch)
        self.db.flush()
        return batch

    def list(self, import_type: str | None = None, status: str | None = None) -> list[ProcessCalculationImportBatch]:
        stmt = select(ProcessCalculationImportBatch).where(ProcessCalculationImportBatch.is_deleted.is_(False))
        if import_type:
            stmt = stmt.where(ProcessCalculationImportBatch.import_type == import_type)
        if status:
            stmt = stmt.where(ProcessCalculationImportBatch.status == status)
        stmt = stmt.order_by(ProcessCalculationImportBatch.id.desc())
        return list(self.db.scalars(stmt).all())


class ProcessNodeRepository:
    """工艺节点及其子配置仓储。"""

    child_models: tuple[ProcessNodeChildModel, ...] = (
        ProcessNodeMaterialInput,
        ProcessNodeConsumable,
        ProcessNodePublicService,
        ProcessNodeEquipment,
        ProcessNodeLabor,
        ProcessNodeOutput,
    )

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, keyword: str | None = None, node_type: str | None = None, status: str | None = None) -> list[ProcessNode]:
        """查询未删除工艺节点。"""

        stmt = select(ProcessNode).where(ProcessNode.is_deleted.is_(False))
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    ProcessNode.code.like(like),
                    ProcessNode.name.like(like),
                    ProcessNode.node_type.like(like),
                    ProcessNode.description.like(like),
                    ProcessNode.remark.like(like),
                )
            )
        if node_type:
            stmt = stmt.where(ProcessNode.node_type == node_type)
        if status:
            stmt = stmt.where(ProcessNode.status == status)
        stmt = stmt.order_by(ProcessNode.sort_order.asc(), ProcessNode.id.desc())
        return list(self.db.scalars(stmt).all())

    def get_by_id(self, node_id: int, include_deleted: bool = False) -> ProcessNode | None:
        """按 ID 查询节点。"""

        node = self.db.get(ProcessNode, node_id)
        if node is None:
            return None
        if not include_deleted and node.is_deleted:
            return None
        return node

    def get_by_code(self, code: str) -> ProcessNode | None:
        """按编码查询节点，包含软删除记录以保证 code 全局唯一。"""

        return self.db.scalar(select(ProcessNode).where(ProcessNode.code == code))

    def add(self, node: ProcessNode) -> ProcessNode:
        """新增节点主表记录。"""

        self.db.add(node)
        self.db.flush()
        return node

    def list_children(self, model: ProcessNodeChildModel, node_id: int, include_deleted: bool = False) -> list[Any]:
        """查询节点子配置。"""

        stmt = select(model).where(model.node_id == node_id)
        if not include_deleted:
            stmt = stmt.where(model.is_deleted.is_(False))
        stmt = stmt.order_by(model.sort_order.asc(), model.id.asc())
        return list(self.db.scalars(stmt).all())

    def replace_children(self, model: ProcessNodeChildModel, node_id: int, rows: list[dict[str, Any]]) -> None:
        """整体替换指定类型子配置，历史记录保留为软删除。"""

        now = _utc_now()
        for child in self.list_children(model, node_id):
            child.is_deleted = True
            child.deleted_at = now
        for row in rows:
            self.db.add(model(node_id=node_id, is_deleted=False, **row))
        self.db.flush()

    def soft_delete(self, node: ProcessNode) -> None:
        """软删除节点和全部未删除子配置。"""

        now = _utc_now()
        node.is_deleted = True
        node.deleted_at = now
        node.status = "disabled"
        for model in self.child_models:
            for child in self.list_children(model, node.id):
                child.is_deleted = True
                child.deleted_at = now
        self.db.flush()

    def count_route_references(self, node_id: int) -> int:
        """统计未删除路线对当前节点的引用。"""

        stmt = (
            select(func.count())
            .select_from(ProcessRouteNode)
            .join(ProcessRoute, ProcessRouteNode.route_id == ProcessRoute.id)
            .where(
                ProcessRouteNode.node_id == node_id,
                ProcessRouteNode.is_deleted.is_(False),
                ProcessRoute.is_deleted.is_(False),
            )
        )
        return int(self.db.scalar(stmt) or 0)
