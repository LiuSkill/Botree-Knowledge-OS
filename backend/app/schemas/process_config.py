"""Process configuration schemas.

职责：
1. 定义工艺配置基础库、节点和路线的请求/响应模型。
2. 约束状态、区域、币种和节点类型使用英文编码入库。
3. 为后续 CRUD、导入导出和权限接口提供统一类型。
"""

from datetime import datetime
from decimal import Decimal
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProcessStatus = Literal["enabled", "draft", "disabled"]
ProcessOwnerType = Literal["material", "product", "consumable", "public_service"]
ProcessRegionCode = Literal["asia", "europe", "americas"]
ProcessCurrency = Literal["CNY", "EUR", "USD"]
ProcessNodeType = Literal["pretreatment", "hydrometallurgy", "pyrometallurgy", "post_treatment"]


class _TrimTextMixin(BaseModel):
    """统一清理前端传入的文本字段。"""

    @field_validator(
        "code",
        "name",
        "type",
        "unit",
        "region_name",
        "equipment_name",
        "equipment_type",
        "version",
        "description",
        "remark",
        "change_log",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        value = value.strip()
        return value or None

    @field_validator("node_params_json", "snapshot_json", mode="before", check_fields=False)
    @classmethod
    def _normalize_json_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class ProcessLibraryBase(_TrimTextMixin):
    """基础库公共字段。"""

    code: str = Field(..., min_length=1, max_length=100, description="编码")
    name: str = Field(..., min_length=1, max_length=150, description="名称")
    type: str = Field(..., min_length=1, max_length=100, description="类型")
    description: str | None = Field(default=None, description="描述信息")
    unit: str = Field(..., min_length=1, max_length=50, description="单位")
    status: ProcessStatus = Field(default="enabled", description="状态")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessLibraryUpdate(_TrimTextMixin):
    """基础库更新字段。"""

    code: str | None = Field(default=None, min_length=1, max_length=100, description="编码")
    name: str | None = Field(default=None, min_length=1, max_length=150, description="名称")
    type: str | None = Field(default=None, min_length=1, max_length=100, description="类型")
    description: str | None = Field(default=None, description="描述信息")
    unit: str | None = Field(default=None, min_length=1, max_length=50, description="单位")
    status: ProcessStatus | None = Field(default=None, description="状态")
    sort_order: int | None = Field(default=None, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessLibraryOut(ProcessLibraryBase):
    """基础库响应字段。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_by: int | None = None
    updated_by: int | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProcessMaterialCreate(ProcessLibraryBase):
    """创建原料。"""


class ProcessMaterialUpdate(ProcessLibraryUpdate):
    """更新原料。"""


class ProcessMaterialOut(ProcessLibraryOut):
    """原料响应。"""


class ProcessProductCreate(ProcessLibraryBase):
    """创建产品。"""


class ProcessProductUpdate(ProcessLibraryUpdate):
    """更新产品。"""


class ProcessProductOut(ProcessLibraryOut):
    """产品响应。"""


class ProcessConsumableCreate(ProcessLibraryBase):
    """创建消耗品。"""


class ProcessConsumableUpdate(ProcessLibraryUpdate):
    """更新消耗品。"""


class ProcessConsumableOut(ProcessLibraryOut):
    """消耗品响应。"""


class ProcessPublicServiceCreate(ProcessLibraryBase):
    """创建公共服务。"""


class ProcessPublicServiceUpdate(ProcessLibraryUpdate):
    """更新公共服务。"""


class ProcessPublicServiceOut(ProcessLibraryOut):
    """公共服务响应。"""


class ProcessRegionPriceCreate(_TrimTextMixin):
    """创建区域单价。"""

    owner_type: ProcessOwnerType = Field(..., description="归属类型")
    owner_id: int = Field(..., gt=0, description="归属基础库ID")
    region_code: ProcessRegionCode = Field(..., description="区域编码")
    region_name: str = Field(..., min_length=1, max_length=100, description="区域名称")
    currency: ProcessCurrency = Field(..., description="币种")
    unit_price: Decimal = Field(default=Decimal("0"), ge=0, description="单位价格")
    unit: str = Field(..., min_length=1, max_length=50, description="计价单位")
    status: ProcessStatus = Field(default="enabled", description="状态")


class ProcessRegionPriceUpdate(_TrimTextMixin):
    """更新区域单价。"""

    region_name: str | None = Field(default=None, min_length=1, max_length=100, description="区域名称")
    currency: ProcessCurrency | None = Field(default=None, description="币种")
    unit_price: Decimal | None = Field(default=None, ge=0, description="单位价格")
    unit: str | None = Field(default=None, min_length=1, max_length=50, description="计价单位")
    status: ProcessStatus | None = Field(default=None, description="状态")


class ProcessRegionPriceOut(ProcessRegionPriceCreate):
    """区域单价响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_by: int | None = None
    updated_by: int | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProcessNodeCreate(_TrimTextMixin):
    """创建工艺节点。"""

    code: str = Field(..., min_length=1, max_length=100, description="节点编码")
    name: str = Field(..., min_length=1, max_length=150, description="节点名称")
    node_type: ProcessNodeType = Field(..., description="节点类型")
    staff: Decimal = Field(default=Decimal("0"), ge=0, description="人员数量")
    area: Decimal = Field(default=Decimal("0"), ge=0, description="占地面积")
    description: str | None = Field(default=None, description="描述信息")
    status: ProcessStatus = Field(default="draft", description="状态")
    version: str = Field(default="1.0", min_length=1, max_length=50, description="版本号")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeUpdate(_TrimTextMixin):
    """更新工艺节点。"""

    code: str | None = Field(default=None, min_length=1, max_length=100, description="节点编码")
    name: str | None = Field(default=None, min_length=1, max_length=150, description="节点名称")
    node_type: ProcessNodeType | None = Field(default=None, description="节点类型")
    staff: Decimal | None = Field(default=None, ge=0, description="人员数量")
    area: Decimal | None = Field(default=None, ge=0, description="占地面积")
    description: str | None = Field(default=None, description="描述信息")
    status: ProcessStatus | None = Field(default=None, description="状态")
    version: str | None = Field(default=None, min_length=1, max_length=50, description="版本号")
    sort_order: int | None = Field(default=None, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeOut(ProcessNodeCreate):
    """工艺节点响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_by: int | None = None
    updated_by: int | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProcessNodeMaterialInputCreate(_TrimTextMixin):
    """创建节点输入原料。"""

    node_id: int = Field(..., gt=0, description="节点ID")
    material_id: int = Field(..., gt=0, description="原料ID")
    amount_per_ton: Decimal = Field(default=Decimal("0"), ge=0, description="每吨原料投入量")
    unit: str = Field(..., min_length=1, max_length=50, description="单位")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeMaterialInputUpdate(_TrimTextMixin):
    """更新节点输入原料。"""

    material_id: int | None = Field(default=None, gt=0, description="原料ID")
    amount_per_ton: Decimal | None = Field(default=None, ge=0, description="每吨原料投入量")
    unit: str | None = Field(default=None, min_length=1, max_length=50, description="单位")
    sort_order: int | None = Field(default=None, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeMaterialInputOut(ProcessNodeMaterialInputCreate):
    """节点输入原料响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProcessNodeConsumableCreate(_TrimTextMixin):
    """创建节点消耗品。"""

    node_id: int = Field(..., gt=0, description="节点ID")
    consumable_id: int = Field(..., gt=0, description="消耗品ID")
    amount_per_ton: Decimal = Field(default=Decimal("0"), ge=0, description="每吨原料消耗量")
    unit: str = Field(..., min_length=1, max_length=50, description="单位")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeConsumableUpdate(_TrimTextMixin):
    """更新节点消耗品。"""

    consumable_id: int | None = Field(default=None, gt=0, description="消耗品ID")
    amount_per_ton: Decimal | None = Field(default=None, ge=0, description="每吨原料消耗量")
    unit: str | None = Field(default=None, min_length=1, max_length=50, description="单位")
    sort_order: int | None = Field(default=None, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeConsumableOut(ProcessNodeConsumableCreate):
    """节点消耗品响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProcessNodePublicServiceCreate(_TrimTextMixin):
    """创建节点公共服务消耗。"""

    node_id: int = Field(..., gt=0, description="节点ID")
    public_service_id: int = Field(..., gt=0, description="公共服务ID")
    amount_per_ton: Decimal = Field(default=Decimal("0"), ge=0, description="每吨原料消耗量")
    unit: str = Field(..., min_length=1, max_length=50, description="单位")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodePublicServiceUpdate(_TrimTextMixin):
    """更新节点公共服务消耗。"""

    public_service_id: int | None = Field(default=None, gt=0, description="公共服务ID")
    amount_per_ton: Decimal | None = Field(default=None, ge=0, description="每吨原料消耗量")
    unit: str | None = Field(default=None, min_length=1, max_length=50, description="单位")
    sort_order: int | None = Field(default=None, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodePublicServiceOut(ProcessNodePublicServiceCreate):
    """节点公共服务消耗响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProcessNodeEquipmentCreate(_TrimTextMixin):
    """创建节点设备投资。"""

    node_id: int = Field(..., gt=0, description="节点ID")
    equipment_name: str = Field(..., min_length=1, max_length=150, description="设备名称")
    equipment_type: str | None = Field(default=None, max_length=100, description="设备类型")
    quantity: Decimal = Field(default=Decimal("0"), ge=0, description="设备数量")
    investment_amount: Decimal = Field(default=Decimal("0"), ge=0, description="投资金额")
    currency: str = Field(default="CNY", min_length=1, max_length=10, description="币种")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeEquipmentUpdate(_TrimTextMixin):
    """更新节点设备投资。"""

    equipment_name: str | None = Field(default=None, min_length=1, max_length=150, description="设备名称")
    equipment_type: str | None = Field(default=None, max_length=100, description="设备类型")
    quantity: Decimal | None = Field(default=None, ge=0, description="设备数量")
    investment_amount: Decimal | None = Field(default=None, ge=0, description="投资金额")
    currency: str | None = Field(default=None, min_length=1, max_length=10, description="币种")
    sort_order: int | None = Field(default=None, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeEquipmentOut(ProcessNodeEquipmentCreate):
    """节点设备投资响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProcessNodeOutputCreate(_TrimTextMixin):
    """创建节点输出产品。"""

    node_id: int = Field(..., gt=0, description="节点ID")
    product_id: int = Field(..., gt=0, description="产品ID")
    output_per_ton: Decimal = Field(default=Decimal("0"), ge=0, description="每吨原料产出量")
    unit: str = Field(..., min_length=1, max_length=50, description="单位")
    is_main_product: bool = Field(default=False, description="是否主产品")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeOutputUpdate(_TrimTextMixin):
    """更新节点输出产品。"""

    product_id: int | None = Field(default=None, gt=0, description="产品ID")
    output_per_ton: Decimal | None = Field(default=None, ge=0, description="每吨原料产出量")
    unit: str | None = Field(default=None, min_length=1, max_length=50, description="单位")
    is_main_product: bool | None = Field(default=None, description="是否主产品")
    sort_order: int | None = Field(default=None, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeOutputOut(ProcessNodeOutputCreate):
    """节点输出产品响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProcessNodeMaterialInputPayload(_TrimTextMixin):
    """节点维护时提交的输入原料，不要求前端传 node_id。"""

    material_id: int = Field(..., gt=0, description="原料ID")
    amount_per_ton: Decimal = Field(default=Decimal("0"), ge=0, description="每吨投入量")
    unit: str = Field(..., min_length=1, max_length=50, description="单位")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeConsumablePayload(_TrimTextMixin):
    """节点维护时提交的消耗品，不要求前端传 node_id。"""

    consumable_id: int = Field(..., gt=0, description="消耗品ID")
    amount_per_ton: Decimal = Field(default=Decimal("0"), ge=0, description="每吨消耗量")
    unit: str = Field(..., min_length=1, max_length=50, description="单位")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodePublicServicePayload(_TrimTextMixin):
    """节点维护时提交的公共服务消耗，不要求前端传 node_id。"""

    public_service_id: int = Field(..., gt=0, description="公共服务ID")
    amount_per_ton: Decimal = Field(default=Decimal("0"), ge=0, description="每吨消耗量")
    unit: str = Field(..., min_length=1, max_length=50, description="单位")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeEquipmentPayload(_TrimTextMixin):
    """节点维护时提交的设备/投资。"""

    equipment_name: str = Field(..., min_length=1, max_length=150, description="设备名称")
    equipment_type: str | None = Field(default=None, max_length=100, description="设备类型")
    quantity: Decimal = Field(default=Decimal("0"), ge=0, description="设备数量")
    investment_amount: Decimal = Field(default=Decimal("0"), ge=0, description="投资金额")
    currency: str = Field(default="CNY", min_length=1, max_length=10, description="币种")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeOutputPayload(_TrimTextMixin):
    """节点维护时提交的输出产品，不要求前端传 node_id。"""

    product_id: int = Field(..., gt=0, description="产品ID")
    output_per_ton: Decimal = Field(default=Decimal("0"), ge=0, description="每吨产出量")
    unit: str = Field(..., min_length=1, max_length=50, description="单位")
    is_main_product: bool = Field(default=False, description="是否主产品")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeCreateWithChildren(ProcessNodeCreate):
    """创建工艺节点，主表与子配置一次提交。"""

    material_inputs: list[ProcessNodeMaterialInputPayload] = Field(default_factory=list, description="输入原料")
    consumables: list[ProcessNodeConsumablePayload] = Field(default_factory=list, description="消耗品")
    public_services: list[ProcessNodePublicServicePayload] = Field(default_factory=list, description="公共服务")
    equipment: list[ProcessNodeEquipmentPayload] = Field(default_factory=list, description="设备/投资")
    outputs: list[ProcessNodeOutputPayload] = Field(default_factory=list, description="输出产品")


class ProcessNodeUpdateWithChildren(ProcessNodeUpdate):
    """编辑工艺节点，子配置采用整体替换。"""

    material_inputs: list[ProcessNodeMaterialInputPayload] = Field(default_factory=list, description="输入原料")
    consumables: list[ProcessNodeConsumablePayload] = Field(default_factory=list, description="消耗品")
    public_services: list[ProcessNodePublicServicePayload] = Field(default_factory=list, description="公共服务")
    equipment: list[ProcessNodeEquipmentPayload] = Field(default_factory=list, description="设备/投资")
    outputs: list[ProcessNodeOutputPayload] = Field(default_factory=list, description="输出产品")


class ProcessNodeOutWithChildren(ProcessNodeOut):
    """工艺节点详情，包含完整子配置。"""

    material_inputs: list[ProcessNodeMaterialInputOut] = Field(default_factory=list, description="输入原料")
    consumables: list[ProcessNodeConsumableOut] = Field(default_factory=list, description="消耗品")
    public_services: list[ProcessNodePublicServiceOut] = Field(default_factory=list, description="公共服务")
    equipment: list[ProcessNodeEquipmentOut] = Field(default_factory=list, description="设备/投资")
    outputs: list[ProcessNodeOutputOut] = Field(default_factory=list, description="输出产品")


class ProcessRouteCreate(_TrimTextMixin):
    """创建工艺路线。"""

    code: str = Field(..., min_length=1, max_length=100, description="路线编码")
    name: str = Field(..., min_length=1, max_length=150, description="路线名称")
    input_material_id: int = Field(..., gt=0, description="输入原料ID")
    final_product_id: int = Field(..., gt=0, description="最终产品ID")
    version: str = Field(default="1.0", min_length=1, max_length=50, description="版本号")
    description: str | None = Field(default=None, description="描述信息")
    status: ProcessStatus = Field(default="draft", description="状态")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessRouteUpdate(_TrimTextMixin):
    """更新工艺路线。"""

    code: str | None = Field(default=None, min_length=1, max_length=100, description="路线编码")
    name: str | None = Field(default=None, min_length=1, max_length=150, description="路线名称")
    input_material_id: int | None = Field(default=None, gt=0, description="输入原料ID")
    final_product_id: int | None = Field(default=None, gt=0, description="最终产品ID")
    version: str | None = Field(default=None, min_length=1, max_length=50, description="版本号")
    description: str | None = Field(default=None, description="描述信息")
    status: ProcessStatus | None = Field(default=None, description="状态")
    sort_order: int | None = Field(default=None, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessRouteOut(ProcessRouteCreate):
    """工艺路线响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_by: int | None = None
    updated_by: int | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProcessRouteNodeCreate(_TrimTextMixin):
    """创建路线节点链路。"""

    route_id: int = Field(..., gt=0, description="路线ID")
    node_id: int = Field(..., gt=0, description="节点ID")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    node_params_json: str | None = Field(default=None, description="节点参数JSON")
    remark: str | None = Field(default=None, description="备注")


class ProcessRouteNodeUpdate(_TrimTextMixin):
    """更新路线节点链路。"""

    node_id: int | None = Field(default=None, gt=0, description="节点ID")
    sort_order: int | None = Field(default=None, ge=0, le=999999, description="排序值")
    node_params_json: str | None = Field(default=None, description="节点参数JSON")
    remark: str | None = Field(default=None, description="备注")


class ProcessRouteNodeOut(ProcessRouteNodeCreate):
    """路线节点链路响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProcessRouteVersionCreate(_TrimTextMixin):
    """创建路线版本快照。"""

    route_id: int = Field(..., gt=0, description="路线ID")
    version_no: int = Field(..., ge=1, description="版本序号")
    snapshot_json: str = Field(..., min_length=1, description="路线快照JSON")
    change_log: str | None = Field(default=None, description="变更说明")


class ProcessRouteVersionOut(ProcessRouteVersionCreate):
    """路线版本快照响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_by: int | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProcessLibraryRegionPricePayload(_TrimTextMixin):
    """基础库随主数据提交的区域单价，不暴露 owner 字段给前端填写。"""

    region_code: ProcessRegionCode = Field(..., description="区域编码")
    region_name: str | None = Field(default=None, min_length=1, max_length=100, description="区域名称")
    currency: ProcessCurrency | None = Field(default=None, description="币种")
    unit_price: Decimal = Field(default=Decimal("0"), ge=0, description="单位价格")
    unit: str | None = Field(default=None, min_length=1, max_length=50, description="计价单位")
    status: ProcessStatus = Field(default="enabled", description="状态")


class ProcessLibraryCreateWithPrices(ProcessLibraryBase):
    """基础库创建请求，区域单价缺省时由后端补齐三大区域。"""

    region_prices: list[ProcessLibraryRegionPricePayload] = Field(default_factory=list, max_length=3, description="区域单价")


class ProcessLibraryUpdateWithPrices(ProcessLibraryUpdate):
    """基础库编辑请求，传入 region_prices 时整体同步三大区域价格。"""

    region_prices: list[ProcessLibraryRegionPricePayload] | None = Field(default=None, max_length=3, description="区域单价")


class ProcessLibraryStatusUpdate(BaseModel):
    """基础库启用/停用请求。"""

    status: Literal["enabled", "disabled"] = Field(..., description="状态")


class ProcessLibraryOptionOut(BaseModel):
    """基础库下拉选项。"""

    id: int
    code: str
    name: str
    type: str
    unit: str
    status: ProcessStatus


class ProcessLibraryOutWithPrices(ProcessLibraryOut):
    """基础库返回结构，包含已持久化的区域单价。"""

    region_prices: list[ProcessRegionPriceOut] = Field(default_factory=list, description="区域单价")


class ProcessMaterialCreateWithPrices(ProcessLibraryCreateWithPrices):
    """创建原料。"""


class ProcessMaterialUpdateWithPrices(ProcessLibraryUpdateWithPrices):
    """编辑原料。"""


class ProcessMaterialOutWithPrices(ProcessLibraryOutWithPrices):
    """原料详情。"""


class ProcessProductCreateWithPrices(ProcessLibraryCreateWithPrices):
    """创建产品。"""


class ProcessProductUpdateWithPrices(ProcessLibraryUpdateWithPrices):
    """编辑产品。"""


class ProcessProductOutWithPrices(ProcessLibraryOutWithPrices):
    """产品详情。"""


class ProcessConsumableCreateWithPrices(ProcessLibraryCreateWithPrices):
    """创建消耗品。"""


class ProcessConsumableUpdateWithPrices(ProcessLibraryUpdateWithPrices):
    """编辑消耗品。"""


class ProcessConsumableOutWithPrices(ProcessLibraryOutWithPrices):
    """消耗品详情。"""


class ProcessPublicServiceCreateWithPrices(ProcessLibraryCreateWithPrices):
    """创建公共服务。"""


class ProcessPublicServiceUpdateWithPrices(ProcessLibraryUpdateWithPrices):
    """编辑公共服务。"""


class ProcessPublicServiceOutWithPrices(ProcessLibraryOutWithPrices):
    """公共服务详情。"""

class ProcessRouteNodePayload(_TrimTextMixin):
    """Route node payload submitted by the route maintenance API."""

    node_id: int = Field(..., gt=0, description="Node ID")
    sort_order: int = Field(default=0, ge=0, le=999999, description="Sort order")
    node_params_json: str | None = Field(default=None, description="Node params JSON")
    remark: str | None = Field(default=None, description="Remark")


class ProcessRouteCreateWithNodes(ProcessRouteCreate):
    """Create route payload with optional node chain."""

    nodes: list[ProcessRouteNodePayload] = Field(default_factory=list, description="Route nodes")


class ProcessRouteUpdateWithNodes(ProcessRouteUpdate):
    """Update route payload with replace-all node chain semantics."""

    nodes: list[ProcessRouteNodePayload] | None = Field(default=None, description="Route nodes")


class ProcessRouteNodeAddPayload(ProcessRouteNodePayload):
    """Payload for adding a single route node."""


class ProcessRouteNodeReorderItem(BaseModel):
    """Single route node reorder item."""

    route_node_id: int = Field(..., gt=0, description="Route node ID")
    sort_order: int = Field(..., ge=0, le=999999, description="Sort order")


class ProcessRouteNodeReorderPayload(BaseModel):
    """Payload for route node reorder."""

    items: list[ProcessRouteNodeReorderItem] = Field(default_factory=list, description="Reorder items")


class ProcessRouteVersionCreatePayload(_TrimTextMixin):
    """Payload for creating a route snapshot version."""

    version_no: int | None = Field(default=None, ge=1, description="Version number")
    change_log: str | None = Field(default=None, description="Change log")


class ProcessRouteListItemOut(ProcessRouteOut):
    """Route list item."""

    input_material_name: str | None = Field(default=None, description="Input material name")
    final_product_name: str | None = Field(default=None, description="Final product name")
    node_count: int = Field(default=0, ge=0, description="Node count")


class ProcessRouteNodeDetailOut(ProcessRouteNodeOut):
    """Route node detail with full node configuration."""

    node: ProcessNodeOutWithChildren = Field(..., description="Node detail")


class ProcessRouteDetailOut(BaseModel):
    """Full route detail response."""

    route: ProcessRouteOut
    input_material: ProcessMaterialOutWithPrices
    final_product: ProcessProductOutWithPrices
    nodes: list[ProcessRouteNodeDetailOut] = Field(default_factory=list, description="Route nodes")


class ProcessConfigImportErrorOut(BaseModel):
    """Excel 导入错误明细。"""

    sheet: str = Field(..., description="Sheet 名称")
    row: int = Field(..., ge=1, description="Excel 行号")
    field: str = Field(..., description="字段名称")
    message: str = Field(..., description="错误原因")


class ProcessConfigImportResultOut(BaseModel):
    """Excel 导入结果。"""

    module: str = Field(..., description="模块编码")
    imported_count: int = Field(..., ge=0, description="成功导入数量")
    imported_codes: list[str] = Field(default_factory=list, description="导入成功的编码列表")
