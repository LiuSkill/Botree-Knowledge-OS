"""快速财务计算器服务测试。"""

from __future__ import annotations

from decimal import Decimal
import sys
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models import Base  # noqa: E402
from app.models.process_config import (  # noqa: E402
    ProcessCalculationOutput,
    ProcessConsumable,
    ProcessMaterial,
    ProcessNode,
    ProcessNodeConsumable,
    ProcessNodeEquipment,
    ProcessNodeOutput,
    ProcessNodePublicService,
    ProcessProduct,
    ProcessPublicService,
    ProcessRegionPrice,
    ProcessRoute,
    ProcessRouteNode,
)
from app.schemas.process_calculator import ProcessCalculatorRequest  # noqa: E402
from app.services.process_calculator_service import ProcessCalculatorService  # noqa: E402


def test_multi_product_calculation_deduplicates_shared_nodes() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_calculation_data(db)
        query_count = 0

        def count_query(*_: object) -> None:
            nonlocal query_count
            query_count += 1

        event.listen(engine, "before_cursor_execute", count_query)
        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_products=seeded["product_ids"],
                region_code="asia",
                currency="CNY",
                tax_rate="0.25",
                discount_rate="0.08",
                period_years=5,
                advanced_params={},
            )
        )
        event.remove(engine, "before_cursor_execute", count_query)

        assert query_count <= 16
        assert len(result["matched_routes"]) == 1
        assert len(result["recommended_route"]["routes"]) == 2
        assert result["recommended_route"]["node_codes"] == ["A1"]
        assert result["recommended_route"]["routes"][0]["input_material_code"] == "M1"
        assert result["recommended_route"]["routes"][0]["final_product_code"] == "P1"
        route_node = result["recommended_route"]["routes"][0]["nodes"][0]
        assert route_node["code"] == "A1"
        assert route_node["name"] == "浸出"
        assert route_node["version"] == "V1"
        assert route_node["sort_order"] == 1
        assert [item["amount"] for item in result["product_outputs"]] == ["2.000000", "3.000000"]
        assert result["consumable_costs"][0]["amount"] == "20.000000"
        assert result["public_service_costs"][0]["amount"] == "50.000000"
        assert result["waste_outputs"][0]["amount"] == "1.000000"
        assert result["revenue"] == "8000.00"
        assert result["opex"] == "1380.00"
        assert result["ebitda"] == "6620.00"
        assert result["capex"] == "100.00"
        assert Decimal(result["npv"]) > 0
        assert result["irr"] is not None
    engine.dispose()


def test_expression_record_uses_structured_coefficient_without_evaluating_expression() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_calculation_data(db, product_formula_type="expression")
        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_products=[seeded["product_ids"][0]],
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )

        assert result["product_outputs"][0]["amount"] == "2.000000"
        assert any("未执行原表达式" in warning for warning in result["warnings"])
    engine.dispose()


def test_route_output_ratio_does_not_apply_recovery_rate_again() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_calculation_data(db)
        output = db.scalar(
            select(ProcessCalculationOutput).where(ProcessCalculationOutput.product_id == seeded["product_ids"][0])
        )
        assert output is not None
        output.recovery_rate = Decimal("0.8")
        output.output_ratio = Decimal("0.2")
        db.commit()

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_products=[seeded["product_ids"][0]],
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )

        assert result["product_outputs"][0]["amount"] == "2.000000"
    engine.dispose()


def test_calculation_parameter_override_is_returned_and_applied() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_calculation_data(db)
        output = db.scalar(
            select(ProcessCalculationOutput).where(ProcessCalculationOutput.product_id == seeded["product_ids"][0])
        )
        assert output is not None
        override_key = f"product_output:{output.id}:ratio"

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_products=[seeded["product_ids"][0]],
                region_code="asia",
                currency="CNY",
                parameter_overrides={override_key: "0.4"},
            )
        )

        parameter = next(item for item in result["calculation_parameters"] if item["key"] == override_key)
        assert parameter["value"] == "0.4"
        assert result["product_outputs"][0]["amount"] == "4.000000"
        assert result["revenue"] == "4000.00"
    engine.dispose()


def test_calculation_returns_only_top_three_ranked_schemes() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_calculation_data(db)
        material = db.get(ProcessMaterial, seeded["material_id"])
        product_item = db.get(ProcessProduct, seeded["product_ids"][0])
        node = db.scalar(select(ProcessNode).where(ProcessNode.code == "A1"))
        assert material is not None and product_item is not None and node is not None

        extra_routes = [
            ProcessRoute(
                code=f"A1-P1-{index}",
                name=f"钴路线{index}",
                input_material_id=material.id,
                final_product_id=product_item.id,
                status="enabled",
                version="V1",
                sort_order=index,
            )
            for index in range(2, 6)
        ]
        db.add_all(extra_routes)
        db.flush()
        for route in extra_routes:
            db.add(ProcessRouteNode(route_id=route.id, node_id=node.id, sort_order=1))
            db.add(
                ProcessCalculationOutput(
                    route_id=route.id,
                    output_type="product",
                    product_id=product_item.id,
                    output_name=product_item.name,
                    formula_type="fixed",
                    recovery_rate=Decimal("1"),
                    unit="t/t-BM",
                    output_ratio=Decimal("0.2"),
                )
            )
        db.commit()

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": material.id, "amount": "10", "unit": "t"}],
                target_products=[product_item.id],
                region_code="asia",
                currency="CNY",
                sort_criteria="npv",
                advanced_params={},
            )
        )

        assert len(result["matched_routes"]) == 3
        assert result["recommended_route"]["scheme_code"] == result["matched_routes"][0]["scheme_code"]
    engine.dispose()


