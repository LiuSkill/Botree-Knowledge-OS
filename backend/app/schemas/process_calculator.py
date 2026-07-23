"""快速财务计算器请求与响应模型。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.process_config import ProcessCurrency, ProcessRegionCode


CalculatorSortCriteria = Literal["npv", "irr", "ebitda", "payback_period", "capex"]


class CalculatorMaterialInput(BaseModel):
    """参与测算的原料及年处理量。"""

    material_id: int = Field(..., gt=0)
    amount: Decimal = Field(..., gt=0)
    unit: str = Field(default="t", min_length=1, max_length=50)

    @field_validator("unit", mode="before")
    @classmethod
    def strip_unit(cls, value: str) -> str:
        return value.strip()


class CalculatorAdvancedParams(BaseModel):
    """MVP 可安全执行的高级参数。"""

    base_capacity: Decimal | None = Field(default=None, gt=0, description="设备投资对应的基准年产能，单位t")
    scale_param_n: Decimal | None = Field(default=None, gt=0, le=1, description="CAPEX规模修正指数")
    other_opex: Decimal = Field(default=Decimal("0"), ge=0, description="年度其他运营成本")
    annual_growth_rate: Decimal = Field(default=Decimal("0"), ge=Decimal("-0.99"), le=Decimal("1"))

    @model_validator(mode="after")
    def validate_scale_params(self) -> "CalculatorAdvancedParams":
        if (self.base_capacity is None) != (self.scale_param_n is None):
            raise ValueError("base_capacity 与 scale_param_n 必须同时填写")
        return self


class ProcessCalculatorRequest(BaseModel):
    """快速财务测算入参。"""

    materials: list[CalculatorMaterialInput] = Field(..., min_length=1, max_length=10)
    target_products: list[int] = Field(..., min_length=1, max_length=10)
    region_code: ProcessRegionCode
    currency: ProcessCurrency
    tax_rate: Decimal = Field(default=Decimal("0.25"), ge=0, le=1)
    discount_rate: Decimal = Field(default=Decimal("0.08"), gt=Decimal("-1"), le=1)
    period_years: int = Field(default=10, ge=1, le=50)
    sort_criteria: CalculatorSortCriteria = "npv"
    advanced_params: CalculatorAdvancedParams = Field(default_factory=CalculatorAdvancedParams)
    parameter_overrides: dict[str, Decimal] = Field(default_factory=dict, max_length=500)

    @field_validator("parameter_overrides")
    @classmethod
    def validate_parameter_overrides(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        if any(not key.strip() or amount < 0 for key, amount in value.items()):
            raise ValueError("测算参数键不能为空且参数值不能小于 0")
        return value

    @model_validator(mode="after")
    def validate_unique_inputs(self) -> "ProcessCalculatorRequest":
        material_ids = [item.material_id for item in self.materials]
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("materials 中不能重复选择同一原料")
        if len(self.target_products) != len(set(self.target_products)):
            raise ValueError("target_products 中不能重复选择同一产品")
        return self


class CalculatorLibraryOption(BaseModel):
    id: int
    code: str
    name: str
    unit: str


class CalculatorRegionOption(BaseModel):
    code: ProcessRegionCode
    name: str
    currency: ProcessCurrency


class ProcessCalculatorOptionsOut(BaseModel):
    materials: list[CalculatorLibraryOption]
    target_products: list[CalculatorLibraryOption]
    regions: list[CalculatorRegionOption]
    sort_criteria: list[dict[str, str]]
    defaults: dict[str, Any]


class CalculatorRouteNodeRef(BaseModel):
    id: int
    code: str
    name: str
    version: str
    sort_order: int


class CalculatorRouteRef(BaseModel):
    id: int
    code: str
    name: str
    input_material_id: int
    input_material_code: str
    input_material_name: str
    final_product_id: int
    final_product_code: str
    final_product_name: str
    node_codes: list[str]
    nodes: list[CalculatorRouteNodeRef]


class CalculatorAmountItem(BaseModel):
    id: int | None = None
    code: str | None = None
    name: str
    output_type: str | None = None
    amount: Decimal
    unit: str
    unit_price: Decimal | None = None
    cost: Decimal = Decimal("0")
    route_id: int | None = None
    node_id: int | None = None


class CalculatorCashFlow(BaseModel):
    year: int
    revenue: Decimal
    opex: Decimal
    tax: Decimal
    net_cash_flow: Decimal
    discounted_cash_flow: Decimal


class CalculatorMaterialBalance(BaseModel):
    input_mass_t: Decimal
    accounted_output_mass_t: Decimal
    difference_mass_t: Decimal
    balance_rate: Decimal | None
    excluded_non_mass_outputs: list[str] = Field(default_factory=list)


class CalculatorMetrics(BaseModel):
    capex: Decimal
    material_cost: Decimal
    consumable_cost: Decimal
    public_service_cost: Decimal
    labor_cost: Decimal = Decimal("0")
    waste_treatment_cost: Decimal
    other_opex: Decimal
    opex: Decimal
    revenue: Decimal
    ebitda: Decimal
    npv: Decimal
    irr: Decimal | None
    payback_period: Decimal | None
    discounted_payback_period: Decimal | None


class CalculatorParameter(BaseModel):
    """推荐方案实际参与计算且允许本次测算覆盖的参数。"""

    key: str
    category: str
    name: str
    value: Decimal
    unit: str


class CalculatorSchemeSummary(BaseModel):
    scheme_code: str
    routes: list[CalculatorRouteRef]
    node_codes: list[str]
    is_complete: bool
    warnings: list[str]
    metrics: CalculatorMetrics


class ProcessCalculatorResultOut(BaseModel):
    calculation_id: str
    matched_routes: list[CalculatorSchemeSummary]
    recommended_route: CalculatorSchemeSummary | None
    product_outputs: list[CalculatorAmountItem]
    consumable_costs: list[CalculatorAmountItem]
    public_service_costs: list[CalculatorAmountItem]
    labor_costs: list[CalculatorAmountItem] = Field(default_factory=list)
    waste_outputs: list[CalculatorAmountItem]
    capex: Decimal
    opex: Decimal
    revenue: Decimal
    ebitda: Decimal
    npv: Decimal
    irr: Decimal | None
    payback_period: Decimal | None
    material_balance: CalculatorMaterialBalance | None
    cash_flows: list[CalculatorCashFlow]
    calculation_parameters: list[CalculatorParameter]
    warnings: list[str]
