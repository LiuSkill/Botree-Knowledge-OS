"""Process configuration API."""

from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.exceptions import AppException
from app.core.response import success
from app.models.user import User
from app.schemas.process_config import (
    ProcessCalculationOutputReplacePayload,
    ProcessAssetCreateWithPrices,
    ProcessAssetUpdateWithPrices,
    ProcessConsumableCreateWithPrices,
    ProcessConsumableUpdateWithPrices,
    ProcessLaborCostCreateWithPrices,
    ProcessLaborCostUpdateWithPrices,
    ProcessLibraryStatusUpdate,
    ProcessMaterialCreateWithPrices,
    ProcessMaterialCompositionReplacePayload,
    ProcessMaterialUpdateWithPrices,
    ProcessNodeCreateWithChildren,
    ProcessNodeUpdateWithChildren,
    ProcessProductCreateWithPrices,
    ProcessProductUpdateWithPrices,
    ProcessPublicServiceCreateWithPrices,
    ProcessPublicServiceUpdateWithPrices,
    ProcessRouteCreateWithNodes,
    ProcessRouteNodeAddPayload,
    ProcessRouteNodeReorderPayload,
    ProcessRouteUpdateWithNodes,
    ProcessRouteVersionCreatePayload,
)
from app.schemas.process_calculator import ProcessCalculatorRequest
from app.services.process_calculator_service import ProcessCalculatorService
from app.services.process_config_excel_service import ProcessConfigExcelService
from app.services.process_config_service import ProcessConfigService

router = APIRouter(prefix="/process-config", tags=["工艺配置"])

EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _excel_response(content: bytes, filename: str) -> StreamingResponse:
    return StreamingResponse(
        BytesIO(content),
        media_type=EXCEL_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _read_upload_file(upload_file: UploadFile) -> bytes:
    if not upload_file.filename:
        raise AppException("请选择导入文件")
    content = await upload_file.read()
    if not content:
        raise AppException("导入文件内容为空")
    return content


@router.get("/calculator/options", summary="快速财务计算器选项")
def get_calculator_options(
    _: User = Depends(require_permission("process_config:calculator:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessCalculatorService(db).get_options())


@router.post("/calculator/calculate", summary="执行快速财务测算")
def calculate_financial_model(
    payload: ProcessCalculatorRequest,
    _: User = Depends(require_permission("process_config:calculator:calculate")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessCalculatorService(db).calculate(payload))


@router.get("/calculation-import-batches", summary="快速财务计算器Excel导入批次")
def list_calculation_import_batches(
    import_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_permission("process_config:route:import")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).list_calculation_import_batches(import_type=import_type, status=status, page=page, page_size=page_size))


@router.get("/materials", summary="原料库列表")
def list_materials(
    keyword: str | None = None,
    type_code: str | None = Query(default=None, alias="type"),
    status: str | None = None,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_permission("process_config:material:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).list_library("material", keyword=keyword, type_code=type_code, status=status, page=page, page_size=page_size))


@router.get("/materials/template", summary="下载原料库导入模板", response_model=None)
def download_material_template(
    _: User = Depends(require_permission("process_config:material:import")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    content, filename = ProcessConfigExcelService(db).build_template("materials")
    return _excel_response(content, filename)


@router.get("/materials/export", summary="导出原料库数据", response_model=None)
def export_materials(
    keyword: str | None = None,
    type_code: str | None = Query(default=None, alias="type"),
    status: str | None = None,
    _: User = Depends(require_permission("process_config:material:export")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    content, filename = ProcessConfigExcelService(db).export_module("materials", {"keyword": keyword, "type": type_code, "status": status})
    return _excel_response(content, filename)


@router.post("/materials/import", summary="导入原料库数据")
async def import_materials(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("process_config:material:import")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigExcelService(db).import_module("materials", await _read_upload_file(file), current_user))


@router.post("/materials", summary="新增原料")
def create_material(
    payload: ProcessMaterialCreateWithPrices,
    current_user: User = Depends(require_permission("process_config:material:create")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).create_library("material", payload, current_user))


@router.get("/materials/{material_id}", summary="原料详情")
def get_material(
    material_id: int,
    _: User = Depends(require_permission("process_config:material:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).get_library("material", material_id))


@router.get("/materials/{material_id}/compositions", summary="原料元素组成")
def list_material_compositions(
    material_id: int,
    _: User = Depends(require_permission("process_config:material:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).list_material_compositions(material_id))


@router.put("/materials/{material_id}/compositions", summary="维护原料元素组成")
def replace_material_compositions(
    material_id: int,
    payload: ProcessMaterialCompositionReplacePayload,
    current_user: User = Depends(require_permission("process_config:material:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).replace_material_compositions(material_id, payload, current_user))


@router.put("/materials/{material_id}", summary="编辑原料")
def update_material(
    material_id: int,
    payload: ProcessMaterialUpdateWithPrices,
    current_user: User = Depends(require_permission("process_config:material:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).update_library("material", material_id, payload, current_user))


@router.patch("/materials/{material_id}/status", summary="启用或停用原料")
def update_material_status(
    material_id: int,
    payload: ProcessLibraryStatusUpdate,
    current_user: User = Depends(require_permission("process_config:material:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).update_status("material", material_id, payload, current_user))


@router.delete("/materials/{material_id}", summary="删除原料")
def delete_material(
    material_id: int,
    current_user: User = Depends(require_permission("process_config:material:delete")),
    db: Session = Depends(get_db),
) -> dict:
    ProcessConfigService(db).delete_library("material", material_id, current_user)
    return success({"deleted": True})


@router.get("/products", summary="产品库列表")
def list_products(
    keyword: str | None = None,
    type_code: str | None = Query(default=None, alias="type"),
    output_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_permission("process_config:product:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(
        ProcessConfigService(db).list_library(
            "product",
            keyword=keyword,
            type_code=type_code,
            output_type=output_type,
            status=status,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/products/template", summary="下载产品库导入模板", response_model=None)
def download_product_template(
    _: User = Depends(require_permission("process_config:product:import")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    content, filename = ProcessConfigExcelService(db).build_template("products")
    return _excel_response(content, filename)


@router.get("/products/export", summary="导出产品库数据", response_model=None)
def export_products(
    keyword: str | None = None,
    type_code: str | None = Query(default=None, alias="type"),
    output_type: str | None = None,
    status: str | None = None,
    _: User = Depends(require_permission("process_config:product:export")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    content, filename = ProcessConfigExcelService(db).export_module("products", {"keyword": keyword, "type": type_code, "output_type": output_type, "status": status})
    return _excel_response(content, filename)


@router.post("/products/import", summary="导入产品库数据")
async def import_products(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("process_config:product:import")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigExcelService(db).import_module("products", await _read_upload_file(file), current_user))


@router.post("/products", summary="新增产品")
def create_product(
    payload: ProcessProductCreateWithPrices,
    current_user: User = Depends(require_permission("process_config:product:create")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).create_library("product", payload, current_user))


@router.get("/products/{product_id}", summary="产品详情")
def get_product(
    product_id: int,
    _: User = Depends(require_permission("process_config:product:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).get_library("product", product_id))


@router.put("/products/{product_id}", summary="编辑产品")
def update_product(
    product_id: int,
    payload: ProcessProductUpdateWithPrices,
    current_user: User = Depends(require_permission("process_config:product:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).update_library("product", product_id, payload, current_user))


@router.patch("/products/{product_id}/status", summary="启用或停用产品")
def update_product_status(
    product_id: int,
    payload: ProcessLibraryStatusUpdate,
    current_user: User = Depends(require_permission("process_config:product:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).update_status("product", product_id, payload, current_user))


@router.delete("/products/{product_id}", summary="删除产品")
def delete_product(
    product_id: int,
    current_user: User = Depends(require_permission("process_config:product:delete")),
    db: Session = Depends(get_db),
) -> dict:
    ProcessConfigService(db).delete_library("product", product_id, current_user)
    return success({"deleted": True})


@router.get("/consumables", summary="消耗品库列表")
def list_consumables(
    keyword: str | None = None,
    type_code: str | None = Query(default=None, alias="type"),
    status: str | None = None,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_permission("process_config:consumable:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).list_library("consumable", keyword=keyword, type_code=type_code, status=status, page=page, page_size=page_size))


@router.get("/consumables/template", summary="下载消耗品库导入模板", response_model=None)
def download_consumable_template(
    _: User = Depends(require_permission("process_config:consumable:import")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    content, filename = ProcessConfigExcelService(db).build_template("consumables")
    return _excel_response(content, filename)


@router.get("/consumables/export", summary="导出消耗品库数据", response_model=None)
def export_consumables(
    keyword: str | None = None,
    type_code: str | None = Query(default=None, alias="type"),
    status: str | None = None,
    _: User = Depends(require_permission("process_config:consumable:export")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    content, filename = ProcessConfigExcelService(db).export_module("consumables", {"keyword": keyword, "type": type_code, "status": status})
    return _excel_response(content, filename)


@router.post("/consumables/import", summary="导入消耗品库数据")
async def import_consumables(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("process_config:consumable:import")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigExcelService(db).import_module("consumables", await _read_upload_file(file), current_user))


@router.post("/consumables", summary="新增消耗品")
def create_consumable(
    payload: ProcessConsumableCreateWithPrices,
    current_user: User = Depends(require_permission("process_config:consumable:create")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).create_library("consumable", payload, current_user))


@router.get("/consumables/{consumable_id}", summary="消耗品详情")
def get_consumable(
    consumable_id: int,
    _: User = Depends(require_permission("process_config:consumable:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).get_library("consumable", consumable_id))


@router.put("/consumables/{consumable_id}", summary="编辑消耗品")
def update_consumable(
    consumable_id: int,
    payload: ProcessConsumableUpdateWithPrices,
    current_user: User = Depends(require_permission("process_config:consumable:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).update_library("consumable", consumable_id, payload, current_user))


@router.patch("/consumables/{consumable_id}/status", summary="启用或停用消耗品")
def update_consumable_status(
    consumable_id: int,
    payload: ProcessLibraryStatusUpdate,
    current_user: User = Depends(require_permission("process_config:consumable:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).update_status("consumable", consumable_id, payload, current_user))


@router.delete("/consumables/{consumable_id}", summary="删除消耗品")
def delete_consumable(
    consumable_id: int,
    current_user: User = Depends(require_permission("process_config:consumable:delete")),
    db: Session = Depends(get_db),
) -> dict:
    ProcessConfigService(db).delete_library("consumable", consumable_id, current_user)
    return success({"deleted": True})


@router.get("/public-services", summary="公共服务库列表")
def list_public_services(
    keyword: str | None = None,
    type_code: str | None = Query(default=None, alias="type"),
    status: str | None = None,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_permission("process_config:public_service:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).list_library("public_service", keyword=keyword, type_code=type_code, status=status, page=page, page_size=page_size))


@router.get("/public-services/template", summary="下载公共服务库导入模板", response_model=None)
def download_public_service_template(
    _: User = Depends(require_permission("process_config:public_service:import")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    content, filename = ProcessConfigExcelService(db).build_template("public-services")
    return _excel_response(content, filename)


@router.get("/public-services/export", summary="导出公共服务库数据", response_model=None)
def export_public_services(
    keyword: str | None = None,
    type_code: str | None = Query(default=None, alias="type"),
    status: str | None = None,
    _: User = Depends(require_permission("process_config:public_service:export")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    content, filename = ProcessConfigExcelService(db).export_module("public-services", {"keyword": keyword, "type": type_code, "status": status})
    return _excel_response(content, filename)


@router.post("/public-services/import", summary="导入公共服务库数据")
async def import_public_services(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("process_config:public_service:import")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigExcelService(db).import_module("public-services", await _read_upload_file(file), current_user))


@router.post("/public-services", summary="新增公共服务")
def create_public_service(
    payload: ProcessPublicServiceCreateWithPrices,
    current_user: User = Depends(require_permission("process_config:public_service:create")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).create_library("public_service", payload, current_user))


@router.get("/public-services/{public_service_id}", summary="公共服务详情")
def get_public_service(
    public_service_id: int,
    _: User = Depends(require_permission("process_config:public_service:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).get_library("public_service", public_service_id))


@router.put("/public-services/{public_service_id}", summary="编辑公共服务")
def update_public_service(
    public_service_id: int,
    payload: ProcessPublicServiceUpdateWithPrices,
    current_user: User = Depends(require_permission("process_config:public_service:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).update_library("public_service", public_service_id, payload, current_user))


@router.patch("/public-services/{public_service_id}/status", summary="启用或停用公共服务")
def update_public_service_status(
    public_service_id: int,
    payload: ProcessLibraryStatusUpdate,
    current_user: User = Depends(require_permission("process_config:public_service:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).update_status("public_service", public_service_id, payload, current_user))


@router.delete("/public-services/{public_service_id}", summary="删除公共服务")
def delete_public_service(
    public_service_id: int,
    current_user: User = Depends(require_permission("process_config:public_service:delete")),
    db: Session = Depends(get_db),
) -> dict:
    ProcessConfigService(db).delete_library("public_service", public_service_id, current_user)
    return success({"deleted": True})


@router.get("/labor-costs", summary="人员成本库列表")
def list_labor_costs(
    keyword: str | None = None,
    type_code: str | None = Query(default=None, alias="type"),
    status: str | None = None,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_permission("process_config:labor:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).list_library("labor", keyword=keyword, type_code=type_code, status=status, page=page, page_size=page_size))


@router.post("/labor-costs", summary="新增人员成本")
def create_labor_cost(
    payload: ProcessLaborCostCreateWithPrices,
    current_user: User = Depends(require_permission("process_config:labor:create")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).create_library("labor", payload, current_user))


@router.get("/labor-costs/{labor_cost_id}", summary="人员成本详情")
def get_labor_cost(
    labor_cost_id: int,
    _: User = Depends(require_permission("process_config:labor:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).get_library("labor", labor_cost_id))


@router.put("/labor-costs/{labor_cost_id}", summary="编辑人员成本")
def update_labor_cost(
    labor_cost_id: int,
    payload: ProcessLaborCostUpdateWithPrices,
    current_user: User = Depends(require_permission("process_config:labor:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).update_library("labor", labor_cost_id, payload, current_user))


@router.patch("/labor-costs/{labor_cost_id}/status", summary="启用或停用人员成本")
def update_labor_cost_status(
    labor_cost_id: int,
    payload: ProcessLibraryStatusUpdate,
    current_user: User = Depends(require_permission("process_config:labor:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).update_status("labor", labor_cost_id, payload, current_user))


@router.delete("/labor-costs/{labor_cost_id}", summary="删除人员成本")
def delete_labor_cost(
    labor_cost_id: int,
    current_user: User = Depends(require_permission("process_config:labor:delete")),
    db: Session = Depends(get_db),
) -> dict:
    ProcessConfigService(db).delete_library("labor", labor_cost_id, current_user)
    return success({"deleted": True})


@router.get("/assets", summary="设备/基础设施资产库列表")
def list_assets(
    keyword: str | None = None,
    type_code: str | None = Query(default=None, alias="type"),
    asset_class: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_permission("process_config:asset:view")),
    db: Session = Depends(get_db),
) -> dict:
    result = ProcessConfigService(db).list_library("asset", keyword=keyword, type_code=type_code, status=status, page=page, page_size=page_size)
    if asset_class:
        filtered = [item for item in result["items"] if item.get("asset_class") == asset_class]
        result = {**result, "items": filtered, "total": len(filtered)}
    return success(result)


@router.post("/assets", summary="新增设备/基础设施资产")
def create_asset(
    payload: ProcessAssetCreateWithPrices,
    current_user: User = Depends(require_permission("process_config:asset:create")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).create_library("asset", payload, current_user))


@router.get("/assets/{asset_id}", summary="设备/基础设施资产详情")
def get_asset(
    asset_id: int,
    _: User = Depends(require_permission("process_config:asset:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).get_library("asset", asset_id))


@router.put("/assets/{asset_id}", summary="编辑设备/基础设施资产")
def update_asset(
    asset_id: int,
    payload: ProcessAssetUpdateWithPrices,
    current_user: User = Depends(require_permission("process_config:asset:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).update_library("asset", asset_id, payload, current_user))


@router.patch("/assets/{asset_id}/status", summary="启用或停用设备/基础设施资产")
def update_asset_status(
    asset_id: int,
    payload: ProcessLibraryStatusUpdate,
    current_user: User = Depends(require_permission("process_config:asset:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).update_status("asset", asset_id, payload, current_user))


@router.delete("/assets/{asset_id}", summary="删除设备/基础设施资产")
def delete_asset(
    asset_id: int,
    current_user: User = Depends(require_permission("process_config:asset:delete")),
    db: Session = Depends(get_db),
) -> dict:
    ProcessConfigService(db).delete_library("asset", asset_id, current_user)
    return success({"deleted": True})


@router.get("/nodes", summary="工艺节点库列表")
def list_nodes(
    keyword: str | None = None,
    node_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_permission("process_config:node:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(
        ProcessConfigService(db).list_nodes(
            keyword=keyword,
            node_type=node_type,
            status=status,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/nodes/template", summary="下载工艺节点库导入模板", response_model=None)
def download_node_template(
    _: User = Depends(require_permission("process_config:node:import")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    content, filename = ProcessConfigExcelService(db).build_template("nodes")
    return _excel_response(content, filename)


@router.get("/nodes/export", summary="导出工艺节点库数据", response_model=None)
def export_nodes(
    keyword: str | None = None,
    node_type: str | None = None,
    status: str | None = None,
    _: User = Depends(require_permission("process_config:node:export")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    content, filename = ProcessConfigExcelService(db).export_module(
        "nodes",
        {"keyword": keyword, "node_type": node_type, "status": status},
    )
    return _excel_response(content, filename)


@router.post("/nodes/import", summary="导入工艺节点库数据")
async def import_nodes(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("process_config:node:import")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigExcelService(db).import_module("nodes", await _read_upload_file(file), current_user))


@router.post("/nodes", summary="新增工艺节点")
def create_node(
    payload: ProcessNodeCreateWithChildren,
    current_user: User = Depends(require_permission("process_config:node:create")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).create_node(payload, current_user))


@router.get("/nodes/{node_id}", summary="工艺节点详情")
def get_node(
    node_id: int,
    _: User = Depends(require_permission("process_config:node:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).get_node(node_id))


@router.put("/nodes/{node_id}", summary="编辑工艺节点")
def update_node(
    node_id: int,
    payload: ProcessNodeUpdateWithChildren,
    current_user: User = Depends(require_permission("process_config:node:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).update_node(node_id, payload, current_user))


@router.delete("/nodes/{node_id}", summary="删除工艺节点")
def delete_node(
    node_id: int,
    current_user: User = Depends(require_permission("process_config:node:delete")),
    db: Session = Depends(get_db),
) -> dict:
    ProcessConfigService(db).delete_node(node_id, current_user)
    return success({"deleted": True})


@router.get("/routes", summary="工艺路线列表")
def list_routes(
    keyword: str | None = None,
    input_material_id: int | None = None,
    final_product_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_permission("process_config:route:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(
        ProcessConfigService(db).list_routes(
            keyword=keyword,
            input_material_id=input_material_id,
            final_product_id=final_product_id,
            status=status,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/routes/template", summary="下载工艺路线库导入模板", response_model=None)
def download_route_template(
    _: User = Depends(require_permission("process_config:route:import")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    content, filename = ProcessConfigExcelService(db).build_template("routes")
    return _excel_response(content, filename)


@router.get("/routes/export", summary="导出工艺路线库数据", response_model=None)
def export_routes(
    keyword: str | None = None,
    input_material_id: int | None = None,
    final_product_id: int | None = None,
    status: str | None = None,
    _: User = Depends(require_permission("process_config:route:export")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    content, filename = ProcessConfigExcelService(db).export_module(
        "routes",
        {
            "keyword": keyword,
            "input_material_id": input_material_id,
            "final_product_id": final_product_id,
            "status": status,
        },
    )
    return _excel_response(content, filename)


@router.post("/routes/import", summary="导入工艺路线库数据")
async def import_routes(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("process_config:route:import")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigExcelService(db).import_module("routes", await _read_upload_file(file), current_user))


@router.post("/routes", summary="新增工艺路线")
def create_route(
    payload: ProcessRouteCreateWithNodes,
    current_user: User = Depends(require_permission("process_config:route:create")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).create_route(payload, current_user))


@router.get("/routes/{route_id}", summary="工艺路线详情")
def get_route(
    route_id: int,
    _: User = Depends(require_permission("process_config:route:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).get_route(route_id))


@router.get("/routes/{route_id}/tree-preview", summary="工艺路线树形预览")
def get_route_tree_preview(
    route_id: int,
    _: User = Depends(require_permission("process_config:route:preview")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).get_route_tree_preview(route_id))


@router.get("/routes/{route_id}/calculation-outputs", summary="路线测算产出系数")
def list_route_calculation_outputs(
    route_id: int,
    _: User = Depends(require_permission("process_config:route:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).list_route_calculation_outputs(route_id))


@router.put("/routes/{route_id}/calculation-outputs", summary="维护路线测算产出系数")
def replace_route_calculation_outputs(
    route_id: int,
    payload: ProcessCalculationOutputReplacePayload,
    current_user: User = Depends(require_permission("process_config:route:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).replace_route_calculation_outputs(route_id, payload, current_user))


@router.put("/routes/{route_id}", summary="编辑工艺路线")
def update_route(
    route_id: int,
    payload: ProcessRouteUpdateWithNodes,
    current_user: User = Depends(require_permission("process_config:route:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).update_route(route_id, payload, current_user))


@router.delete("/routes/{route_id}", summary="删除工艺路线")
def delete_route(
    route_id: int,
    current_user: User = Depends(require_permission("process_config:route:delete")),
    db: Session = Depends(get_db),
) -> dict:
    ProcessConfigService(db).delete_route(route_id, current_user)
    return success({"deleted": True})


@router.post("/routes/{route_id}/nodes", summary="新增路线节点")
def add_route_node(
    route_id: int,
    payload: ProcessRouteNodeAddPayload,
    current_user: User = Depends(require_permission("process_config:route:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).add_route_node(route_id, payload, current_user))


@router.put("/routes/{route_id}/nodes/reorder", summary="调整路线节点顺序")
def reorder_route_nodes(
    route_id: int,
    payload: ProcessRouteNodeReorderPayload,
    current_user: User = Depends(require_permission("process_config:route:update")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).reorder_route_nodes(route_id, payload, current_user))


@router.delete("/routes/{route_id}/nodes/{route_node_id}", summary="删除路线节点")
def delete_route_node(
    route_id: int,
    route_node_id: int,
    current_user: User = Depends(require_permission("process_config:route:update")),
    db: Session = Depends(get_db),
) -> dict:
    ProcessConfigService(db).delete_route_node(route_id, route_node_id, current_user)
    return success({"deleted": True})




@router.get("/routes/{route_id}/versions", summary="路线版本列表")
def list_route_versions(
    route_id: int,
    _: User = Depends(require_permission("process_config:route:version")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).list_route_versions(route_id))


@router.post("/routes/{route_id}/versions", summary="新增路线版本")
def create_route_version(
    route_id: int,
    payload: ProcessRouteVersionCreatePayload,
    current_user: User = Depends(require_permission("process_config:route:version")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).create_route_version(route_id, payload, current_user))


@router.get("/options/materials", summary="原料下拉选项")
def material_options(
    type_code: str | None = Query(default=None, alias="type"),
    _: User = Depends(require_permission("process_config:material:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).list_options("material", type_code=type_code))


@router.get("/options/products", summary="产品下拉选项")
def product_options(
    type_code: str | None = Query(default=None, alias="type"),
    output_type: str | None = None,
    _: User = Depends(require_permission("process_config:product:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).list_options("product", type_code=type_code, output_type=output_type))


@router.get("/options/consumables", summary="消耗品下拉选项")
def consumable_options(
    type_code: str | None = Query(default=None, alias="type"),
    _: User = Depends(require_permission("process_config:consumable:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).list_options("consumable", type_code=type_code))


@router.get("/options/public-services", summary="公共服务下拉选项")
def public_service_options(
    type_code: str | None = Query(default=None, alias="type"),
    _: User = Depends(require_permission("process_config:public_service:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).list_options("public_service", type_code=type_code))


@router.get("/options/labor-costs", summary="人员成本下拉选项")
def labor_cost_options(
    type_code: str | None = Query(default=None, alias="type"),
    _: User = Depends(require_permission("process_config:labor:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).list_options("labor", type_code=type_code))


@router.get("/options/assets", summary="设备/基础设施资产下拉选项")
def asset_options(
    type_code: str | None = Query(default=None, alias="type"),
    _: User = Depends(require_permission("process_config:asset:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProcessConfigService(db).list_options("asset", type_code=type_code))
