"""Process configuration schemas.

职责：
1. 定义工艺配置基础库、节点和路线的请求/响应模型。
2. 约束状态、区域、币种和节点类型使用英文编码入库。
3. 为后续 CRUD、导入导出和权限接口提供统一类型。
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

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
