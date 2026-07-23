"""Process configuration services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import json
import logging
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
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
from app.models.user import User
from app.repositories.process_config_repository import (
    ProcessCalculationImportBatchRepository,
    ProcessCalculationOutputRepository,
    ProcessLibraryModel,
    ProcessLibraryRepository,
    ProcessMaterialCompositionRepository,
    ProcessNodeChildModel,
    ProcessNodeRepository,
    ProcessRouteRepository,
)
from app.schemas.process_config import (
    ProcessCalculationImportBatchOut,
    ProcessCalculationOutputOut,
    ProcessCalculationOutputReplacePayload,
    ProcessAssetOutWithPrices,
    ProcessLibraryCreateWithPrices,
    ProcessLibraryOutWithPrices,
    ProcessLibraryRegionPricePayload,
    ProcessLibraryStatusUpdate,
    ProcessLibraryUpdateWithPrices,
    ProcessLaborCostOutWithPrices,
    ProcessMaterialOutWithPrices,
    ProcessMaterialCompositionOut,
    ProcessMaterialCompositionReplacePayload,
    ProcessNodeConsumablePayload,
    ProcessNodeConsumableOut,
    ProcessNodeCreateWithChildren,
    ProcessNodeEquipmentOut,
    ProcessNodeEquipmentPayload,
    ProcessNodeLaborOut,
    ProcessNodeLaborPayload,
    ProcessNodeMaterialInputOut,
    ProcessNodeMaterialInputPayload,
    ProcessNodeOut,
    ProcessNodeOutWithChildren,
    ProcessNodeOutputOut,
    ProcessNodeOutputPayload,
    ProcessNodePublicServiceOut,
    ProcessNodePublicServicePayload,
    ProcessNodeUpdateWithChildren,
    ProcessProductOutWithPrices,
    ProcessRouteCreateWithNodes,
    ProcessRouteDetailOut,
    ProcessRouteListItemOut,
    ProcessRouteNodeAddPayload,
    ProcessRouteNodeDetailOut,
    ProcessRouteNodeOut,
    ProcessRouteNodePayload,
    ProcessRouteNodeReorderPayload,
    ProcessRouteOut,
    ProcessRouteTreePreviewOut,
    ProcessRouteUpdateWithNodes,
    ProcessRouteVersionCreatePayload,
    ProcessRouteVersionOut,
    ProcessRegionPriceOut,
)
from app.services.system_service import SystemService
from app.utils.pagination import paginate

logger = logging.getLogger(__name__)

ProcessLibraryKind = Literal["material", "product", "consumable", "public_service", "labor", "asset"]

VALID_PROCESS_STATUSES = {"enabled", "draft", "disabled"}
VALID_PROCESS_NODE_TYPES = {"pretreatment", "hydrometallurgy", "pyrometallurgy", "post_treatment"}
VALID_CALCULATION_IMPORT_STATUSES = {"pending", "success", "failed", "partial_success"}
REGION_ORDER = ("asia", "europe", "americas")
REGION_CONFIG = {
    "asia": {"region_name": "亚洲", "currency": "CNY"},
    "europe": {"region_name": "欧洲", "currency": "EUR"},
    "americas": {"region_name": "美洲", "currency": "USD"},
}


def _utc_now() -> datetime:
    """返回 naive UTC 时间，兼容项目当前数据库字段写法。"""

    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class ProcessLibraryConfig:
    """基础库类型配置，避免四个模块复制业务规则。"""

    kind: ProcessLibraryKind
    owner_type: str
    label: str
    model: ProcessLibraryModel


LIBRARY_CONFIGS: dict[ProcessLibraryKind, ProcessLibraryConfig] = {
    "material": ProcessLibraryConfig("material", "material", "原料", ProcessMaterial),
    "product": ProcessLibraryConfig("product", "product", "产品", ProcessProduct),
    "consumable": ProcessLibraryConfig("consumable", "consumable", "消耗品", ProcessConsumable),
    "public_service": ProcessLibraryConfig("public_service", "public_service", "公共服务", ProcessPublicService),
    "labor": ProcessLibraryConfig("labor", "labor", "人员成本", ProcessLaborCost),
    "asset": ProcessLibraryConfig("asset", "asset", "设备/基础设施资产", ProcessAsset),
}


class ProcessConfigService:
    """工艺配置基础库业务服务。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.system_service = SystemService(db)

    def list_library(
        self,
        kind: ProcessLibraryKind,
        keyword: str | None = None,
        type_code: str | None = None,
        output_type: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict:
        """分页查询基础库数据。"""

        self._validate_status_filter(status)
        repo = self._repository(kind)
        items = [
            self._serialize_library(repo, item)
            for item in repo.list(keyword=keyword, type_code=type_code, output_type=output_type, status=status)
        ]
        return paginate(items, page, page_size)

    def get_library(self, kind: ProcessLibraryKind, item_id: int) -> dict:
        """查询基础库详情。"""

        repo = self._repository(kind)
        item = self._get_existing(repo, item_id)
        return self._serialize_library(repo, item)

    def create_library(self, kind: ProcessLibraryKind, payload: ProcessLibraryCreateWithPrices, operator: User) -> dict:
        """创建基础库数据并同步三大区域单价。"""

        config = self._config(kind)
        repo = self._repository(kind)
        self._validate_code_unique(repo, payload.code)

        item_data = payload.model_dump(exclude={"region_prices"})
        item = config.model(**item_data, created_by=operator.id, updated_by=operator.id, is_deleted=False)
        repo.add(item)
        self._sync_region_prices(
            repo,
            item,
            self._normalize_region_prices(payload.region_prices, item.unit, allow_default=True),
            operator,
        )
        self.system_service.record_operation(operator, f"新增{config.label}", f"process_{config.owner_type}", item.id, f"新增{config.label} {item.name}")
        self.db.commit()
        self.db.refresh(item)
        logger.info("工艺基础库新增完成: kind=%s id=%s operator_id=%s", kind, item.id, operator.id)
        return self._serialize_library(repo, item)

    def update_library(self, kind: ProcessLibraryKind, item_id: int, payload: ProcessLibraryUpdateWithPrices, operator: User) -> dict:
        """编辑基础库数据并按需同步区域单价。"""

        config = self._config(kind)
        repo = self._repository(kind)
        item = self._get_existing(repo, item_id)
        fields_set = payload.model_fields_set

        if "code" in fields_set and payload.code != item.code:
            self._validate_code_unique(repo, payload.code, exclude_id=item.id)

        item_data = payload.model_dump(exclude_unset=True, exclude={"region_prices"})
        for field, value in item_data.items():
            setattr(item, field, value)
        item.updated_by = operator.id

        if "region_prices" in fields_set and payload.region_prices is not None:
            self._sync_region_prices(repo, item, self._normalize_region_prices(payload.region_prices, item.unit, allow_default=False), operator)

        self.system_service.record_operation(operator, f"编辑{config.label}", f"process_{config.owner_type}", item.id, f"编辑{config.label} {item.name}")
        self.db.commit()
        self.db.refresh(item)
        logger.info("工艺基础库编辑完成: kind=%s id=%s operator_id=%s", kind, item.id, operator.id)
        return self._serialize_library(repo, item)

    def update_status(self, kind: ProcessLibraryKind, item_id: int, payload: ProcessLibraryStatusUpdate, operator: User) -> dict:
        """启用或停用基础库数据。"""

        config = self._config(kind)
        repo = self._repository(kind)
        item = self._get_existing(repo, item_id)
        item.status = payload.status
        item.updated_by = operator.id
        action = "启用" if payload.status == "enabled" else "停用"
        self.system_service.record_operation(operator, f"{action}{config.label}", f"process_{config.owner_type}", item.id, f"{action}{config.label} {item.name}")
        self.db.commit()
        self.db.refresh(item)
        logger.info("工艺基础库状态变更完成: kind=%s id=%s status=%s operator_id=%s", kind, item.id, payload.status, operator.id)
        return self._serialize_library(repo, item)

    def delete_library(self, kind: ProcessLibraryKind, item_id: int, operator: User) -> None:
        """软删除基础库数据，存在业务引用时禁止删除。"""

        config = self._config(kind)
        repo = self._repository(kind)
        item = self._get_existing(repo, item_id)
        if repo.count_references(item.id) > 0:
            raise AppException("当前数据已被引用，不能删除")

        repo.soft_delete(item)
        item.updated_by = operator.id
        self.system_service.record_operation(operator, f"删除{config.label}", f"process_{config.owner_type}", item.id, f"删除{config.label} {item.name}")
        self.db.commit()
        logger.info("工艺基础库删除完成: kind=%s id=%s operator_id=%s", kind, item.id, operator.id)

    def list_options(
        self,
        kind: ProcessLibraryKind,
        type_code: str | None = None,
        output_type: str | None = None,
    ) -> list[dict]:
        """查询启用基础库下拉选项。"""

        repo = self._repository(kind)
        return [
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "type": item.type,
                "unit": item.unit,
                "status": item.status,
                "output_type": getattr(item, "output_type", None),
                "asset_class": getattr(item, "asset_class", None),
            }
            for item in repo.list_options(type_code=type_code, output_type=output_type)
        ]

    def list_material_compositions(self, material_id: int) -> list[dict]:
        """查询指定原料的元素组成。"""

        material_repo = self._repository("material")
        self._get_existing(material_repo, material_id)
        repo = ProcessMaterialCompositionRepository(self.db)
        return [self._serialize_material_composition(item) for item in repo.list_by_material(material_id)]

    def replace_material_compositions(
        self,
        material_id: int,
        payload: ProcessMaterialCompositionReplacePayload,
        operator: User,
    ) -> list[dict]:
        """整体替换原料元素组成，保持历史记录软删除。"""

        material_repo = self._repository("material")
        material = self._get_existing(material_repo, material_id)
        self._validate_unique_payload_field(payload.items, "element_code", "元素编码不能重复")

        repo = ProcessMaterialCompositionRepository(self.db)
        repo.replace(material.id, [row.model_dump() for row in payload.items], operator.id)
        material.updated_by = operator.id

        self.system_service.record_operation(operator, "维护原料元素组成", "process_material", material.id, f"维护原料元素组成 {material.name}")
        self.db.commit()
        logger.info("原料元素组成维护完成: material_id=%s operator_id=%s count=%s", material.id, operator.id, len(payload.items))
        return [self._serialize_material_composition(item) for item in repo.list_by_material(material.id)]

    def list_route_calculation_outputs(self, route_id: int) -> list[dict]:
        """查询指定路线的测算产出系数配置。"""

        route_repo = ProcessRouteRepository(self.db)
        route = self._get_existing_route(route_repo, route_id)
        repo = ProcessCalculationOutputRepository(self.db)
        return [self._serialize_calculation_output(item) for item in repo.list_by_route(route.id)]

    def replace_route_calculation_outputs(
        self,
        route_id: int,
        payload: ProcessCalculationOutputReplacePayload,
        operator: User,
    ) -> list[dict]:
        """整体替换路线测算产出配置，支撑产品、废固和废水产出系数。"""

        route_repo = ProcessRouteRepository(self.db)
        route = self._get_existing_route(route_repo, route_id)
        self._validate_calculation_output_payload(route, payload)

        repo = ProcessCalculationOutputRepository(self.db)
        repo.replace(route.id, [row.model_dump() for row in payload.items], operator.id)
        route.updated_by = operator.id

        self.system_service.record_operation(operator, "维护路线测算产出", "process_route", route.id, f"维护路线测算产出 {route.name}")
        self.db.commit()
        logger.info("路线测算产出维护完成: route_id=%s operator_id=%s count=%s", route.id, operator.id, len(payload.items))
        return [self._serialize_calculation_output(item) for item in repo.list_by_route(route.id)]

    def list_calculation_import_batches(
        self,
        import_type: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict:
        """查询快速财务计算器 Excel 导入批次。"""

        if status is not None and status not in VALID_CALCULATION_IMPORT_STATUSES:
            raise AppException("导入批次状态仅支持 pending/success/failed/partial_success")
        repo = ProcessCalculationImportBatchRepository(self.db)
        items = [ProcessCalculationImportBatchOut.model_validate(item).model_dump(mode="json") for item in repo.list(import_type, status)]
        return paginate(items, page, page_size)

    def list_nodes(
        self,
        keyword: str | None = None,
        node_type: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict:
        """分页查询工艺节点。"""

        self._validate_status_filter(status)
        self._validate_node_type_filter(node_type)
        repo = ProcessNodeRepository(self.db)
        items = [self._serialize_node_base(node) for node in repo.list(keyword=keyword, node_type=node_type, status=status)]
        return paginate(items, page, page_size)

    def get_node(self, node_id: int) -> dict:
        """查询工艺节点详情。"""

        repo = ProcessNodeRepository(self.db)
        node = self._get_existing_node(repo, node_id)
        return self._serialize_node(repo, node)

    def create_node(self, payload: ProcessNodeCreateWithChildren, operator: User) -> dict:
        """创建工艺节点，主表和全部子配置在同一事务内保存。"""

        repo = ProcessNodeRepository(self.db)
        self._validate_node_code_unique(repo, payload.code)
        self._validate_node_payload(payload.status, payload)

        node_data = payload.model_dump(
            exclude={"material_inputs", "consumables", "public_services", "equipment", "labor", "outputs"},
        )
        node = ProcessNode(**node_data, created_by=operator.id, updated_by=operator.id, is_deleted=False)
        repo.add(node)
        self._replace_node_children(repo, node.id, payload)

        self.system_service.record_operation(operator, "新增工艺节点", "process_node", node.id, f"新增工艺节点 {node.name}")
        self.db.commit()
        self.db.refresh(node)
        logger.info("工艺节点新增完成: node_id=%s operator_id=%s", node.id, operator.id)
        return self._serialize_node(repo, node)

    def update_node(self, node_id: int, payload: ProcessNodeUpdateWithChildren, operator: User) -> dict:
        """编辑工艺节点，子配置整体替换并保持事务一致。"""

        repo = ProcessNodeRepository(self.db)
        node = self._get_existing_node(repo, node_id)
        fields_set = payload.model_fields_set
        if "code" in fields_set and payload.code != node.code:
            self._validate_node_code_unique(repo, payload.code, exclude_id=node.id)

        final_status = payload.status if "status" in fields_set and payload.status is not None else node.status
        self._validate_node_payload(final_status, payload)

        node_data = payload.model_dump(
            exclude_unset=True,
            exclude={"material_inputs", "consumables", "public_services", "equipment", "labor", "outputs"},
        )
        for field, value in node_data.items():
            setattr(node, field, value)
        node.updated_by = operator.id
        self._replace_node_children(repo, node.id, payload)

        self.system_service.record_operation(operator, "编辑工艺节点", "process_node", node.id, f"编辑工艺节点 {node.name}")
        self.db.commit()
        self.db.refresh(node)
        logger.info("工艺节点编辑完成: node_id=%s operator_id=%s", node.id, operator.id)
        return self._serialize_node(repo, node)

    def delete_node(self, node_id: int, operator: User) -> None:
        """软删除工艺节点；已被路线引用时禁止删除。"""

        repo = ProcessNodeRepository(self.db)
        node = self._get_existing_node(repo, node_id)
        if repo.count_route_references(node.id) > 0:
            raise AppException("当前节点已被工艺路线引用，不能删除")

        repo.soft_delete(node)
        node.updated_by = operator.id
        self.system_service.record_operation(operator, "删除工艺节点", "process_node", node.id, f"删除工艺节点 {node.name}")
        self.db.commit()
        logger.info("工艺节点删除完成: node_id=%s operator_id=%s", node.id, operator.id)

    def list_routes(
        self,
        keyword: str | None = None,
        status: str | None = None,
        input_material_id: int | None = None,
        final_product_id: int | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict:
        """分页查询工艺路线。"""

        self._validate_status_filter(status)
        repo = ProcessRouteRepository(self.db)
        items = [
            self._serialize_route_list_item(repo, route)
            for route in repo.list(
                keyword=keyword,
                status=status,
                input_material_id=input_material_id,
                final_product_id=final_product_id,
            )
        ]
        return paginate(items, page, page_size)

    def get_route(self, route_id: int) -> dict:
        """查询工艺路线详情。"""

        repo = ProcessRouteRepository(self.db)
        route = self._get_existing_route(repo, route_id)
        return self._serialize_route_detail(repo, route)

    def get_route_tree_preview(self, route_id: int) -> dict:
        """批量生成路线树预览数据，供前端一次请求渲染完整工艺树。"""

        repo = ProcessRouteRepository(self.db)
        data = repo.get_tree_preview_data()
        routes: list[ProcessRoute] = data["routes"]
        if not any(route.id == route_id for route in routes):
            raise AppException("工艺路线不存在或已删除")

        material_map: dict[int, ProcessMaterial] = {item.id: item for item in data["materials"]}
        product_map: dict[int, ProcessProduct] = {item.id: item for item in data["products"]}
        node_map: dict[int, ProcessNode] = {item.id: item for item in data["nodes"]}
        route_nodes_by_route_id: dict[int, list[ProcessRouteNode]] = {}
        outputs_by_node_id: dict[int, list[ProcessNodeOutput]] = {}

        for route_node in data["route_nodes"]:
            route_nodes_by_route_id.setdefault(route_node.route_id, []).append(route_node)
        for output in data["outputs"]:
            outputs_by_node_id.setdefault(output.node_id, []).append(output)

        preview_routes: list[dict[str, Any]] = []
        for route in routes:
            material = material_map.get(route.input_material_id)
            final_product = product_map.get(route.final_product_id)
            if material is None or final_product is None:
                logger.warning("路线树预览跳过引用缺失路线: route_id=%s", route.id)
                continue

            preview_routes.append(
                {
                    "id": route.id,
                    "code": route.code,
                    "name": route.name,
                    "version": route.version,
                    "sort_order": route.sort_order,
                    "input_material": self._serialize_route_tree_library_item(material),
                    "final_product": self._serialize_route_tree_library_item(final_product),
                    "nodes": [
                        self._serialize_route_tree_node(route_node, node_map, outputs_by_node_id, product_map)
                        for route_node in route_nodes_by_route_id.get(route.id, [])
                        if route_node.node_id in node_map
                    ],
                }
            )

        payload = ProcessRouteTreePreviewOut(current_route_id=route_id, routes=preview_routes)
        return payload.model_dump(mode="json")

    def create_route(self, payload: ProcessRouteCreateWithNodes, operator: User) -> dict:
        """创建工艺路线并可一次性保存节点链路。"""

        repo = ProcessRouteRepository(self.db)
        self._validate_route_code_unique(repo, payload.code)
        self._validate_route_payload(
            payload.status,
            payload.input_material_id,
            payload.final_product_id,
            payload.nodes,
        )

        route_data = payload.model_dump(exclude={"nodes"})
        route = ProcessRoute(**route_data, created_by=operator.id, updated_by=operator.id, is_deleted=False)
        repo.add(route)
        repo.replace_nodes(route.id, [self._route_node_payload_dump(row) for row in payload.nodes])

        self.system_service.record_operation(operator, "新增工艺路线", "process_route", route.id, f"新增工艺路线 {route.name}")
        self.db.commit()
        self.db.refresh(route)
        logger.info("工艺路线新增完成: route_id=%s operator_id=%s", route.id, operator.id)
        return self._serialize_route_detail(repo, route)

    def update_route(self, route_id: int, payload: ProcessRouteUpdateWithNodes, operator: User) -> dict:
        """编辑工艺路线并按需整体替换节点链路。"""

        repo = ProcessRouteRepository(self.db)
        route = self._get_existing_route(repo, route_id)
        fields_set = payload.model_fields_set

        if "code" in fields_set and payload.code != route.code:
            self._validate_route_code_unique(repo, payload.code, exclude_id=route.id)

        final_status = payload.status if "status" in fields_set and payload.status is not None else route.status
        final_input_material_id = (
            payload.input_material_id
            if "input_material_id" in fields_set and payload.input_material_id is not None
            else route.input_material_id
        )
        final_product_id = (
            payload.final_product_id
            if "final_product_id" in fields_set and payload.final_product_id is not None
            else route.final_product_id
        )
        final_nodes = payload.nodes if "nodes" in fields_set and payload.nodes is not None else self._route_nodes_to_payloads(repo.list_nodes(route.id))
        self._validate_route_payload(final_status, final_input_material_id, final_product_id, final_nodes)

        route_data = payload.model_dump(exclude_unset=True, exclude={"nodes"})
        for field, value in route_data.items():
            setattr(route, field, value)
        route.updated_by = operator.id

        if "nodes" in fields_set and payload.nodes is not None:
            repo.replace_nodes(route.id, [self._route_node_payload_dump(row) for row in payload.nodes])

        self.system_service.record_operation(operator, "编辑工艺路线", "process_route", route.id, f"编辑工艺路线 {route.name}")
        self.db.commit()
        self.db.refresh(route)
        logger.info("工艺路线编辑完成: route_id=%s operator_id=%s", route.id, operator.id)
        return self._serialize_route_detail(repo, route)

    def delete_route(self, route_id: int, operator: User) -> None:
        """软删除工艺路线及其节点链路、版本快照。"""

        repo = ProcessRouteRepository(self.db)
        route = self._get_existing_route(repo, route_id)
        repo.soft_delete(route)
        route.updated_by = operator.id

        self.system_service.record_operation(operator, "删除工艺路线", "process_route", route.id, f"删除工艺路线 {route.name}")
        self.db.commit()
        logger.info("工艺路线删除完成: route_id=%s operator_id=%s", route.id, operator.id)

    def add_route_node(self, route_id: int, payload: ProcessRouteNodeAddPayload, operator: User) -> dict:
        """向工艺路线追加一个节点链路。"""

        repo = ProcessRouteRepository(self.db)
        route = self._get_existing_route(repo, route_id)
        final_nodes = [*self._route_nodes_to_payloads(repo.list_nodes(route.id)), payload]
        self._validate_route_payload(route.status, route.input_material_id, route.final_product_id, final_nodes)

        route_node = ProcessRouteNode(route_id=route.id, is_deleted=False, **self._route_node_payload_dump(payload))
        repo.add_route_node(route_node)
        route.updated_by = operator.id

        self.system_service.record_operation(operator, "新增路线节点", "process_route", route.id, f"新增路线节点 {route.name}")
        self.db.commit()
        self.db.refresh(route_node)
        logger.info("工艺路线节点新增完成: route_id=%s route_node_id=%s operator_id=%s", route.id, route_node.id, operator.id)
        return self._serialize_route_node(route_node)

    def reorder_route_nodes(self, route_id: int, payload: ProcessRouteNodeReorderPayload, operator: User) -> list[dict]:
        """调整路线节点顺序。"""

        repo = ProcessRouteRepository(self.db)
        route = self._get_existing_route(repo, route_id)
        route_nodes = repo.list_nodes(route.id)
        if not route_nodes:
            raise AppException("当前路线暂无节点可排序")
        if not payload.items:
            raise AppException("排序数据不能为空")

        route_node_by_id = {route_node.id: route_node for route_node in route_nodes}
        requested_ids: set[int] = set()
        updated_orders: dict[int, int] = {}
        for item in payload.items:
            route_node = route_node_by_id.get(item.route_node_id)
            if not route_node:
                raise AppException(f"路线节点不存在: id={item.route_node_id}")
            if item.route_node_id in requested_ids:
                raise AppException("排序节点不能重复")
            requested_ids.add(item.route_node_id)
            updated_orders[route_node.id] = item.sort_order

        final_orders = [updated_orders.get(route_node.id, route_node.sort_order) for route_node in route_nodes]
        if len(final_orders) != len(set(final_orders)):
            raise AppException("节点顺序不能重复")

        for route_node in route_nodes:
            if route_node.id in updated_orders:
                route_node.sort_order = updated_orders[route_node.id]
        route.updated_by = operator.id
        self._validate_route_payload(
            route.status,
            route.input_material_id,
            route.final_product_id,
            self._route_nodes_to_payloads(route_nodes),
        )

        self.system_service.record_operation(operator, "调整路线节点顺序", "process_route", route.id, f"调整路线节点顺序 {route.name}")
        self.db.commit()
        logger.info("工艺路线节点排序完成: route_id=%s operator_id=%s", route.id, operator.id)
        return [self._serialize_route_node(route_node) for route_node in repo.list_nodes(route.id)]

    def delete_route_node(self, route_id: int, route_node_id: int, operator: User) -> None:
        """删除单个路线节点；启用中的路线删除后仍需满足至少一个节点。"""

        repo = ProcessRouteRepository(self.db)
        route = self._get_existing_route(repo, route_id)
        route_nodes = repo.list_nodes(route.id)
        route_node = next((item for item in route_nodes if item.id == route_node_id), None)
        if not route_node:
            raise AppException("路线节点不存在", status_code=404, code=404)

        remaining_nodes = [
            payload_row
            for item, payload_row in zip(route_nodes, self._route_nodes_to_payloads(route_nodes))
            if item.id != route_node_id
        ]
        self._validate_route_payload(route.status, route.input_material_id, route.final_product_id, remaining_nodes)

        repo.soft_delete_route_node(route_node)
        route.updated_by = operator.id

        self.system_service.record_operation(operator, "删除路线节点", "process_route", route.id, f"删除路线节点 {route.name}")
        self.db.commit()
        logger.info("工艺路线节点删除完成: route_id=%s route_node_id=%s operator_id=%s", route.id, route_node.id, operator.id)

    def copy_route(self, route_id: int, operator: User) -> dict:
        """复制工艺路线主信息与节点链路，新路线默认启用。"""

        repo = ProcessRouteRepository(self.db)
        route = self._get_existing_route(repo, route_id)
        route_nodes = repo.list_nodes(route.id)
        copied_route = ProcessRoute(
            code=self._generate_route_copy_code(repo, route.code),
            name=route.name,
            input_material_id=route.input_material_id,
            final_product_id=route.final_product_id,
            version=route.version,
            description=route.description,
            status="enabled",
            sort_order=route.sort_order,
            remark=route.remark,
            created_by=operator.id,
            updated_by=operator.id,
            is_deleted=False,
        )
        repo.add(copied_route)
        repo.replace_nodes(copied_route.id, [self._route_node_model_dump(row) for row in route_nodes])

        self.system_service.record_operation(operator, "复制工艺路线", "process_route", copied_route.id, f"复制工艺路线 {route.name}")
        self.db.commit()
        self.db.refresh(copied_route)
        logger.info("工艺路线复制完成: source_route_id=%s new_route_id=%s operator_id=%s", route.id, copied_route.id, operator.id)
        return self._serialize_route_detail(repo, copied_route)

    def list_route_versions(self, route_id: int) -> list[dict]:
        """查询路线版本快照列表。"""

        repo = ProcessRouteRepository(self.db)
        route = self._get_existing_route(repo, route_id)
        return [self._serialize_route_version(version) for version in repo.list_versions(route.id)]

    def create_route_version(self, route_id: int, payload: ProcessRouteVersionCreatePayload, operator: User) -> dict:
        """保存当前路线完整快照为版本记录。"""

        repo = ProcessRouteRepository(self.db)
        route = self._get_existing_route(repo, route_id)
        version_no = payload.version_no or repo.next_version_no(route.id)
        if repo.get_version_by_no(route.id, version_no, include_deleted=True):
            raise AppException("版本号已存在")

        snapshot = self._serialize_route_detail(repo, route)
        version = ProcessRouteVersion(
            route_id=route.id,
            version_no=version_no,
            snapshot_json=json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
            change_log=payload.change_log,
            created_by=operator.id,
            is_deleted=False,
        )
        repo.add_version(version)

        self.system_service.record_operation(operator, "新增路线版本", "process_route", route.id, f"新增路线版本 {route.name} v{version_no}")
        self.db.commit()
        self.db.refresh(version)
        logger.info("工艺路线版本新增完成: route_id=%s version_no=%s operator_id=%s", route.id, version_no, operator.id)
        return self._serialize_route_version(version)

    def _config(self, kind: ProcessLibraryKind) -> ProcessLibraryConfig:
        config = LIBRARY_CONFIGS.get(kind)
        if not config:
            raise AppException("数据不存在", status_code=404, code=404)
        return config

    def _repository(self, kind: ProcessLibraryKind) -> ProcessLibraryRepository:
        config = self._config(kind)
        return ProcessLibraryRepository(self.db, config.model, config.owner_type)

    def _get_existing(self, repo: ProcessLibraryRepository, item_id: int) -> Any:
        item = repo.get_by_id(item_id)
        if not item:
            raise AppException("数据不存在", status_code=404, code=404)
        return item

    def _validate_status_filter(self, status: str | None) -> None:
        if status is not None and status not in VALID_PROCESS_STATUSES:
            raise AppException("状态仅支持 enabled/draft/disabled")

    def _validate_code_unique(self, repo: ProcessLibraryRepository, code: str | None, exclude_id: int | None = None) -> None:
        if not code:
            return
        exists = repo.get_by_code(code)
        if exists and exists.id != exclude_id:
            raise AppException("编码已存在")

    def _normalize_region_prices(
        self,
        region_prices: list[ProcessLibraryRegionPricePayload] | None,
        default_unit: str,
        allow_default: bool,
    ) -> list[dict[str, Any]]:
        """归一化三大区域单价，保证区域、币种和排序稳定。"""

        if not region_prices:
            if not allow_default:
                raise AppException("区域单价必须包含 asia/europe/americas")
            region_prices = [
                ProcessLibraryRegionPricePayload(region_code=region_code, unit_price=Decimal("0"), unit=default_unit)
                for region_code in REGION_ORDER
            ]

        normalized_by_region: dict[str, dict[str, Any]] = {}
        for price in region_prices:
            if price.region_code in normalized_by_region:
                raise AppException("区域单价存在重复区域")
            region_config = REGION_CONFIG[price.region_code]
            expected_currency = region_config["currency"]
            if price.currency is not None and price.currency != expected_currency:
                raise AppException(f"{price.region_code} 区域币种必须为 {expected_currency}")
            normalized_by_region[price.region_code] = {
                "region_code": price.region_code,
                "region_name": price.region_name or region_config["region_name"],
                "currency": expected_currency,
                "unit_price": price.unit_price,
                "unit": price.unit or default_unit,
                "status": price.status,
            }

        missing_regions = [region_code for region_code in REGION_ORDER if region_code not in normalized_by_region]
        if missing_regions:
            raise AppException("区域单价必须包含 asia/europe/americas")
        return [normalized_by_region[region_code] for region_code in REGION_ORDER]

    def _sync_region_prices(
        self,
        repo: ProcessLibraryRepository,
        item: Any,
        normalized_prices: list[dict[str, Any]],
        operator: User,
    ) -> None:
        """整体同步三大区域单价，修正历史重复区域为软删除。"""

        active_prices = repo.list_region_prices(item.id)
        active_by_region: dict[str, ProcessRegionPrice] = {}
        now = _utc_now()
        for price in active_prices:
            if price.region_code in active_by_region:
                price.is_deleted = True
                price.deleted_at = now
                price.status = "disabled"
                continue
            active_by_region[price.region_code] = price

        expected_regions = {price["region_code"] for price in normalized_prices}
        for price in active_prices:
            if price.region_code not in expected_regions:
                price.is_deleted = True
                price.deleted_at = now
                price.status = "disabled"

        for price_data in normalized_prices:
            price = active_by_region.get(price_data["region_code"])
            if price:
                for field, value in price_data.items():
                    setattr(price, field, value)
                price.updated_by = operator.id
                continue
            repo.add_region_price(
                ProcessRegionPrice(
                    owner_type=repo.owner_type,
                    owner_id=item.id,
                    created_by=operator.id,
                    updated_by=operator.id,
                    is_deleted=False,
                    **price_data,
                )
            )
        self.db.flush()

    def _get_existing_node(self, repo: ProcessNodeRepository, node_id: int) -> ProcessNode:
        node = repo.get_by_id(node_id)
        if not node:
            raise AppException("数据不存在", status_code=404, code=404)
        return node

    def _get_existing_route(self, repo: ProcessRouteRepository, route_id: int) -> ProcessRoute:
        route = repo.get_by_id(route_id)
        if not route:
            raise AppException("数据不存在", status_code=404, code=404)
        return route

    def _validate_node_type_filter(self, node_type: str | None) -> None:
        if node_type is not None and node_type not in VALID_PROCESS_NODE_TYPES:
            raise AppException("节点类型仅支持 pretreatment/hydrometallurgy/pyrometallurgy/post_treatment")

    def _validate_node_code_unique(self, repo: ProcessNodeRepository, code: str | None, exclude_id: int | None = None) -> None:
        if not code:
            return
        exists = repo.get_by_code(code)
        if exists and exists.id != exclude_id:
            raise AppException("编码已存在")

    def _validate_route_code_unique(self, repo: ProcessRouteRepository, code: str | None, exclude_id: int | None = None) -> None:
        if not code:
            return
        exists = repo.get_by_code(code)
        if exists and exists.id != exclude_id:
            raise AppException("编码已存在")

    def _validate_node_payload(self, status: str | None, payload: ProcessNodeCreateWithChildren | ProcessNodeUpdateWithChildren) -> None:
        """校验节点整体配置；启用时引用基础数据也必须启用。"""

        require_enabled_refs = status == "enabled"
        if require_enabled_refs and not payload.outputs:
            raise AppException("启用节点时至少需要配置一个输出产品")

        self._validate_reference_items(
            "material",
            payload.material_inputs,
            "material_id",
            "引用的原料不存在或已删除",
            "启用节点时，引用的原料必须为启用状态",
            require_enabled_refs,
        )
        self._validate_reference_items(
            "product",
            payload.outputs,
            "product_id",
            "引用的产品不存在或已删除",
            "启用节点时，引用的产品必须为启用状态",
            require_enabled_refs,
        )
        self._validate_reference_items(
            "consumable",
            payload.consumables,
            "consumable_id",
            "引用的消耗品不存在或已删除",
            "启用节点时，引用的消耗品必须为启用状态",
            require_enabled_refs,
        )
        self._validate_reference_items(
            "public_service",
            payload.public_services,
            "public_service_id",
            "引用的公共服务不存在或已删除",
            "启用节点时，引用的公共服务必须为启用状态",
            require_enabled_refs,
        )

    def _validate_reference_items(
        self,
        kind: ProcessLibraryKind,
        rows: list[Any],
        id_field: str,
        missing_message: str,
        disabled_message: str,
        require_enabled: bool,
    ) -> None:
        repo = self._repository(kind)
        for row in rows:
            item_id = getattr(row, id_field)
            item = repo.get_by_id(item_id)
            if not item:
                raise AppException(f"{missing_message}: id={item_id}")
            if require_enabled and item.status != "enabled":
                raise AppException(f"{disabled_message}: id={item_id}")

    def _validate_route_payload(
        self,
        status: str | None,
        input_material_id: int,
        final_product_id: int,
        nodes: list[ProcessRouteNodePayload | ProcessRouteNodeAddPayload],
    ) -> None:
        """校验路线启用规则、基础引用和节点链路。"""

        require_enabled_refs = status == "enabled"
        if require_enabled_refs and not nodes:
            raise AppException("启用路线时至少需要配置一个节点")

        self._validate_route_node_rows(nodes)

        material_repo = self._repository("material")
        input_material = material_repo.get_by_id(input_material_id)
        if not input_material:
            raise AppException(f"引用的输入原料不存在或已删除: id={input_material_id}")
        if require_enabled_refs and input_material.status != "enabled":
            raise AppException(f"启用路线时，引用的输入原料必须为启用状态: id={input_material_id}")

        product_repo = self._repository("product")
        final_product = product_repo.get_by_id(final_product_id)
        if not final_product:
            raise AppException(f"引用的最终产品不存在或已删除: id={final_product_id}")
        if require_enabled_refs and final_product.status != "enabled":
            raise AppException(f"启用路线时，引用的最终产品必须为启用状态: id={final_product_id}")

        node_repo = ProcessNodeRepository(self.db)
        for row in nodes:
            node = node_repo.get_by_id(row.node_id)
            if not node:
                raise AppException(f"引用的工艺节点不存在或已删除: id={row.node_id}")
            if require_enabled_refs and node.status != "enabled":
                raise AppException(f"启用路线时，引用的工艺节点必须为启用状态: id={row.node_id}")

    def _validate_route_node_rows(self, nodes: list[ProcessRouteNodePayload | ProcessRouteNodeAddPayload]) -> None:
        sort_orders = [row.sort_order for row in nodes]
        if len(sort_orders) != len(set(sort_orders)):
            raise AppException("节点顺序不能重复")

    def _validate_unique_payload_field(self, rows: list[Any], field_name: str, message: str) -> None:
        seen: set[Any] = set()
        for row in rows:
            value = getattr(row, field_name)
            key = value.strip().lower() if isinstance(value, str) else value
            if key in seen:
                raise AppException(message)
            seen.add(key)

    def _validate_calculation_output_payload(
        self,
        route: ProcessRoute,
        payload: ProcessCalculationOutputReplacePayload,
    ) -> None:
        product_repo = self._repository("product")
        require_enabled_refs = route.status == "enabled"
        for row in payload.items:
            if row.product_id is None:
                continue
            product = product_repo.get_by_id(row.product_id)
            if not product:
                raise AppException(f"引用的产品不存在或已删除: id={row.product_id}")
            if require_enabled_refs and product.status != "enabled":
                raise AppException(f"启用路线时，测算产出引用的产品必须为启用状态: id={row.product_id}")

    def _replace_node_children(
        self,
        repo: ProcessNodeRepository,
        node_id: int,
        payload: ProcessNodeCreateWithChildren | ProcessNodeUpdateWithChildren,
    ) -> None:
        repo.replace_children(ProcessNodeMaterialInput, node_id, [self._payload_dump(row) for row in payload.material_inputs])
        repo.replace_children(ProcessNodeConsumable, node_id, [self._payload_dump(row) for row in payload.consumables])
        repo.replace_children(ProcessNodePublicService, node_id, [self._payload_dump(row) for row in payload.public_services])
        repo.replace_children(ProcessNodeEquipment, node_id, [self._payload_dump(row) for row in payload.equipment])
        repo.replace_children(ProcessNodeLabor, node_id, [self._payload_dump(row) for row in payload.labor])
        repo.replace_children(ProcessNodeOutput, node_id, [self._payload_dump(row) for row in payload.outputs])

    def _route_nodes_to_payloads(self, route_nodes: list[ProcessRouteNode]) -> list[ProcessRouteNodePayload]:
        return [
            ProcessRouteNodePayload(
                node_id=route_node.node_id,
                sort_order=route_node.sort_order,
                node_params_json=route_node.node_params_json,
                remark=route_node.remark,
            )
            for route_node in route_nodes
        ]

    def _route_node_payload_dump(self, payload: ProcessRouteNodePayload | ProcessRouteNodeAddPayload) -> dict[str, Any]:
        return payload.model_dump()

    def _route_node_model_dump(self, route_node: ProcessRouteNode) -> dict[str, Any]:
        return {
            "node_id": route_node.node_id,
            "sort_order": route_node.sort_order,
            "node_params_json": route_node.node_params_json,
            "remark": route_node.remark,
        }

    def _generate_route_copy_code(self, repo: ProcessRouteRepository, source_code: str) -> str:
        base_code = f"{source_code}_COPY"
        candidate = base_code
        index = 2
        while repo.get_by_code(candidate):
            candidate = f"{base_code}_{index}"
            index += 1
        return candidate

    def _payload_dump(
        self,
        payload: (
            ProcessNodeMaterialInputPayload
            | ProcessNodeConsumablePayload
            | ProcessNodePublicServicePayload
            | ProcessNodeEquipmentPayload
            | ProcessNodeLaborPayload
            | ProcessNodeOutputPayload
        ),
    ) -> dict[str, Any]:
        data = payload.model_dump()
        if "amount_per_ton_bm" in data and "amount_per_ton_bm" not in payload.model_fields_set:
            data["amount_per_ton_bm"] = data.get("amount_per_ton", Decimal("0"))
        return data

    def _serialize_route_base(self, route: ProcessRoute) -> dict[str, Any]:
        return ProcessRouteOut.model_validate(route).model_dump(mode="json")

    def _serialize_route_node(self, route_node: ProcessRouteNode) -> dict[str, Any]:
        return ProcessRouteNodeOut.model_validate(route_node).model_dump(mode="json")

    def _serialize_route_list_item(self, repo: ProcessRouteRepository, route: ProcessRoute) -> dict[str, Any]:
        material_repo = self._repository("material")
        product_repo = self._repository("product")
        input_material = material_repo.get_by_id(route.input_material_id)
        final_product = product_repo.get_by_id(route.final_product_id)
        data = {
            **self._serialize_route_base(route),
            "input_material_name": input_material.name if input_material else None,
            "final_product_name": final_product.name if final_product else None,
            "node_count": len(repo.list_nodes(route.id)),
        }
        return ProcessRouteListItemOut.model_validate(data).model_dump(mode="json")

    def _serialize_route_detail(self, repo: ProcessRouteRepository, route: ProcessRoute) -> dict[str, Any]:
        material_repo = self._repository("material")
        product_repo = self._repository("product")
        node_repo = ProcessNodeRepository(self.db)

        input_material = self._get_existing(material_repo, route.input_material_id)
        final_product = self._get_existing(product_repo, route.final_product_id)
        nodes = []
        for route_node in repo.list_nodes(route.id):
            node = self._get_existing_node(node_repo, route_node.node_id)
            nodes.append(
                ProcessRouteNodeDetailOut.model_validate(
                    {
                        **self._serialize_route_node(route_node),
                        "node": self._serialize_node(node_repo, node),
                    }
                ).model_dump(mode="json")
            )

        data = {
            "route": self._serialize_route_base(route),
            "input_material": ProcessMaterialOutWithPrices.model_validate(self._serialize_library(material_repo, input_material)).model_dump(
                mode="json"
            ),
            "final_product": ProcessProductOutWithPrices.model_validate(self._serialize_library(product_repo, final_product)).model_dump(
                mode="json"
            ),
            "nodes": nodes,
        }
        return ProcessRouteDetailOut.model_validate(data).model_dump(mode="json")

    def _serialize_route_tree_library_item(self, item: ProcessMaterial | ProcessProduct) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": item.id,
            "code": item.code,
            "name": item.name,
            "unit": item.unit,
            "output_type": None,
        }
        if isinstance(item, ProcessProduct):
            data["output_type"] = item.output_type
        return data

    def _serialize_route_tree_node(
        self,
        route_node: ProcessRouteNode,
        node_map: dict[int, ProcessNode],
        outputs_by_node_id: dict[int, list[ProcessNodeOutput]],
        product_map: dict[int, ProcessProduct],
    ) -> dict[str, Any]:
        node = node_map[route_node.node_id]
        outputs = []
        for output in outputs_by_node_id.get(node.id, []):
            product = product_map.get(output.product_id)
            outputs.append(
                {
                    "id": output.id,
                    "product_id": output.product_id,
                    "output_type": output.output_type,
                    "product": self._serialize_route_tree_library_item(product) if product else None,
                }
            )
        return {
            "route_node_id": route_node.id,
            "node_id": node.id,
            "code": node.code,
            "name": node.name,
            "node_type": node.node_type,
            "version": node.version,
            "sort_order": route_node.sort_order,
            "outputs": outputs,
        }

    def _serialize_route_version(self, version: ProcessRouteVersion) -> dict[str, Any]:
        return ProcessRouteVersionOut.model_validate(version).model_dump(mode="json")

    def _serialize_node_base(self, node: ProcessNode) -> dict:
        data = {
            "id": node.id,
            "code": node.code,
            "name": node.name,
            "node_type": node.node_type,
            "staff": node.staff,
            "area": node.area,
            "description": node.description,
            "status": node.status,
            "version": node.version,
            "sort_order": node.sort_order,
            "remark": node.remark,
            "created_by": node.created_by,
            "updated_by": node.updated_by,
            "is_deleted": node.is_deleted,
            "deleted_at": node.deleted_at,
            "created_at": node.created_at,
            "updated_at": node.updated_at,
        }
        return ProcessNodeOut.model_validate(data).model_dump(mode="json")

    def _serialize_node(self, repo: ProcessNodeRepository, node: ProcessNode) -> dict:
        data = {
            **self._serialize_node_base(node),
            "material_inputs": self._serialize_child_list(repo, ProcessNodeMaterialInput, ProcessNodeMaterialInputOut, node.id),
            "consumables": self._serialize_child_list(repo, ProcessNodeConsumable, ProcessNodeConsumableOut, node.id),
            "public_services": self._serialize_child_list(repo, ProcessNodePublicService, ProcessNodePublicServiceOut, node.id),
            "equipment": self._serialize_child_list(repo, ProcessNodeEquipment, ProcessNodeEquipmentOut, node.id),
            "labor": self._serialize_child_list(repo, ProcessNodeLabor, ProcessNodeLaborOut, node.id),
            "outputs": self._serialize_child_list(repo, ProcessNodeOutput, ProcessNodeOutputOut, node.id),
        }
        return ProcessNodeOutWithChildren.model_validate(data).model_dump(mode="json")

    def _serialize_child_list(
        self,
        repo: ProcessNodeRepository,
        model: ProcessNodeChildModel,
        schema: type[Any],
        node_id: int,
    ) -> list[dict]:
        return [schema.model_validate(child).model_dump(mode="json") for child in repo.list_children(model, node_id)]

    def _serialize_material_composition(self, composition: ProcessMaterialComposition) -> dict:
        return ProcessMaterialCompositionOut.model_validate(composition).model_dump(mode="json")

    def _serialize_calculation_output(self, output: ProcessCalculationOutput) -> dict:
        return ProcessCalculationOutputOut.model_validate(output).model_dump(mode="json")

    def _serialize_library(self, repo: ProcessLibraryRepository, item: Any) -> dict:
        region_order = {region_code: index for index, region_code in enumerate(REGION_ORDER)}
        prices = sorted(repo.list_region_prices(item.id), key=lambda price: region_order.get(price.region_code, 99))
        data = {
            "id": item.id,
            "code": item.code,
            "name": item.name,
            "type": item.type,
            "description": item.description,
            "unit": item.unit,
            "status": item.status,
            "sort_order": item.sort_order,
            "remark": item.remark,
            "created_by": item.created_by,
            "updated_by": item.updated_by,
            "is_deleted": item.is_deleted,
            "deleted_at": item.deleted_at,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "region_prices": [ProcessRegionPriceOut.model_validate(price).model_dump(mode="json") for price in prices],
        }
        if repo.owner_type == "product":
            data.update(
                {
                    "output_type": getattr(item, "output_type", "product"),
                    "spec": getattr(item, "spec", None),
                    "treatment_cost": getattr(item, "treatment_cost", Decimal("0")),
                }
            )
            return ProcessProductOutWithPrices.model_validate(data).model_dump(mode="json")
        if repo.owner_type == "labor":
            data.update(
                {
                    "salary_period": getattr(item, "salary_period", "year"),
                    "welfare_factor": getattr(item, "welfare_factor", Decimal("1")),
                }
            )
            return ProcessLaborCostOutWithPrices.model_validate(data).model_dump(mode="json")
        if repo.owner_type == "asset":
            data.update(
                {
                    "asset_class": getattr(item, "asset_class", "equipment"),
                }
            )
            return ProcessAssetOutWithPrices.model_validate(data).model_dump(mode="json")
        return ProcessLibraryOutWithPrices.model_validate(data).model_dump(mode="json")
