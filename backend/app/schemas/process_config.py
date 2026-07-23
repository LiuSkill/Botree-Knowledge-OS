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
ProcessOwnerType = Literal["material", "product", "consumable", "public_service", "labor", "asset"]
ProcessRegionCode = Literal["asia", "europe", "americas"]
ProcessCurrency = Literal["CNY", "EUR", "USD"]
ProcessNodeType = Literal["pretreatment", "hydrometallurgy", "pyrometallurgy", "post_treatment"]
ProcessFormulaType = Literal["fixed", "expression"]
ProcessOutputType = Literal["product", "byproduct", "solid_waste", "wastewater"]
ProcessCalculationImportStatus = Literal["pending", "success", "failed", "partial_success"]


class _TrimTextMixin(BaseModel):
    """统一清理前端传入的文本字段。"""

    @field_validator(
        "code",
        "name",
        "type",
        "unit",
        "region_name",
        "element_code",
        "element_name",
        "output_type",
        "output_name",
        "spec",
        "formula_type",
        "expression",
        "import_type",
        "file_name",
        "file_path",
        "error_message",
        "equipment_name",
        "equipment_type",
        "asset_class",
        "salary_period",
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

    @field_validator("node_params_json", "snapshot_json", "scale_param", mode="before", check_fields=False)
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


class ProcessMaterialCompositionPayload(_TrimTextMixin):
    """原料元素组成配置。"""

    element_code: str = Field(..., min_length=1, max_length=30, description="元素编码")
    element_name: str = Field(..., min_length=1, max_length=100, description="元素名称")
    content_ratio: Decimal = Field(default=Decimal("0"), ge=0, description="含量比例")
    unit: str = Field(default="%", min_length=1, max_length=50, description="单位")
    remark: str | None = Field(default=None, description="备注")


class ProcessMaterialCompositionReplacePayload(BaseModel):
    """整体替换指定原料的元素组成。"""

    items: list[ProcessMaterialCompositionPayload] = Field(default_factory=list, description="元素组成")


class ProcessMaterialCompositionOut(ProcessMaterialCompositionPayload):
    """原料元素组成响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    material_id: int
    created_by: int | None = None
    updated_by: int | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProcessProductCreate(ProcessLibraryBase):
    """创建产品。"""


    output_type: ProcessOutputType = Field(default="product", description="产出物类型")
    spec: str | None = Field(default=None, max_length=100, description="规格")
    treatment_cost: Decimal = Field(default=Decimal("0"), ge=0, description="处理成本")


class ProcessProductUpdate(ProcessLibraryUpdate):
    """更新产品。"""


    output_type: ProcessOutputType | None = Field(default=None, description="产出物类型")
    spec: str | None = Field(default=None, max_length=100, description="规格")
    treatment_cost: Decimal | None = Field(default=None, ge=0, description="处理成本")


class ProcessProductOut(ProcessLibraryOut):
    """产品响应。"""


    output_type: ProcessOutputType = Field(default="product", description="产出物类型")
    spec: str | None = Field(default=None, description="规格")
    treatment_cost: Decimal = Field(default=Decimal("0"), ge=0, description="处理成本")


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
    status: ProcessStatus = Field(default="enabled", description="状态")
    version: str = Field(default="V1", min_length=1, max_length=50, description="版本号")
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


    formula_type: ProcessFormulaType = Field(default="fixed", description="系数类型")
    amount_per_ton_bm: Decimal = Field(default=Decimal("0"), ge=0, description="每吨黑粉BM消耗系数")
    expression: str | None = Field(default=None, description="表达式系数")
    scale_param: str | None = Field(default=None, description="规模修正参数JSON")
    source_template_id: int | None = Field(default=None, gt=0, description="来源测算模板/导入批次ID")
    balance_weight: Decimal = Field(default=Decimal("0"), description="水平衡权重值")


class ProcessNodeConsumableUpdate(_TrimTextMixin):
    """更新节点消耗品。"""

    consumable_id: int | None = Field(default=None, gt=0, description="消耗品ID")
    amount_per_ton: Decimal | None = Field(default=None, ge=0, description="每吨原料消耗量")
    unit: str | None = Field(default=None, min_length=1, max_length=50, description="单位")
    sort_order: int | None = Field(default=None, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


    formula_type: ProcessFormulaType | None = Field(default=None, description="系数类型")
    amount_per_ton_bm: Decimal | None = Field(default=None, ge=0, description="每吨黑粉BM消耗系数")
    expression: str | None = Field(default=None, description="表达式系数")
    scale_param: str | None = Field(default=None, description="规模修正参数JSON")
    source_template_id: int | None = Field(default=None, gt=0, description="来源测算模板/导入批次ID")
    balance_weight: Decimal | None = Field(default=None, description="水平衡权重值")


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


    formula_type: ProcessFormulaType = Field(default="fixed", description="系数类型")
    amount_per_ton_bm: Decimal = Field(default=Decimal("0"), ge=0, description="每吨黑粉BM消耗系数")
    expression: str | None = Field(default=None, description="表达式系数")
    scale_param: str | None = Field(default=None, description="规模修正参数JSON")
    source_template_id: int | None = Field(default=None, gt=0, description="来源测算模板/导入批次ID")
    balance_weight: Decimal = Field(default=Decimal("0"), description="水平衡权重值")


class ProcessNodePublicServiceUpdate(_TrimTextMixin):
    """更新节点公共服务消耗。"""

    public_service_id: int | None = Field(default=None, gt=0, description="公共服务ID")
    amount_per_ton: Decimal | None = Field(default=None, ge=0, description="每吨原料消耗量")
    unit: str | None = Field(default=None, min_length=1, max_length=50, description="单位")
    sort_order: int | None = Field(default=None, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


    formula_type: ProcessFormulaType | None = Field(default=None, description="系数类型")
    amount_per_ton_bm: Decimal | None = Field(default=None, ge=0, description="每吨黑粉BM消耗系数")
    expression: str | None = Field(default=None, description="表达式系数")
    scale_param: str | None = Field(default=None, description="规模修正参数JSON")
    source_template_id: int | None = Field(default=None, gt=0, description="来源测算模板/导入批次ID")
    balance_weight: Decimal | None = Field(default=None, description="水平衡权重值")


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
    asset_id: int | None = Field(default=None, gt=0, description="资产库ID")
    asset_class: str = Field(default="equipment", max_length=30, description="资产类别：equipment/infrastructure")
    equipment_name: str = Field(..., min_length=1, max_length=150, description="设备名称")
    equipment_type: str | None = Field(default=None, max_length=100, description="设备类型")
    quantity: Decimal = Field(default=Decimal("0"), ge=0, description="设备数量")
    installation_factor: Decimal = Field(default=Decimal("1"), ge=0, description="安装/配套系数")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeEquipmentUpdate(_TrimTextMixin):
    """更新节点设备投资。"""

    equipment_name: str | None = Field(default=None, min_length=1, max_length=150, description="设备名称")
    asset_id: int | None = Field(default=None, gt=0, description="资产库ID")
    asset_class: str | None = Field(default=None, max_length=30, description="资产类别：equipment/infrastructure")
    equipment_type: str | None = Field(default=None, max_length=100, description="设备类型")
    quantity: Decimal | None = Field(default=None, ge=0, description="设备数量")
    installation_factor: Decimal | None = Field(default=None, ge=0, description="安装/配套系数")
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


class ProcessNodeLaborCreate(_TrimTextMixin):
    """创建节点人员成本配置。"""

    node_id: int = Field(..., gt=0, description="节点ID")
    labor_cost_id: int = Field(..., gt=0, description="人员成本库ID")
    headcount: Decimal = Field(default=Decimal("0"), ge=0, description="人数")
    load_factor: Decimal = Field(default=Decimal("1"), ge=0, description="负荷系数")
    include_in_opex: bool = Field(default=True, description="是否计入OPEX")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeLaborUpdate(_TrimTextMixin):
    """更新节点人员成本配置。"""

    labor_cost_id: int | None = Field(default=None, gt=0, description="人员成本库ID")
    headcount: Decimal | None = Field(default=None, ge=0, description="人数")
    load_factor: Decimal | None = Field(default=None, ge=0, description="负荷系数")
    include_in_opex: bool | None = Field(default=None, description="是否计入OPEX")
    sort_order: int | None = Field(default=None, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeLaborOut(ProcessNodeLaborCreate):
    """节点人员成本配置响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProcessNodeOutputCreate(_TrimTextMixin):
    """创建节点输出物。"""

    node_id: int = Field(..., gt=0, description="节点ID")
    product_id: int = Field(..., gt=0, description="产品ID")
    output_type: ProcessOutputType = Field(default="product", description="产出物类型")
    output_per_ton: Decimal = Field(default=Decimal("0"), ge=0, description="每吨原料产出量")
    formula_type: ProcessFormulaType = Field(default="fixed", description="系数类型")
    expression: str | None = Field(default=None, description="表达式系数")
    scale_param: str | None = Field(default=None, description="规模修正参数JSON")
    source_template_id: int | None = Field(default=None, gt=0, description="来源测算模板/导入批次ID")
    balance_weight: Decimal = Field(default=Decimal("0"), description="水平衡权重值")
    treatment_cost: Decimal = Field(default=Decimal("0"), ge=0, description="节点处理成本")
    unit: str = Field(..., min_length=1, max_length=50, description="单位")
    is_main_product: bool = Field(default=False, description="是否主产品")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeOutputUpdate(_TrimTextMixin):
    """更新节点输出物。"""

    product_id: int | None = Field(default=None, gt=0, description="产品ID")
    output_type: ProcessOutputType | None = Field(default=None, description="产出物类型")
    output_per_ton: Decimal | None = Field(default=None, ge=0, description="每吨原料产出量")
    formula_type: ProcessFormulaType | None = Field(default=None, description="系数类型")
    expression: str | None = Field(default=None, description="表达式系数")
    scale_param: str | None = Field(default=None, description="规模修正参数JSON")
    source_template_id: int | None = Field(default=None, gt=0, description="来源测算模板/导入批次ID")
    balance_weight: Decimal | None = Field(default=None, description="水平衡权重值")
    treatment_cost: Decimal | None = Field(default=None, ge=0, description="节点处理成本")
    unit: str | None = Field(default=None, min_length=1, max_length=50, description="单位")
    is_main_product: bool | None = Field(default=None, description="是否主产品")
    sort_order: int | None = Field(default=None, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeOutputOut(ProcessNodeOutputCreate):
    """节点输出物响应。"""

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


    formula_type: ProcessFormulaType = Field(default="fixed", description="系数类型")
    amount_per_ton_bm: Decimal = Field(default=Decimal("0"), ge=0, description="每吨黑粉BM消耗系数")
    expression: str | None = Field(default=None, description="表达式系数")
    scale_param: str | None = Field(default=None, description="规模修正参数JSON")
    source_template_id: int | None = Field(default=None, gt=0, description="来源测算模板/导入批次ID")
    balance_weight: Decimal = Field(default=Decimal("0"), description="水平衡权重值")


class ProcessNodePublicServicePayload(_TrimTextMixin):
    """节点维护时提交的公共服务消耗，不要求前端传 node_id。"""

    public_service_id: int = Field(..., gt=0, description="公共服务ID")
    amount_per_ton: Decimal = Field(default=Decimal("0"), ge=0, description="每吨消耗量")
    unit: str = Field(..., min_length=1, max_length=50, description="单位")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


    formula_type: ProcessFormulaType = Field(default="fixed", description="系数类型")
    amount_per_ton_bm: Decimal = Field(default=Decimal("0"), ge=0, description="每吨黑粉BM消耗系数")
    expression: str | None = Field(default=None, description="表达式系数")
    scale_param: str | None = Field(default=None, description="规模修正参数JSON")
    source_template_id: int | None = Field(default=None, gt=0, description="来源测算模板/导入批次ID")
    balance_weight: Decimal = Field(default=Decimal("0"), description="水平衡权重值")


class ProcessNodeEquipmentPayload(_TrimTextMixin):
    """节点维护时提交的设备/投资。"""

    asset_id: int | None = Field(default=None, gt=0, description="资产库ID")
    asset_class: str = Field(default="equipment", max_length=30, description="资产类别：equipment/infrastructure")
    equipment_name: str = Field(..., min_length=1, max_length=150, description="设备名称")
    equipment_type: str | None = Field(default=None, max_length=100, description="设备类型")
    quantity: Decimal = Field(default=Decimal("0"), ge=0, description="设备数量")
    installation_factor: Decimal = Field(default=Decimal("1"), ge=0, description="安装/配套系数")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeLaborPayload(_TrimTextMixin):
    """节点维护时提交的人员成本配置。"""

    labor_cost_id: int = Field(..., gt=0, description="人员成本库ID")
    headcount: Decimal = Field(default=Decimal("0"), ge=0, description="人数")
    load_factor: Decimal = Field(default=Decimal("1"), ge=0, description="负荷系数")
    include_in_opex: bool = Field(default=True, description="是否计入OPEX")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessNodeOutputPayload(_TrimTextMixin):
    """节点维护时提交的输出物，不要求前端传 node_id。"""

    product_id: int = Field(..., gt=0, description="产品ID")
    output_type: ProcessOutputType = Field(default="product", description="产出物类型")
    output_per_ton: Decimal = Field(default=Decimal("0"), ge=0, description="每吨产出量")
    formula_type: ProcessFormulaType = Field(default="fixed", description="系数类型")
    expression: str | None = Field(default=None, description="表达式系数")
    scale_param: str | None = Field(default=None, description="规模修正参数JSON")
    source_template_id: int | None = Field(default=None, gt=0, description="来源测算模板/导入批次ID")
    balance_weight: Decimal = Field(default=Decimal("0"), description="水平衡权重值")
    treatment_cost: Decimal = Field(default=Decimal("0"), ge=0, description="节点处理成本")
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
    labor: list[ProcessNodeLaborPayload] = Field(default_factory=list, description="人员成本")
    outputs: list[ProcessNodeOutputPayload] = Field(default_factory=list, description="输出物")


class ProcessNodeUpdateWithChildren(ProcessNodeUpdate):
    """编辑工艺节点，子配置采用整体替换。"""

    material_inputs: list[ProcessNodeMaterialInputPayload] = Field(default_factory=list, description="输入原料")
    consumables: list[ProcessNodeConsumablePayload] = Field(default_factory=list, description="消耗品")
    public_services: list[ProcessNodePublicServicePayload] = Field(default_factory=list, description="公共服务")
    equipment: list[ProcessNodeEquipmentPayload] = Field(default_factory=list, description="设备/投资")
    labor: list[ProcessNodeLaborPayload] = Field(default_factory=list, description="人员成本")
    outputs: list[ProcessNodeOutputPayload] = Field(default_factory=list, description="输出物")


class ProcessNodeOutWithChildren(ProcessNodeOut):
    """工艺节点详情，包含完整子配置。"""

    material_inputs: list[ProcessNodeMaterialInputOut] = Field(default_factory=list, description="输入原料")
    consumables: list[ProcessNodeConsumableOut] = Field(default_factory=list, description="消耗品")
    public_services: list[ProcessNodePublicServiceOut] = Field(default_factory=list, description="公共服务")
    equipment: list[ProcessNodeEquipmentOut] = Field(default_factory=list, description="设备/投资")
    labor: list[ProcessNodeLaborOut] = Field(default_factory=list, description="人员成本")
    outputs: list[ProcessNodeOutputOut] = Field(default_factory=list, description="输出物")


class ProcessRouteCreate(_TrimTextMixin):
    """创建工艺路线。"""

    code: str = Field(..., min_length=1, max_length=100, description="路线编码")
    name: str = Field(..., min_length=1, max_length=150, description="路线名称")
    input_material_id: int = Field(..., gt=0, description="输入原料ID")
    final_product_id: int = Field(..., gt=0, description="最终产品ID")
    version: str = Field(default="V1", min_length=1, max_length=50, description="版本号")
    description: str | None = Field(default=None, description="描述信息")
    status: ProcessStatus = Field(default="enabled", description="状态")
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

    region_prices: list[ProcessLibraryRegionPricePayload] = Field(default_factory=list, max_length=9, description="区域币种单价")


class ProcessLibraryUpdateWithPrices(ProcessLibraryUpdate):
    """基础库编辑请求，传入 region_prices 时整体同步三大区域价格。"""

    region_prices: list[ProcessLibraryRegionPricePayload] | None = Field(default=None, max_length=9, description="区域币种单价")


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
    asset_class: Literal["equipment", "infrastructure"] | None = None


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


    output_type: ProcessOutputType = Field(default="product", description="产出物类型")
    spec: str | None = Field(default=None, max_length=100, description="规格")
    treatment_cost: Decimal = Field(default=Decimal("0"), ge=0, description="处理成本")


class ProcessProductUpdateWithPrices(ProcessLibraryUpdateWithPrices):
    """编辑产品。"""


    output_type: ProcessOutputType | None = Field(default=None, description="产出物类型")
    spec: str | None = Field(default=None, max_length=100, description="规格")
    treatment_cost: Decimal | None = Field(default=None, ge=0, description="处理成本")


class ProcessProductOutWithPrices(ProcessLibraryOutWithPrices):
    """产品详情。"""


    output_type: ProcessOutputType = Field(default="product", description="产出物类型")
    spec: str | None = Field(default=None, description="规格")
    treatment_cost: Decimal = Field(default=Decimal("0"), ge=0, description="处理成本")


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

class ProcessLaborCostCreateWithPrices(ProcessLibraryCreateWithPrices):
    """创建人员成本。"""

    salary_period: Literal["month", "year"] = Field(default="year", description="薪酬周期")
    welfare_factor: Decimal = Field(default=Decimal("1"), ge=0, description="福利社保系数")


class ProcessLaborCostUpdateWithPrices(ProcessLibraryUpdateWithPrices):
    """编辑人员成本。"""

    salary_period: Literal["month", "year"] | None = Field(default=None, description="薪酬周期")
    welfare_factor: Decimal | None = Field(default=None, ge=0, description="福利社保系数")


class ProcessLaborCostOutWithPrices(ProcessLibraryOutWithPrices):
    """人员成本详情。"""

    salary_period: Literal["month", "year"] = Field(default="year", description="薪酬周期")
    welfare_factor: Decimal = Field(default=Decimal("1"), description="福利社保系数")


class ProcessAssetCreateWithPrices(ProcessLibraryCreateWithPrices):
    """创建设备/基础设施资产。"""

    asset_class: Literal["equipment", "infrastructure"] = Field(default="equipment", description="资产类别")


class ProcessAssetUpdateWithPrices(ProcessLibraryUpdateWithPrices):
    """编辑设备/基础设施资产。"""

    asset_class: Literal["equipment", "infrastructure"] | None = Field(default=None, description="资产类别")


class ProcessAssetOutWithPrices(ProcessLibraryOutWithPrices):
    """设备/基础设施资产详情。"""

    asset_class: Literal["equipment", "infrastructure"] = Field(default="equipment", description="资产类别")


class ProcessCalculationOutputPayload(_TrimTextMixin):
    """路线维度的测算产出系数配置。"""

    output_type: ProcessOutputType = Field(..., description="产出物类型")
    product_id: int | None = Field(default=None, gt=0, description="产品库ID")
    output_name: str = Field(..., min_length=1, max_length=150, description="产出物名称")
    spec: str | None = Field(default=None, max_length=100, description="规格")
    formula_type: ProcessFormulaType = Field(default="fixed", description="系数类型")
    recovery_rate: Decimal = Field(default=Decimal("0"), ge=0, description="收率")
    balance_weight: Decimal = Field(default=Decimal("0"), ge=0, description="水平衡权重值")
    unit: str = Field(..., min_length=1, max_length=50, description="单位")
    output_ratio: Decimal = Field(default=Decimal("0"), ge=0, description="产出系数")
    expression: str | None = Field(default=None, description="表达式系数")
    scale_param: str | None = Field(default=None, description="规模修正参数JSON")
    treatment_cost: Decimal = Field(default=Decimal("0"), ge=0, description="处理成本")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序值")
    remark: str | None = Field(default=None, description="备注")


class ProcessCalculationOutputReplacePayload(BaseModel):
    """整体替换指定路线的测算产出配置。"""

    items: list[ProcessCalculationOutputPayload] = Field(default_factory=list, description="测算产出配置")


class ProcessCalculationOutputOut(ProcessCalculationOutputPayload):
    """路线测算产出系数响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    route_id: int
    created_by: int | None = None
    updated_by: int | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


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


class ProcessRouteTreeLibraryItemOut(BaseModel):
    """路线树预览中的基础库精简信息。"""

    id: int
    code: str
    name: str
    unit: str | None = None
    output_type: str | None = None


class ProcessRouteTreeNodeOutputOut(BaseModel):
    """路线树预览中的节点三废输出。"""

    id: int
    product_id: int
    output_type: ProcessOutputType
    product: ProcessRouteTreeLibraryItemOut | None = None


class ProcessRouteTreeNodeOut(BaseModel):
    """路线树预览中的工艺节点精简信息。"""

    route_node_id: int
    node_id: int
    code: str
    name: str
    node_type: ProcessNodeType
    version: str
    sort_order: int
    outputs: list[ProcessRouteTreeNodeOutputOut] = Field(default_factory=list, description="节点三废输出")


class ProcessRouteTreeRouteOut(BaseModel):
    """路线树预览中的路线精简信息。"""

    id: int
    code: str
    name: str
    version: str
    sort_order: int
    input_material: ProcessRouteTreeLibraryItemOut
    final_product: ProcessRouteTreeLibraryItemOut
    nodes: list[ProcessRouteTreeNodeOut] = Field(default_factory=list, description="路线节点")


class ProcessRouteTreePreviewOut(BaseModel):
    """工艺路线完整树预览数据。"""

    current_route_id: int
    routes: list[ProcessRouteTreeRouteOut] = Field(default_factory=list, description="完整路线树数据")


class ProcessCalculationImportBatchOut(_TrimTextMixin):
    """快速财务计算器 Excel 导入批次响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str
    file_path: str | None = None
    import_type: str
    status: ProcessCalculationImportStatus
    success_count: int = Field(default=0, ge=0, description="成功数量")
    failed_count: int = Field(default=0, ge=0, description="失败数量")
    error_message: str | None = None
    created_by: int | None = None
    updated_by: int | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


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
