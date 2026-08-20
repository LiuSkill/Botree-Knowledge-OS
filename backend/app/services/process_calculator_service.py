"""快速财务计算器业务服务。"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from itertools import product
import logging
from time import perf_counter
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.models.process_config import ProcessCalculationOutput, ProcessNodeOutput, ProcessRoute
from app.repositories.process_calculator_repository import ProcessCalculatorRepository
from app.schemas.process_calculator import (
    CalculatorAdvancedParams,
    CalculatorAmountItem,
    CalculatorCashFlow,
    CalculatorMaterialBalance,
    CalculatorMetrics,
    CalculatorParameter,
    CalculatorRouteNodeRef,
    CalculatorRouteRef,
    CalculatorSchemeSummary,
    ProcessCalculatorOptionsOut,
    ProcessCalculatorRequest,
    ProcessCalculatorResultOut,
)

logger = logging.getLogger(__name__)

REGIONS: tuple[dict[str, str], ...] = (
    {"code": "asia", "name": "亚洲", "currency": "CNY"},
    {"code": "europe", "name": "欧洲", "currency": "EUR"},
    {"code": "americas", "name": "美洲", "currency": "USD"},
)
REGION_CURRENCY = {item["code"]: item["currency"] for item in REGIONS}
MAX_ROUTES_PER_PRODUCT = 5
MAX_ROUTE_COMBINATIONS = 100
MAX_OPTION_PROFILES = 5000
MAX_RESULT_SCHEMES = 3
ZERO = Decimal("0")
ONE = Decimal("1")
MONEY_QUANT = Decimal("0.01")
AMOUNT_QUANT = Decimal("0.000001")
WASTE_OUTPUT_TYPES = ("solid_waste", "wastewater", "waste_gas")
PRODUCT_OUTPUT_TYPES = ("product", "byproduct")
TERMINAL_OUTPUT_TYPES = (*PRODUCT_OUTPUT_TYPES, *WASTE_OUTPUT_TYPES)
TARGET_OUTPUT_CATEGORY_OPTIONS: tuple[dict[str, str], ...] = (
    {"code": "li", "name": "Li 产品"},
    {"code": "ni", "name": "Ni 产品"},
    {"code": "co", "name": "Co 产品"},
    {"code": "mn", "name": "Mn 产品"},
    {"code": "cu", "name": "Cu 产品"},
    {"code": "graphite", "name": "石墨产品"},
)
# 兼容旧工艺路线数据：历史 route_node 未写 option 字段时，按图纸关键节点编码反推互斥工艺选项。
NODE_OPTION_FALLBACKS: dict[str, tuple[str, str]] = {
    "A1": ("root_leach_path", "mixed_acid_roasting"),
    "A2": ("root_leach_path", "acid_leaching"),
    "B8": ("water_leach_residue_path", "residue_acid_leaching"),
    "B9": ("water_leach_residue_path", "oxide_ni_co_slag_product"),
    "B3": ("graphite_handling", "drying"),
    "B4": ("copper_removal", "iron_powder"),
    "B5": ("copper_removal", "sulfide"),
    "B6": ("copper_removal", "extraction"),
    "B7": ("graphite_handling", "untreated_solid_waste"),
    "D1": ("lithium_purification", "prel_resin_defluorination"),
    "D2": ("lithium_purification", "deep_chemical_purification"),
    "E3": ("nickel_cobalt_manganese_path", "mhp_precipitation"),
    "E4": ("nickel_cobalt_manganese_path", "p204_extraction"),
    "F1": ("lithium_carbonate_finish", "industrial_drying"),
    "F2": ("lithium_carbonate_finish", "carbonation_thermal_decomposition"),
    "F5": ("manganese_product_path", "manganese_solution_purification"),
    "F6": ("ni_co_separation", "bc196_coextraction"),
    "F7": ("ni_co_separation", "p507_cobalt_extraction"),
    "F8": ("ni_co_separation", "p507_cobalt_extraction"),
    "F10": ("manganese_product_path", "manganese_carbonate_precipitation"),
    "G5": ("ni_co_separation", "c272_cobalt_extraction"),
}
MIXED_ACID_NODE_CODE = "A1"
MIXED_ACID_TAIL_GAS_NODE_CODE = "B1"
MIXED_ACID_WATER_LEACH_NODE_CODE = "B2"


class ProcessCalculatorService:
    """负责路线组合、配置聚合和财务指标计算。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = ProcessCalculatorRepository(db)

    def get_options(self) -> dict[str, Any]:
        data = self.repository.list_options()
        result = ProcessCalculatorOptionsOut(
            materials=[self._library_option(item) for item in data["materials"]],
            target_products=[self._library_option(item) for item in data["products"]],
            target_output_categories=list(TARGET_OUTPUT_CATEGORY_OPTIONS),
            regions=list(REGIONS),
            sort_criteria=[
                {"code": "npv", "name": "净现值最高"},
                {"code": "irr", "name": "内部收益率最高"},
                {"code": "ebitda", "name": "EBITDA最高"},
                {"code": "payback_period", "name": "回收期最短"},
                {"code": "capex", "name": "CAPEX最低"},
            ],
            defaults={
                "tax_rate": Decimal("0.25"),
                "discount_rate": Decimal("0.08"),
                "period_years": 10,
                "sort_criteria": "npv",
            },
        )
        return result.model_dump(mode="json")

    def calculate(self, payload: ProcessCalculatorRequest) -> dict[str, Any]:
        calculation_id = uuid4().hex
        started_at = perf_counter()
        self._validate_region_currency(payload.region_code, payload.currency)
        material_ids = {item.material_id for item in payload.materials}
        product_ids = set(payload.target_products)
        category_mode = bool(payload.target_output_categories)
        data = self.repository.load_calculation_data(
            material_ids,
            product_ids,
            payload.region_code,
            include_all_material_routes=category_mode,
        )
        self._validate_master_data(payload, data)
        context = self._build_context(payload, data)

        material_order = [item.material_id for item in payload.materials]
        if category_mode:
            combinations = list(self._category_route_combinations(material_order, data["routes"], context))
            if not combinations:
                result = self._build_result(
                    calculation_id,
                    [],
                    None,
                    no_route_reason="所选工艺选项没有匹配到合法候选工艺路线",
                )
                return result.model_dump(mode="json")
            details = [self._calculate_scheme(combo, context) for combo in combinations]
            details = [item for item in details if self._matches_target_output_categories(item, context)]
            if not details:
                result = self._build_result(
                    calculation_id,
                    [],
                    None,
                    no_route_reason="候选工艺路线未同时满足所选目标产出类别",
                )
                return result.model_dump(mode="json")
        else:
            grouped_routes = self._group_candidate_routes(material_order, payload.target_products, data["routes"])
            combinations = list(self._route_combinations(material_order, payload.target_products, grouped_routes))
            if not combinations:
                raise AppException("未找到能够覆盖全部目标产品的启用工艺路线")
            details = [self._calculate_scheme(combo, context) for combo in combinations]
        if category_mode:
            details.sort(key=lambda item: self._category_scheme_sort_key(item, context, payload.sort_criteria))
        else:
            details.sort(key=lambda item: self._scheme_sort_key(item["summary"], payload.sort_criteria))
        # 所有候选组合先参与排序，再截取前三条，避免前端截断导致推荐结果失真。
        ranked_details = details[:MAX_RESULT_SCHEMES]
        recommended = ranked_details[0] if ranked_details else None
        result = self._build_result(calculation_id, ranked_details, recommended)
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.info(
            "快速财务测算完成 calculation_id=%s material_count=%s product_count=%s scheme_count=%s status=%s elapsed_ms=%s",
            calculation_id,
            len(payload.materials),
            len(payload.target_products),
            len(ranked_details),
            "complete" if recommended and recommended["summary"].is_complete else "warning",
            elapsed_ms,
        )
        return result.model_dump(mode="json")

    def _validate_region_currency(self, region_code: str, currency: str) -> None:
        expected = REGION_CURRENCY[region_code]
        if currency != expected:
            raise AppException(f"{region_code} 区域当前仅支持 {expected}，系统未配置汇率，不能换算为 {currency}")

    def _validate_master_data(self, payload: ProcessCalculatorRequest, data: dict[str, list[Any]]) -> None:
        actual_material_ids = {item.id for item in data["materials"]}
        missing_materials = [item.material_id for item in payload.materials if item.material_id not in actual_material_ids]
        if missing_materials:
            raise AppException(f"原料不存在或未启用：{missing_materials}")
        actual_product_ids = {item.id for item in data["target_products"]}
        missing_products = [item_id for item_id in payload.target_products if item_id not in actual_product_ids]
        if missing_products:
            raise AppException(f"目标产品不存在、未启用或不是产品类型：{missing_products}")
        for item in payload.materials:
            self._to_tons(item.amount, item.unit)

    def _group_candidate_routes(
        self,
        material_ids: list[int],
        target_products: list[int],
        routes: list[ProcessRoute],
    ) -> dict[tuple[int, int], list[ProcessRoute]]:
        grouped: dict[tuple[int, int], list[ProcessRoute]] = defaultdict(list)
        for route in routes:
            grouped[(route.input_material_id, route.final_product_id)].append(route)
        expected_pairs = [(material_id, product_id) for material_id in material_ids for product_id in target_products]
        missing = [pair for pair in expected_pairs if not grouped[pair]]
        if missing:
            labels = [f"原料{material_id}/产品{product_id}" for material_id, product_id in missing]
            raise AppException("以下原料与目标产品组合没有匹配到启用路线：" + "、".join(labels))
        return {pair: grouped[pair][:MAX_ROUTES_PER_PRODUCT] for pair in expected_pairs}

    def _route_combinations(
        self,
        material_ids: list[int],
        target_products: list[int],
        grouped_routes: dict[tuple[int, int], list[ProcessRoute]],
    ) -> Iterable[tuple[ProcessRoute, ...]]:
        count = 0
        route_groups = [
            grouped_routes[(material_id, product_id)]
            for material_id in material_ids
            for product_id in target_products
        ]
        for combination in product(*route_groups):
            if count >= MAX_ROUTE_COMBINATIONS:
                break
            count += 1
            yield combination

    def _category_route_combinations(
        self,
        material_ids: list[int],
        routes: list[ProcessRoute],
        context: dict[str, Any],
    ) -> Iterable[tuple[ProcessRoute, ...]]:
        selected_options = context["payload"].selected_options
        routes_by_material: dict[int, list[tuple[ProcessRoute, dict[str, str]]]] = defaultdict(list)
        for route in routes:
            options = self._route_selected_options(route, context)
            if options is None:
                continue
            if not self._route_options_match_user_selection(options, selected_options):
                continue
            routes_by_material[route.input_material_id].append((route, options))

        route_groups: list[list[tuple[ProcessRoute, ...]]] = []
        for material_id in material_ids:
            material_groups = self._complete_material_candidate_groups(
                routes_by_material.get(material_id, []),
                selected_options,
                context,
            )
            if not material_groups:
                return
            route_groups.append(material_groups)
        count = 0
        for combination in product(*route_groups):
            if count >= MAX_ROUTE_COMBINATIONS:
                break
            count += 1
            yield tuple(route for group in combination for route in group)

    def _complete_material_candidate_groups(
        self,
        routes_with_options: list[tuple[ProcessRoute, dict[str, str]]],
        selected_options: dict[str, str],
        context: dict[str, Any],
    ) -> list[tuple[ProcessRoute, ...]]:
        candidate_options = self._candidate_option_profiles(routes_with_options, selected_options)
        result: list[tuple[ProcessRoute, ...]] = []
        seen_route_sets: set[tuple[int, ...]] = set()
        for profile in candidate_options:
            routes = [
                route
                for route, route_options in routes_with_options
                if self._route_options_are_subset(route_options, profile)
            ]
            route_ids = tuple(sorted(route.id for route in routes))
            if not route_ids or route_ids in seen_route_sets:
                continue
            seen_route_sets.add(route_ids)
            result.append(tuple(routes))
        target_categories = set(context["payload"].target_output_categories)
        if target_categories:
            result.sort(
                key=lambda routes: self._category_group_score(routes, context, target_categories),
                reverse=True,
            )
        return result[:MAX_ROUTE_COMBINATIONS]

    @staticmethod
    def _category_group_score(
        routes: tuple[ProcessRoute, ...],
        context: dict[str, Any],
        target_categories: set[str],
    ) -> tuple[int, int, int]:
        categories = {
            product.target_output_category
            for route in routes
            if (product := context["products"].get(route.final_product_id)) is not None
            and product.target_output_category
        }
        return (len(categories & target_categories), -len(categories - target_categories), -len(routes))

    def _candidate_option_profiles(
        self,
        routes_with_options: list[tuple[ProcessRoute, dict[str, str]]],
        selected_options: dict[str, str],
    ) -> list[dict[str, str]]:
        profiles: list[dict[str, str]] = [dict(selected_options)]
        seen_profiles = {self._option_profile_key(selected_options)}
        for _, options in routes_with_options:
            for existing_profile in list(profiles):
                profile = self._merge_route_options(existing_profile, options)
                if profile is None:
                    continue
                profile_key = self._option_profile_key(profile)
                if profile_key in seen_profiles:
                    continue
                seen_profiles.add(profile_key)
                profiles.append(profile)
                if len(profiles) >= MAX_OPTION_PROFILES:
                    break
            if len(profiles) >= MAX_OPTION_PROFILES:
                break
        candidates = list(profiles)
        maximal_profiles = [
            profile
            for profile in candidates
            if not any(
                profile != other and self._route_options_are_subset(profile, other)
                for other in candidates
            )
        ]
        return maximal_profiles[:MAX_OPTION_PROFILES]

    @staticmethod
    def _option_profile_key(profile: dict[str, str]) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(profile.items()))

    @staticmethod
    def _merge_route_options(base_options: dict[str, str], route_options: dict[str, str]) -> dict[str, str] | None:
        merged = dict(base_options)
        for group_code, option_code in route_options.items():
            existing = merged.get(group_code)
            if existing is not None and existing != option_code:
                return None
            merged[group_code] = option_code
        return merged

    def _profile_is_covered_by_existing_profile(self, profile: dict[str, str], profiles: list[dict[str, str]]) -> bool:
        return any(self._route_options_are_subset(profile, existing) for existing in profiles)

    @staticmethod
    def _route_options_are_subset(route_options: dict[str, str], candidate_options: dict[str, str]) -> bool:
        return all(candidate_options.get(group_code) == option_code for group_code, option_code in route_options.items())

    def _route_selected_options(self, route: ProcessRoute, context: dict[str, Any]) -> dict[str, str] | None:
        result: dict[str, str] = {}
        node_codes: set[str] = set()
        for relation in context["route_nodes"].get(route.id, []):
            node = context["nodes"].get(relation.node_id)
            node_code = node.code if node else None
            if node_code:
                node_codes.add(node_code)
            option_group_code = relation.option_group_code
            option_code = relation.option_code
            if not option_group_code:
                fallback = NODE_OPTION_FALLBACKS.get(node_code or "")
                if not fallback:
                    continue
                option_group_code, option_code = fallback
            elif not option_code:
                return None
            existing = result.get(option_group_code)
            if existing is not None and existing != option_code:
                return None
            result[option_group_code] = option_code
        if MIXED_ACID_NODE_CODE in node_codes and (
            MIXED_ACID_TAIL_GAS_NODE_CODE not in node_codes
            or MIXED_ACID_WATER_LEACH_NODE_CODE not in node_codes
        ):
            return None
        return result

    @staticmethod
    def _route_options_match_user_selection(route_options: dict[str, str], selected_options: dict[str, str]) -> bool:
        return all(route_options.get(group_code) == option_code for group_code, option_code in selected_options.items())

    def _build_context(self, payload: ProcessCalculatorRequest, data: dict[str, list[Any]]) -> dict[str, Any]:
        route_nodes: dict[int, list[Any]] = defaultdict(list)
        for item in data["route_nodes"]:
            route_nodes[item.route_id].append(item)
        child_maps: dict[str, dict[int, list[Any]]] = {}
        for key in ("node_consumables", "node_public_services", "node_equipment", "node_labor", "node_outputs"):
            grouped: dict[int, list[Any]] = defaultdict(list)
            for item in data[key]:
                grouped[item.node_id].append(item)
            child_maps[key] = grouped
        calculation_outputs: dict[int, list[ProcessCalculationOutput]] = defaultdict(list)
        for item in data["calculation_outputs"]:
            calculation_outputs[item.route_id].append(item)
        return {
            "payload": payload,
            "parameter_overrides": payload.parameter_overrides,
            "material_amount_t": {
                item.material_id: self._to_tons(item.amount, item.unit) for item in payload.materials
            },
            "materials": {item.id: item for item in data["materials"]},
            "products": {item.id: item for item in data["products"]},
            "nodes": {item.id: item for item in data["nodes"]},
            "consumables": {item.id: item for item in data["consumables"]},
            "public_services": {item.id: item for item in data["public_services"]},
            "labor_costs": {item.id: item for item in data["labor_costs"]},
            "assets": {item.id: item for item in data["assets"]},
            "prices": {(item.owner_type, item.owner_id): item for item in data["prices"]},
            "route_nodes": route_nodes,
            "calculation_outputs": calculation_outputs,
            **child_maps,
        }

    def _calculate_scheme(self, routes: tuple[ProcessRoute, ...], context: dict[str, Any]) -> dict[str, Any]:
        warnings: list[str] = []
        context["active_routes"] = routes
        unique_node_ids, node_materials = self._collect_nodes(routes, context["route_nodes"])
        node_amounts = {
            node_id: sum((context["material_amount_t"][material_id] for material_id in material_ids), ZERO)
            for node_id, material_ids in node_materials.items()
        }
        product_outputs = self._calculate_product_outputs(routes, context, warnings, unique_node_ids, node_amounts)
        consumable_costs = self._calculate_relation_costs(
            unique_node_ids, node_amounts, context, warnings, relation_key="node_consumables"
        )
        public_service_costs = self._calculate_relation_costs(
            unique_node_ids, node_amounts, context, warnings, relation_key="node_public_services"
        )
        labor_costs = self._calculate_labor_costs(unique_node_ids, context, warnings)
        waste_outputs = self._calculate_waste_outputs(unique_node_ids, node_amounts, context, warnings)
        material_cost = self._calculate_material_cost(routes, context, warnings)
        revenue = sum((item.cost for item in product_outputs), ZERO)
        consumable_cost = sum((item.cost for item in consumable_costs), ZERO)
        public_service_cost = sum((item.cost for item in public_service_costs), ZERO)
        labor_cost = sum((item.cost for item in labor_costs), ZERO)
        waste_treatment_cost = sum((item.cost for item in waste_outputs), ZERO)
        capex = self._calculate_capex(unique_node_ids, context, warnings)
        calculation_parameters = self._build_calculation_parameters(routes, unique_node_ids, context)
        other_opex = context["payload"].advanced_params.other_opex
        opex = material_cost + consumable_cost + public_service_cost + labor_cost + waste_treatment_cost + other_opex
        ebitda = revenue - opex
        cash_flows, npv, irr, payback, discounted_payback = self._calculate_cash_flows(
            revenue, opex, capex, context["payload"]
        )
        material_balance = self._calculate_material_balance(
            routes, product_outputs, waste_outputs, context, warnings
        )
        metrics = CalculatorMetrics(
            capex=self._money(capex),
            material_cost=self._money(material_cost),
            consumable_cost=self._money(consumable_cost),
            public_service_cost=self._money(public_service_cost),
            labor_cost=self._money(labor_cost),
            waste_treatment_cost=self._money(waste_treatment_cost),
            other_opex=self._money(other_opex),
            opex=self._money(opex),
            revenue=self._money(revenue),
            ebitda=self._money(ebitda),
            npv=self._money(npv),
            irr=self._ratio(irr),
            payback_period=self._ratio(payback),
            discounted_payback_period=self._ratio(discounted_payback),
        )
        route_refs = self._route_refs(routes, context)
        output_summary = self._build_output_summary(product_outputs, waste_outputs)
        summary = CalculatorSchemeSummary(
            scheme_code=" + ".join(route.code for route in routes),
            routes=route_refs,
            node_codes=[context["nodes"][node_id].code for node_id in unique_node_ids if node_id in context["nodes"]],
            selected_options=self._scheme_selected_options(routes, context),
            output_summary=output_summary,
            is_complete=not warnings,
            warnings=self._dedupe(warnings),
            metrics=metrics,
        )
        detail = {
            "summary": summary,
            "product_outputs": product_outputs,
            "consumable_costs": consumable_costs,
            "public_service_costs": public_service_costs,
            "labor_costs": labor_costs,
            "waste_outputs": waste_outputs,
            "material_balance": material_balance,
            "cash_flows": cash_flows,
            "calculation_parameters": calculation_parameters,
        }
        context.pop("active_routes", None)
        return detail

    def _build_output_summary(
        self,
        product_outputs: list[CalculatorAmountItem],
        waste_outputs: list[CalculatorAmountItem],
    ) -> list[CalculatorAmountItem]:
        return [*product_outputs, *waste_outputs]

    def _scheme_selected_options(self, routes: tuple[ProcessRoute, ...], context: dict[str, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        for route in routes:
            route_options = self._route_selected_options(route, context)
            if route_options:
                result.update(route_options)
        return result

    def _matches_target_output_categories(self, detail: dict[str, Any], context: dict[str, Any]) -> bool:
        required_categories = set(context["payload"].target_output_categories)
        if not required_categories:
            return True
        matched_categories = self._scheme_output_categories(detail["summary"], context)
        return required_categories.issubset(matched_categories)

    def _category_scheme_sort_key(
        self,
        detail: dict[str, Any],
        context: dict[str, Any],
        criteria: str,
    ) -> tuple[Any, ...]:
        """目标类别模式下先按结构贴合度推荐，再在同类候选中使用财务指标排序。"""

        required_categories = set(context["payload"].target_output_categories)
        matched_categories = self._scheme_output_categories(detail["summary"], context)
        extra_categories = matched_categories - required_categories
        return (
            len(required_categories - matched_categories),
            len(extra_categories),
            len(detail["summary"].routes),
            self._scheme_sort_key(detail["summary"], criteria),
        )

    def _scheme_output_categories(
        self,
        summary: CalculatorSchemeSummary,
        context: dict[str, Any],
    ) -> set[str]:
        matched_categories: set[str] = set()
        for item in summary.output_summary:
            if item.output_type not in PRODUCT_OUTPUT_TYPES or item.id is None:
                continue
            product_library = context["products"].get(item.id)
            if not product_library or not product_library.is_product_form:
                continue
            category = product_library.target_output_category
            if category:
                matched_categories.add(category)
        return matched_categories

    def _collect_nodes(
        self,
        routes: tuple[ProcessRoute, ...],
        route_nodes: dict[int, list[Any]],
    ) -> tuple[list[int], dict[int, set[int]]]:
        unique_node_ids: list[int] = []
        seen: set[int] = set()
        node_materials: dict[int, set[int]] = defaultdict(set)
        for route in routes:
            for relation in route_nodes.get(route.id, []):
                node_materials[relation.node_id].add(route.input_material_id)
                if relation.node_id not in seen:
                    seen.add(relation.node_id)
                    unique_node_ids.append(relation.node_id)
        return unique_node_ids, node_materials

    def _calculate_product_outputs(
        self,
        routes: tuple[ProcessRoute, ...],
        context: dict[str, Any],
        warnings: list[str],
        node_ids: list[int],
        node_amounts: dict[int, Decimal],
    ) -> list[CalculatorAmountItem]:
        result: list[CalculatorAmountItem] = []
        seen_product_ids: set[int] = set()
        for route in routes:
            outputs = [
                item
                for item in context["calculation_outputs"].get(route.id, [])
                if item.output_type in PRODUCT_OUTPUT_TYPES and self._is_product_form_output(item.product_id, context)
            ]
            if not outputs:
                outputs = self._fallback_node_product_outputs(route, context)
            if not outputs:
                warnings.append(f"路线 {route.code} 未配置产品产出系数")
                continue
            route_amount = context["material_amount_t"][route.input_material_id]
            for output in outputs:
                ratio = self._parameter_value(context, f"product_output:{output.id}:ratio", output.output_ratio)
                if ratio <= 0:
                    if output.formula_type == "expression":
                        warnings.append(f"{output.output_name} 使用表达式系数且没有可用的结构化数值")
                    else:
                        warnings.append(f"{output.output_name} 的产出系数未配置")
                    ratio = ZERO
                if output.formula_type == "expression":
                    warnings.append(f"{output.output_name} 使用已导入的结构化系数，未执行原表达式")
                if output.recovery_rate <= 0:
                    warnings.append(f"{output.output_name} 未配置收率，当前仅按产出系数计算")
                # Excel 导入后的 output_ratio 已经折算为最终 t/t-BM 产出系数，
                # 这里直接按系数计算，避免再次叠乘收率导致结果偏小。
                amount = route_amount * ratio
                amount_unit = self._coefficient_output_unit(output.unit)
                library = context["products"].get(output.product_id) if output.product_id else None
                unit_price, revenue = self._priced_amount(
                    "product", output.product_id, amount, amount_unit, context, warnings, output.output_name
                )
                result.append(
                    CalculatorAmountItem(
                        id=output.product_id,
                        code=getattr(library, "code", None),
                        name=output.output_name,
                        output_type=output.output_type,
                        amount=self._amount(amount),
                        unit=amount_unit,
                        unit_price=unit_price,
                        cost=self._money(revenue),
                        route_id=route.id,
                    )
                )
                if output.product_id is not None:
                    seen_product_ids.add(output.product_id)
        result.extend(self._calculate_node_product_outputs(node_ids, node_amounts, context, warnings, seen_product_ids))
        return result

    def _calculate_node_product_outputs(
        self,
        node_ids: list[int],
        node_amounts: dict[int, Decimal],
        context: dict[str, Any],
        warnings: list[str],
        seen_product_ids: set[int],
    ) -> list[CalculatorAmountItem]:
        result: list[CalculatorAmountItem] = []
        for node_id in node_ids:
            for output in context["node_outputs"].get(node_id, []):
                if output.output_type not in PRODUCT_OUTPUT_TYPES or not self._is_product_form_output(output.product_id, context):
                    continue
                if output.product_id in seen_product_ids:
                    continue
                library = context["products"].get(output.product_id)
                name = library.name if library else f"节点产出物{output.product_id}"
                coefficient = self._parameter_value(context, f"node_product_output:{output.id}:coefficient", output.output_per_ton)
                if coefficient <= 0:
                    if output.formula_type == "expression":
                        warnings.append(f"节点 {context['nodes'][node_id].code} 的{name}表达式没有可用的结构化数值")
                    else:
                        warnings.append(f"节点 {context['nodes'][node_id].code} 的{name}产出系数未配置")
                    continue
                if output.formula_type == "expression":
                    warnings.append(f"节点 {context['nodes'][node_id].code} 的{name}使用已导入的结构化系数")
                amount = node_amounts[node_id] * coefficient
                amount_unit = self._coefficient_output_unit(output.unit)
                unit_price, revenue = self._priced_amount(
                    "product", output.product_id, amount, amount_unit, context, warnings, name
                )
                result.append(
                    CalculatorAmountItem(
                        id=output.product_id,
                        code=getattr(library, "code", None),
                        name=name,
                        output_type=output.output_type,
                        amount=self._amount(amount),
                        unit=amount_unit,
                        unit_price=unit_price,
                        cost=self._money(revenue),
                        node_id=node_id,
                    )
                )
                if output.product_id is not None:
                    seen_product_ids.add(output.product_id)
        return result

    def _fallback_node_product_outputs(self, route: ProcessRoute, context: dict[str, Any]) -> list[Any]:
        relations = context["route_nodes"].get(route.id, [])
        result: list[Any] = []
        for relation in relations:
            for output in context["node_outputs"].get(relation.node_id, []):
                if output.output_type in PRODUCT_OUTPUT_TYPES and self._is_product_form_output(output.product_id, context):
                    result.append(_NodeOutputAdapter(output, context["products"].get(output.product_id)))
        return result

    @staticmethod
    def _is_product_form_output(product_id: int | None, context: dict[str, Any]) -> bool:
        if product_id is None:
            return True
        product_library = context["products"].get(product_id)
        return product_library is None or bool(product_library.is_product_form)

    def _calculate_relation_costs(
        self,
        node_ids: list[int],
        node_amounts: dict[int, Decimal],
        context: dict[str, Any],
        warnings: list[str],
        *,
        relation_key: str,
    ) -> list[CalculatorAmountItem]:
        is_consumable = relation_key == "node_consumables"
        id_field = "consumable_id" if is_consumable else "public_service_id"
        owner_type = "consumable" if is_consumable else "public_service"
        libraries = context["consumables"] if is_consumable else context["public_services"]
        totals: dict[tuple[int, str], Decimal] = defaultdict(lambda: ZERO)
        for node_id in node_ids:
            for relation in context[relation_key].get(node_id, []):
                library_id = getattr(relation, id_field)
                library = libraries.get(library_id)
                name = library.name if library else str(library_id)
                default_coefficient = relation.amount_per_ton_bm if relation.amount_per_ton_bm != 0 else relation.amount_per_ton
                coefficient = self._parameter_value(context, f"{owner_type}:{relation.id}:coefficient", default_coefficient)
                if coefficient <= 0:
                    if relation.formula_type == "expression":
                        warnings.append(f"节点 {context['nodes'][node_id].code} 的{name}表达式没有可用的结构化数值")
                    else:
                        warnings.append(f"节点 {context['nodes'][node_id].code} 的{name}消耗系数未配置")
                    continue
                if relation.formula_type == "expression":
                    warnings.append(f"节点 {context['nodes'][node_id].code} 的{name}使用已导入的结构化系数")
                amount_unit = self._coefficient_output_unit(relation.unit)
                totals[(library_id, amount_unit)] += node_amounts[node_id] * coefficient
        result: list[CalculatorAmountItem] = []
        for (library_id, unit), amount in totals.items():
            library = libraries.get(library_id)
            name = library.name if library else str(library_id)
            price, cost = self._priced_amount(owner_type, library_id, amount, unit, context, warnings, name)
            result.append(
                CalculatorAmountItem(
                    id=library_id,
                    code=getattr(library, "code", None),
                    name=name,
                    amount=self._amount(amount),
                    unit=unit,
                    unit_price=price,
                    cost=self._money(cost),
                )
            )
        return result

    def _calculate_waste_outputs(
        self,
        node_ids: list[int],
        node_amounts: dict[int, Decimal],
        context: dict[str, Any],
        warnings: list[str],
    ) -> list[CalculatorAmountItem]:
        result: list[CalculatorAmountItem] = []
        result.extend(self._calculate_route_waste_outputs(context, warnings))
        for node_id in node_ids:
            for output in context["node_outputs"].get(node_id, []):
                if output.output_type not in WASTE_OUTPUT_TYPES:
                    continue
                library = context["products"].get(output.product_id)
                name = library.name if library else f"节点产出物{output.product_id}"
                coefficient = self._parameter_value(context, f"waste_output:{output.id}:coefficient", output.output_per_ton)
                is_zero_waste_gas = coefficient <= 0 and output.output_type == "waste_gas"
                if coefficient <= 0:
                    if is_zero_waste_gas:
                        coefficient = ZERO
                    else:
                        if output.formula_type == "expression":
                            warnings.append(f"节点 {context['nodes'][node_id].code} 的{name}表达式没有可用的结构化数值")
                        else:
                            warnings.append(f"节点 {context['nodes'][node_id].code} 的{name}产出系数未配置")
                        continue
                if output.formula_type == "expression" and not is_zero_waste_gas:
                    warnings.append(f"节点 {context['nodes'][node_id].code} 的{name}使用已导入的结构化系数")
                amount = node_amounts[node_id] * coefficient
                amount_unit = self._coefficient_output_unit(output.unit)
                if is_zero_waste_gas:
                    treatment_cost, total_cost = ZERO, ZERO
                else:
                    treatment_cost, total_cost = self._waste_treatment_cost(
                        output,
                        library,
                        amount,
                        amount_unit,
                        context,
                        warnings,
                        name,
                    )
                if treatment_cost is None and not is_zero_waste_gas:
                    warnings.append(f"节点 {context['nodes'][node_id].code} 的{name}未配置处理单价")
                result.append(
                    CalculatorAmountItem(
                        id=output.product_id,
                        code=getattr(library, "code", None),
                        name=name,
                        output_type=output.output_type,
                        amount=self._amount(amount),
                        unit=amount_unit,
                        unit_price=self._money(treatment_cost) if treatment_cost is not None else None,
                        cost=self._money(total_cost),
                        node_id=node_id,
                    )
                )
        return result

    def _calculate_route_waste_outputs(self, context: dict[str, Any], warnings: list[str]) -> list[CalculatorAmountItem]:
        result: list[CalculatorAmountItem] = []
        for route in context.get("active_routes", ()):
            route_amount = context["material_amount_t"][route.input_material_id]
            for output in context["calculation_outputs"].get(route.id, []):
                if output.output_type not in WASTE_OUTPUT_TYPES:
                    continue
                coefficient = self._parameter_value(context, f"waste_route_output:{output.id}:ratio", output.output_ratio)
                is_zero_waste_gas = coefficient <= 0 and output.output_type == "waste_gas"
                if coefficient <= 0:
                    if is_zero_waste_gas:
                        coefficient = ZERO
                    else:
                        warnings.append(f"{output.output_name} 的三废产出系数未配置")
                        coefficient = ZERO
                amount = route_amount * coefficient
                amount_unit = self._coefficient_output_unit(output.unit)
                library = context["products"].get(output.product_id) if output.product_id else None
                if is_zero_waste_gas:
                    treatment_cost, total_cost = ZERO, ZERO
                else:
                    treatment_cost, total_cost = self._route_waste_treatment_cost(
                        output,
                        library,
                        amount,
                        amount_unit,
                        context,
                        warnings,
                        output.output_name,
                    )
                if treatment_cost is None and not is_zero_waste_gas:
                    warnings.append(f"{output.output_name} 未配置处理单价")
                result.append(
                    CalculatorAmountItem(
                        id=output.product_id,
                        code=getattr(library, "code", None),
                        name=output.output_name,
                        output_type=output.output_type,
                        amount=self._amount(amount),
                        unit=amount_unit,
                        unit_price=self._money(treatment_cost) if treatment_cost is not None else None,
                        cost=self._money(total_cost),
                        route_id=route.id,
                    )
                )
        return result

    def _route_waste_treatment_cost(
        self,
        output: ProcessCalculationOutput,
        library: Any | None,
        amount: Decimal,
        amount_unit: str,
        context: dict[str, Any],
        warnings: list[str],
        name: str,
    ) -> tuple[Decimal | None, Decimal]:
        regional_price = context["prices"].get(("product", output.product_id))
        if regional_price is not None and regional_price.unit_price > 0:
            return self._priced_amount("product", output.product_id, amount, amount_unit, context, warnings, name)
        treatment_cost = self._parameter_value(context, f"waste_route_output:{output.id}:treatment_price", output.treatment_cost)
        if treatment_cost <= 0 and library is not None:
            treatment_cost = library.treatment_cost
        if treatment_cost <= 0:
            return None, ZERO
        return self._money(treatment_cost), amount * treatment_cost

    def _calculate_labor_costs(
        self,
        node_ids: list[int],
        context: dict[str, Any],
        warnings: list[str],
    ) -> list[CalculatorAmountItem]:
        result: list[CalculatorAmountItem] = []
        currency = context["payload"].currency
        for node_id in node_ids:
            for relation in context["node_labor"].get(node_id, []):
                if not relation.include_in_opex:
                    continue
                labor = context["labor_costs"].get(relation.labor_cost_id)
                name = labor.name if labor else str(relation.labor_cost_id)
                if labor is None:
                    warnings.append(f"节点 {context['nodes'][node_id].code} 的人员成本 {relation.labor_cost_id} 未找到或未启用")
                    continue
                regional_price = context["prices"].get(("labor", labor.id))
                if regional_price is None or regional_price.unit_price <= 0:
                    warnings.append(f"人员成本 {labor.name} 未配置 {context['payload'].region_code} 区域有效单人薪酬")
                    continue
                if regional_price.currency != currency:
                    warnings.append(f"人员成本 {labor.name} 币种为 {regional_price.currency}，无法换算为 {currency}")
                    continue
                annual_salary = regional_price.unit_price * (Decimal("12") if labor.salary_period == "month" else ONE)
                default_unit_cost = annual_salary * labor.welfare_factor
                headcount = self._parameter_value(context, f"labor:{relation.id}:headcount", relation.headcount)
                load_factor = self._parameter_value(context, f"labor:{relation.id}:load_factor", relation.load_factor)
                unit_cost = self._parameter_value(context, f"labor:{relation.id}:unit_cost", default_unit_cost)
                cost = headcount * load_factor * unit_cost
                result.append(
                    CalculatorAmountItem(
                        id=relation.labor_cost_id,
                        code=labor.code,
                        name=name,
                        output_type="labor",
                        amount=self._amount(headcount * load_factor),
                        unit="person-year",
                        unit_price=self._money(unit_cost),
                        cost=self._money(cost),
                        node_id=node_id,
                    )
                )
        return result

    def _waste_treatment_cost(
        self,
        output: ProcessNodeOutput,
        library: Any | None,
        amount: Decimal,
        amount_unit: str,
        context: dict[str, Any],
        warnings: list[str],
        name: str,
    ) -> tuple[Decimal | None, Decimal]:
        """三废优先采用所选地区处理单价，兼容节点和产出物库原有处理费。"""

        regional_price = context["prices"].get(("product", output.product_id))
        if regional_price is not None and regional_price.unit_price > 0:
            return self._priced_amount(
                "product",
                output.product_id,
                amount,
                amount_unit,
                context,
                warnings,
                name,
            )
        treatment_cost = self._parameter_value(
            context,
            f"waste_output:{output.id}:treatment_price",
            output.treatment_cost,
        )
        if treatment_cost <= 0 and library is not None:
            treatment_cost = library.treatment_cost
        if treatment_cost <= 0:
            return None, ZERO
        return self._money(treatment_cost), amount * treatment_cost

    def _calculate_material_cost(
        self,
        routes: tuple[ProcessRoute, ...],
        context: dict[str, Any],
        warnings: list[str],
    ) -> Decimal:
        total = ZERO
        used_material_ids = {route.input_material_id for route in routes}
        for material_id in used_material_ids:
            material = context["materials"][material_id]
            amount_t = context["material_amount_t"][material_id]
            _, cost = self._priced_amount("material", material_id, amount_t, "t", context, warnings, material.name)
            total += cost
        return total

    def _calculate_capex(
        self,
        node_ids: list[int],
        context: dict[str, Any],
        warnings: list[str],
    ) -> Decimal:
        currency = context["payload"].currency
        total = ZERO
        for node_id in node_ids:
            for equipment in context["node_equipment"].get(node_id, []):
                asset = context["assets"].get(equipment.asset_id) if getattr(equipment, "asset_id", None) else None
                equipment_name = asset.name if asset else equipment.equipment_name
                if asset is None:
                    warnings.append(f"设备/设施 {equipment_name} 未绑定资产库，未计入 CAPEX")
                    continue
                regional_price = context["prices"].get(("asset", asset.id))
                if regional_price is None or regional_price.unit_price <= 0:
                    warnings.append(f"设备/设施 {equipment_name} 未配置 {context['payload'].region_code} 区域有效投资额")
                    continue
                if regional_price.currency != currency:
                    warnings.append(f"设备/设施 {equipment_name} 币种为 {regional_price.currency}，无法换算为 {currency}")
                    continue
                unit_investment = self._parameter_value(
                    context,
                    f"equipment:{equipment.id}:investment",
                    regional_price.unit_price,
                )
                quantity = self._parameter_value(context, f"equipment:{equipment.id}:quantity", equipment.quantity)
                installation_factor = self._parameter_value(
                    context,
                    f"equipment:{equipment.id}:installation_factor",
                    equipment.installation_factor,
                )
                total += quantity * installation_factor * unit_investment
        params: CalculatorAdvancedParams = context["payload"].advanced_params
        if params.base_capacity is not None and params.scale_param_n is not None:
            actual_capacity = sum(context["material_amount_t"].values(), ZERO)
            try:
                total *= (actual_capacity / params.base_capacity) ** params.scale_param_n
            except (InvalidOperation, ZeroDivisionError) as exc:
                raise AppException("CAPEX规模修正参数无效") from exc
        return total

    def _calculate_cash_flows(
        self,
        revenue: Decimal,
        opex: Decimal,
        capex: Decimal,
        payload: ProcessCalculatorRequest,
    ) -> tuple[list[CalculatorCashFlow], Decimal, Decimal | None, Decimal | None, Decimal | None]:
        rows = [
            CalculatorCashFlow(
                year=0,
                revenue=ZERO,
                opex=ZERO,
                tax=ZERO,
                net_cash_flow=self._money(-capex),
                discounted_cash_flow=self._money(-capex),
            )
        ]
        raw_cash_flows = [-capex]
        growth_factor = ONE
        for year in range(1, payload.period_years + 1):
            if year > 1:
                growth_factor *= ONE + payload.advanced_params.annual_growth_rate
            annual_revenue = revenue * growth_factor
            annual_opex = opex * growth_factor
            annual_ebitda = annual_revenue - annual_opex
            tax = max(annual_ebitda, ZERO) * payload.tax_rate
            net_cash_flow = annual_ebitda - tax
            discounted = net_cash_flow / ((ONE + payload.discount_rate) ** year)
            raw_cash_flows.append(net_cash_flow)
            rows.append(
                CalculatorCashFlow(
                    year=year,
                    revenue=self._money(annual_revenue),
                    opex=self._money(annual_opex),
                    tax=self._money(tax),
                    net_cash_flow=self._money(net_cash_flow),
                    discounted_cash_flow=self._money(discounted),
                )
            )
        npv = sum((row.discounted_cash_flow for row in rows), ZERO)
        irr = self._irr(raw_cash_flows)
        payback = self._payback(raw_cash_flows)
        discounted_payback = self._payback([row.discounted_cash_flow for row in rows])
        return rows, npv, irr, payback, discounted_payback

    def _calculate_material_balance(
        self,
        routes: tuple[ProcessRoute, ...],
        product_outputs: list[CalculatorAmountItem],
        waste_outputs: list[CalculatorAmountItem],
        context: dict[str, Any],
        warnings: list[str],
    ) -> CalculatorMaterialBalance:
        input_mass_t = sum(
            (context["material_amount_t"][material_id] for material_id in {route.input_material_id for route in routes}),
            ZERO,
        )
        output_mass_t = ZERO
        excluded: list[str] = []
        for item in [*product_outputs, *waste_outputs]:
            converted = self._try_mass_convert(item.amount, item.unit, "t")
            if converted is None:
                if item.output_type == "waste_gas" and item.amount <= ZERO:
                    continue
                excluded.append(f"{item.name}({item.unit})")
                continue
            output_mass_t += converted
        if excluded:
            warnings.append("物料平衡已排除无法换算为质量的产出物：" + "、".join(excluded))
        difference = input_mass_t - output_mass_t
        balance_rate = output_mass_t / input_mass_t if input_mass_t > 0 else None
        return CalculatorMaterialBalance(
            input_mass_t=self._amount(input_mass_t),
            accounted_output_mass_t=self._amount(output_mass_t),
            difference_mass_t=self._amount(difference),
            balance_rate=self._ratio(balance_rate),
            excluded_non_mass_outputs=excluded,
        )

    def _priced_amount(
        self,
        owner_type: str,
        owner_id: int | None,
        amount: Decimal,
        amount_unit: str,
        context: dict[str, Any],
        warnings: list[str],
        name: str,
    ) -> tuple[Decimal | None, Decimal]:
        if owner_id is None:
            warnings.append(f"{name} 未关联基础库，无法获取区域单价")
            return None, ZERO
        price = context["prices"].get((owner_type, owner_id))
        if price is None or price.unit_price <= 0:
            warnings.append(f"{name} 未配置 {context['payload'].region_code} 区域有效单价")
            return None, ZERO
        if price.currency != context["payload"].currency:
            warnings.append(f"{name} 单价币种为 {price.currency}，无法换算为 {context['payload'].currency}")
            return self._money(price.unit_price), ZERO
        priced_amount = self._convert_amount(amount, amount_unit, price.unit)
        if priced_amount is None:
            warnings.append(f"{name} 数量单位 {amount_unit} 无法换算为计价单位 {price.unit}")
            return self._money(price.unit_price), ZERO
        unit_price = self._parameter_value(context, f"price:{owner_type}:{owner_id}", price.unit_price)
        return self._money(unit_price), priced_amount * unit_price

    @staticmethod
    def _parameter_value(context: dict[str, Any], key: str, default: Decimal) -> Decimal:
        return context["parameter_overrides"].get(key, default)

    def _build_calculation_parameters(
        self,
        routes: tuple[ProcessRoute, ...],
        node_ids: list[int],
        context: dict[str, Any],
    ) -> list[CalculatorParameter]:
        """汇总推荐方案的计算输入，供页面解释和本次测算调参。"""

        result: dict[str, CalculatorParameter] = {}

        def add(key: str, category: str, name: str, value: Decimal, unit: str) -> None:
            result[key] = CalculatorParameter(
                key=key,
                category=category,
                name=name,
                value=self._parameter_value(context, key, value),
                unit=unit,
            )

        for route in routes:
            material = context["materials"][route.input_material_id]
            price = context["prices"].get(("material", route.input_material_id))
            if price:
                add(f"price:material:{material.id}", "区域单价", f"{material.name}原料单价", price.unit_price, f"{price.currency}/{price.unit}")
            for output in context["calculation_outputs"].get(route.id, []):
                if output.output_type not in ("product", "byproduct"):
                    continue
                add(f"product_output:{output.id}:ratio", "产出系数", output.output_name, output.output_ratio, output.unit)
                price = context["prices"].get(("product", output.product_id))
                if price:
                    add(f"price:product:{output.product_id}", "区域单价", f"{output.output_name}单价", price.unit_price, f"{price.currency}/{price.unit}")
        relation_specs = (
            ("node_consumables", "consumable", "药剂吨耗", "consumable_id", context["consumables"]),
            ("node_public_services", "public_service", "公辅吨耗", "public_service_id", context["public_services"]),
        )
        for node_id in node_ids:
            for relation_key, owner_type, category, id_field, libraries in relation_specs:
                for relation in context[relation_key].get(node_id, []):
                    owner_id = getattr(relation, id_field)
                    library = libraries.get(owner_id)
                    coefficient = relation.amount_per_ton_bm or relation.amount_per_ton
                    add(f"{owner_type}:{relation.id}:coefficient", category, library.name if library else str(owner_id), coefficient, relation.unit)
                    price = context["prices"].get((owner_type, owner_id))
                    if price:
                        add(f"price:{owner_type}:{owner_id}", "区域单价", f"{library.name if library else owner_id}单价", price.unit_price, f"{price.currency}/{price.unit}")
            for output in context["node_outputs"].get(node_id, []):
                library = context["products"].get(output.product_id)
                name = library.name if library else str(output.product_id)
                if output.output_type in PRODUCT_OUTPUT_TYPES:
                    add(f"node_product_output:{output.id}:coefficient", "节点产品产出", name, output.output_per_ton, output.unit)
                    price = context["prices"].get(("product", output.product_id))
                    if price:
                        add(f"price:product:{output.product_id}", "区域单价", f"{name}单价", price.unit_price, f"{price.currency}/{price.unit}")
                    continue
                if output.output_type in WASTE_OUTPUT_TYPES:
                    add(f"waste_output:{output.id}:coefficient", "三废产出", name, output.output_per_ton, output.unit)
                    price = context["prices"].get(("product", output.product_id))
                    if price:
                        add(f"price:product:{output.product_id}", "处理单价", f"{name}处理费", price.unit_price, f"{price.currency}/{price.unit}")
                    else:
                        add(f"waste_output:{output.id}:treatment_price", "处理单价", f"{name}处理费", output.treatment_cost, context["payload"].currency)
            for equipment in context["node_equipment"].get(node_id, []):
                asset = context["assets"].get(equipment.asset_id) if getattr(equipment, "asset_id", None) else None
                equipment_name = asset.name if asset else equipment.equipment_name
                regional_price = context["prices"].get(("asset", asset.id)) if asset else None
                if regional_price:
                    add(
                        f"equipment:{equipment.id}:investment",
                        "设备/设施投资",
                        equipment_name,
                        regional_price.unit_price,
                        regional_price.currency,
                    )
                add(f"equipment:{equipment.id}:quantity", "设备/设施数量", equipment_name, equipment.quantity, "set")
                add(f"equipment:{equipment.id}:installation_factor", "安装/配套系数", equipment_name, equipment.installation_factor, "")
            for labor in context["node_labor"].get(node_id, []):
                labor_cost = context["labor_costs"].get(labor.labor_cost_id)
                if not labor_cost:
                    continue
                regional_price = context["prices"].get(("labor", labor_cost.id))
                if not regional_price:
                    continue
                annual_salary = regional_price.unit_price * Decimal("12") if labor_cost.salary_period == "month" else regional_price.unit_price
                unit_labor_cost = annual_salary * labor_cost.welfare_factor
                add(f"labor:{labor.id}:headcount", "人员数量", labor_cost.name, labor.headcount, "person")
                add(f"labor:{labor.id}:load_factor", "人员负荷系数", labor_cost.name, labor.load_factor, "")
                add(f"labor:{labor.id}:unit_cost", "年化单人成本", labor_cost.name, unit_labor_cost, regional_price.currency)
        return list(result.values())

    def _route_refs(self, routes: tuple[ProcessRoute, ...], context: dict[str, Any]) -> list[CalculatorRouteRef]:
        result: list[CalculatorRouteRef] = []
        for route in routes:
            material = context["materials"][route.input_material_id]
            product_library = context["products"][route.final_product_id]
            nodes = [
                CalculatorRouteNodeRef(
                    id=context["nodes"][item.node_id].id,
                    code=context["nodes"][item.node_id].code,
                    name=context["nodes"][item.node_id].name,
                    version=context["nodes"][item.node_id].version,
                    sort_order=item.sort_order,
                    option_group_code=item.option_group_code,
                    option_code=item.option_code,
                    node_params_json=item.node_params_json,
                    outputs=self._route_node_output_refs(item.node_id, context),
                )
                for item in context["route_nodes"].get(route.id, [])
                if item.node_id in context["nodes"]
            ]
            result.append(
                CalculatorRouteRef(
                    id=route.id,
                    code=route.code,
                    name=route.name,
                    input_material_id=material.id,
                    input_material_code=material.code,
                    input_material_name=material.name,
                    final_product_id=product_library.id,
                    final_product_code=product_library.code,
                    final_product_name=product_library.name,
                    node_codes=[node.code for node in nodes],
                    nodes=nodes,
                )
            )
        return result

    def _route_node_output_refs(self, node_id: int, context: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for output in context["node_outputs"].get(node_id, []):
            if output.output_type not in TERMINAL_OUTPUT_TYPES:
                continue
            product_library = context["products"].get(output.product_id)
            result.append(
                {
                    "id": output.id,
                    "product_id": output.product_id,
                    "product_code": getattr(product_library, "code", None),
                    "product_name": getattr(product_library, "name", None),
                    "output_name": getattr(product_library, "name", None) or f"节点产出物{output.product_id}",
                    "output_type": output.output_type,
                }
            )
        return result

    def _build_result(
        self,
        calculation_id: str,
        details: list[dict[str, Any]],
        recommended: dict[str, Any] | None,
        no_route_reason: str | None = None,
    ) -> ProcessCalculatorResultOut:
        summaries = [item["summary"] for item in details]
        if recommended is None:
            return ProcessCalculatorResultOut(
                calculation_id=calculation_id,
                matched_routes=summaries,
                recommended_route=None,
                no_route_reason=no_route_reason,
                product_outputs=[],
                consumable_costs=[],
                public_service_costs=[],
                labor_costs=[],
                waste_outputs=[],
                capex=ZERO,
                opex=ZERO,
                revenue=ZERO,
                ebitda=ZERO,
                npv=ZERO,
                irr=None,
                payback_period=None,
                material_balance=None,
                cash_flows=[],
                calculation_parameters=[],
                warnings=[],
            )
        metrics = recommended["summary"].metrics
        return ProcessCalculatorResultOut(
            calculation_id=calculation_id,
            matched_routes=summaries,
            recommended_route=recommended["summary"],
            no_route_reason=no_route_reason,
            product_outputs=recommended["product_outputs"],
            consumable_costs=recommended["consumable_costs"],
            public_service_costs=recommended["public_service_costs"],
            labor_costs=recommended["labor_costs"],
            waste_outputs=recommended["waste_outputs"],
            capex=metrics.capex,
            opex=metrics.opex,
            revenue=metrics.revenue,
            ebitda=metrics.ebitda,
            npv=metrics.npv,
            irr=metrics.irr,
            payback_period=metrics.payback_period,
            material_balance=recommended["material_balance"],
            cash_flows=recommended["cash_flows"],
            calculation_parameters=recommended["calculation_parameters"],
            warnings=recommended["summary"].warnings,
        )

    @staticmethod
    def _library_option(item: Any) -> dict[str, Any]:
        return {"id": item.id, "code": item.code, "name": item.name, "unit": item.unit}

    @staticmethod
    def _scheme_sort_key(summary: CalculatorSchemeSummary, criteria: str) -> tuple[Any, ...]:
        completeness = 0 if summary.is_complete else 1
        warning_count = len(summary.warnings)
        value = getattr(summary.metrics, criteria)
        if criteria in ("npv", "irr", "ebitda"):
            return completeness, warning_count, value is None, -(value or ZERO), summary.scheme_code
        return completeness, warning_count, value is None, value or Decimal("999999999999999999"), summary.scheme_code

    @staticmethod
    def _to_tons(amount: Decimal, unit: str) -> Decimal:
        converted = ProcessCalculatorService._try_mass_convert(amount, unit, "t")
        if converted is None:
            raise AppException(f"原料处理量单位 {unit} 暂不支持，MVP仅支持 t、kg、g")
        return converted

    @staticmethod
    def _convert_amount(amount: Decimal, source_unit: str, target_unit: str) -> Decimal | None:
        source = ProcessCalculatorService._normalize_unit(source_unit)
        target = ProcessCalculatorService._normalize_unit(target_unit)
        if source == target:
            return amount
        mass = ProcessCalculatorService._try_mass_convert(amount, source, target)
        if mass is not None:
            return mass
        aliases = {"m³": "m3", "方": "m3", "立方米": "m3", "kwh": "kwh", "度": "kwh"}
        return amount if aliases.get(source, source) == aliases.get(target, target) else None

    @staticmethod
    def _try_mass_convert(amount: Decimal, source_unit: str, target_unit: str) -> Decimal | None:
        factors = {"t": Decimal("1000"), "吨": Decimal("1000"), "kg": ONE, "千克": ONE, "g": Decimal("0.001"), "克": Decimal("0.001")}
        source = ProcessCalculatorService._normalize_unit(source_unit)
        target = ProcessCalculatorService._normalize_unit(target_unit)
        if source not in factors or target not in factors:
            return None
        return amount * factors[source] / factors[target]

    @staticmethod
    def _normalize_unit(unit: str) -> str:
        normalized = unit.strip().lower().replace(" ", "")
        return {"ton": "t", "tons": "t", "t-bm": "t", "t/bm": "t", "吨bm": "t"}.get(normalized, normalized)

    @staticmethod
    def _coefficient_output_unit(unit: str) -> str:
        """将 kg/t-BM、KWH/t-BM 等系数单位转换为实际数量单位。"""

        normalized = unit.strip()
        compact = normalized.lower().replace(" ", "")
        for suffix in ("/t-bm", "/tbm", "/t_bm", "/吨bm", "/吨黑粉"):
            if compact.endswith(suffix):
                return normalized[: len(normalized) - len(suffix)].strip()
        return normalized

    @staticmethod
    def _irr(cash_flows: list[Decimal]) -> Decimal | None:
        if not cash_flows or min(cash_flows) >= 0 or max(cash_flows) <= 0:
            return None

        def npv(rate: Decimal) -> Decimal:
            return sum((cash_flow / ((ONE + rate) ** year) for year, cash_flow in enumerate(cash_flows)), ZERO)

        low = Decimal("-0.9999")
        high = Decimal("10")
        low_value = npv(low)
        high_value = npv(high)
        while low_value * high_value > 0 and high < Decimal("1000000"):
            high *= Decimal("10")
            high_value = npv(high)
        if low_value * high_value > 0:
            return None
        for _ in range(200):
            middle = (low + high) / Decimal("2")
            middle_value = npv(middle)
            if abs(middle_value) <= Decimal("0.000001"):
                return middle
            if low_value * middle_value <= 0:
                high = middle
            else:
                low = middle
                low_value = middle_value
        return (low + high) / Decimal("2")

    @staticmethod
    def _payback(cash_flows: list[Decimal]) -> Decimal | None:
        cumulative = ZERO
        for year, cash_flow in enumerate(cash_flows):
            previous = cumulative
            cumulative += cash_flow
            if cumulative >= 0:
                if year == 0:
                    return ZERO
                if cash_flow <= 0:
                    return Decimal(year)
                return Decimal(year - 1) + abs(previous) / cash_flow
        return None

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        return value.quantize(MONEY_QUANT)

    @staticmethod
    def _amount(value: Decimal) -> Decimal:
        return value.quantize(AMOUNT_QUANT)

    @staticmethod
    def _ratio(value: Decimal | None) -> Decimal | None:
        return value.quantize(AMOUNT_QUANT) if value is not None else None


class _NodeOutputAdapter:
    """将节点产品产出转换为路线产出计算所需的只读字段。"""

    def __init__(self, output: ProcessNodeOutput, product_library: Any | None) -> None:
        self.id = output.id
        self.product_id = output.product_id
        self.output_name = product_library.name if product_library else f"节点产出物{output.product_id}"
        self.output_type = output.output_type
        self.output_ratio = output.output_per_ton
        self.recovery_rate = ONE
        self.formula_type = output.formula_type
        self.unit = output.unit