def _seed_calculation_data(db: Session, product_formula_type: str = "fixed") -> dict[str, object]:
    material = ProcessMaterial(code="M1", name="黑粉", type="battery_black_mass", unit="t", status="enabled")
    cobalt = ProcessProduct(code="P1", name="硫酸钴", type="product", unit="t", output_type="product", status="enabled")
    nickel = ProcessProduct(code="P2", name="硫酸镍", type="product", unit="t", output_type="product", status="enabled")
    waste = ProcessProduct(
        code="W1",
        name="除杂渣",
        type="solid_waste",
        unit="t",
        output_type="solid_waste",
        treatment_cost=Decimal("50"),
        status="enabled",
    )
    reagent = ProcessConsumable(code="C1", name="硫酸", type="chemical", unit="kg", status="enabled")
    electricity = ProcessPublicService(code="S1", name="电力", type="utility", unit="kWh", status="enabled")
    db.add_all([material, cobalt, nickel, waste, reagent, electricity])
    db.flush()

    node = ProcessNode(code="A1", name="浸出", node_type="hydrometallurgy", status="enabled", version="V1")
    db.add(node)
    db.flush()
    db.add_all(
        [
            ProcessNodeConsumable(
                node_id=node.id,
                consumable_id=reagent.id,
                amount_per_ton=Decimal("0"),
                amount_per_ton_bm=Decimal("2"),
                formula_type="fixed",
                unit="kg/t-BM",
            ),
            ProcessNodePublicService(
                node_id=node.id,
                public_service_id=electricity.id,
                amount_per_ton=Decimal("0"),
                amount_per_ton_bm=Decimal("5"),
                formula_type="fixed",
                unit="kWh/t-BM",
            ),
            ProcessNodeEquipment(
                node_id=node.id,
                equipment_name="浸出槽",
                quantity=Decimal("1"),
                investment_amount=Decimal("100"),
                currency="CNY",
            ),
            ProcessNodeOutput(
                node_id=node.id,
                product_id=waste.id,
                output_type="solid_waste",
                output_per_ton=Decimal("0.1"),
                formula_type="fixed",
                treatment_cost=Decimal("50"),
                unit="t/t-BM",
            ),
        ]
    )

    routes = [
        ProcessRoute(code="A1-P1", name="钴路线", input_material_id=material.id, final_product_id=cobalt.id, status="enabled", version="V1"),
        ProcessRoute(code="A1-P2", name="镍路线", input_material_id=material.id, final_product_id=nickel.id, status="enabled", version="V1"),
    ]
    db.add_all(routes)
    db.flush()
    db.add_all([ProcessRouteNode(route_id=route.id, node_id=node.id, sort_order=1) for route in routes])
    db.add_all(
        [
            ProcessCalculationOutput(
                route_id=routes[0].id,
                output_type="product",
                product_id=cobalt.id,
                output_name=cobalt.name,
                formula_type=product_formula_type,
                expression="BM*0.2" if product_formula_type == "expression" else None,
                recovery_rate=Decimal("1"),
                unit="t/t-BM",
                output_ratio=Decimal("0.2"),
            ),
            ProcessCalculationOutput(
                route_id=routes[1].id,
                output_type="product",
                product_id=nickel.id,
                output_name=nickel.name,
                formula_type="fixed",
                recovery_rate=Decimal("1"),
                unit="t/t-BM",
                output_ratio=Decimal("0.3"),
            ),
        ]
    )
    prices = [
        ("material", material.id, Decimal("100"), "t"),
        ("product", cobalt.id, Decimal("1000"), "t"),
        ("product", nickel.id, Decimal("2000"), "t"),
        ("product", waste.id, Decimal("80"), "t"),
        ("consumable", reagent.id, Decimal("10"), "kg"),
        ("public_service", electricity.id, Decimal("2"), "kWh"),
    ]
    db.add_all(
        [
            ProcessRegionPrice(
                owner_type=owner_type,
                owner_id=owner_id,
                region_code="asia",
                region_name="亚洲",
                currency="CNY",
                unit_price=unit_price,
                unit=unit,
                status="enabled",
            )
            for owner_type, owner_id, unit_price, unit in prices
        ]
    )
    db.commit()
    return {"material_id": material.id, "product_ids": [cobalt.id, nickel.id]}
