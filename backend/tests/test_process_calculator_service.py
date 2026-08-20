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
    ProcessAsset,
    ProcessConsumable,
    ProcessLaborCost,
    ProcessMaterial,
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

        assert query_count <= 17
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


def test_calculator_options_expose_first_version_target_output_categories() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        _seed_calculation_data(db)

        options = ProcessCalculatorService(db).get_options()

        assert [item["code"] for item in options["target_output_categories"]] == ["li", "ni", "co", "mn", "cu", "graphite"]
        assert options["target_products"]
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


def test_representative_product_route_includes_byproduct_node_outputs() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        material = ProcessMaterial(code="BM-REP", name="Black Mass", type="battery_black_mass", unit="t", status="enabled")
        lithium = ProcessProduct(code="LI-REP", name="Lithium Carbonate", type="li", unit="t", output_type="product", status="enabled")
        cobalt = ProcessProduct(code="CO-BY", name="Cobalt Salt", type="co", unit="t", output_type="byproduct", status="enabled")
        db.add_all([material, lithium, cobalt])
        db.flush()

        node = ProcessNode(code="N-COMPLETE", name="Complete Route Node", node_type="hydrometallurgy", status="enabled", version="V1")
        db.add(node)
        db.flush()
        db.add_all(
            [
                ProcessNodeOutput(
                    node_id=node.id,
                    product_id=lithium.id,
                    output_type="product",
                    output_per_ton=Decimal("0.2"),
                    formula_type="fixed",
                    unit="t/t-BM",
                    is_main_product=True,
                ),
                ProcessNodeOutput(
                    node_id=node.id,
                    product_id=cobalt.id,
                    output_type="byproduct",
                    output_per_ton=Decimal("0.05"),
                    formula_type="fixed",
                    unit="t/t-BM",
                    is_main_product=False,
                ),
            ]
        )
        route = ProcessRoute(
            code="R-REP",
            name="Representative Product Route",
            input_material_id=material.id,
            final_product_id=lithium.id,
            status="enabled",
            version="V1",
        )
        db.add(route)
        db.flush()
        db.add(ProcessRouteNode(route_id=route.id, node_id=node.id, sort_order=1))
        db.add_all(
            [
                ProcessRegionPrice(
                    owner_type="material",
                    owner_id=material.id,
                    region_code="asia",
                    region_name="Asia",
                    currency="CNY",
                    unit_price=Decimal("100"),
                    unit="t",
                    status="enabled",
                ),
                ProcessRegionPrice(
                    owner_type="product",
                    owner_id=lithium.id,
                    region_code="asia",
                    region_name="Asia",
                    currency="CNY",
                    unit_price=Decimal("1000"),
                    unit="t",
                    status="enabled",
                ),
                ProcessRegionPrice(
                    owner_type="product",
                    owner_id=cobalt.id,
                    region_code="asia",
                    region_name="Asia",
                    currency="CNY",
                    unit_price=Decimal("500"),
                    unit="t",
                    status="enabled",
                ),
            ]
        )
        db.commit()

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": material.id, "amount": "10", "unit": "t"}],
                target_products=[lithium.id],
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )

        outputs_by_code = {item["code"]: item for item in result["product_outputs"]}
        assert set(outputs_by_code) == {"LI-REP", "CO-BY"}
        assert outputs_by_code["LI-REP"]["amount"] == "2.000000"
        assert outputs_by_code["CO-BY"]["amount"] == "0.500000"
    engine.dispose()


def test_waste_gas_node_output_is_counted_as_waste_treatment_cost() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        material = ProcessMaterial(code="BM-GAS", name="Black Mass", type="battery_black_mass", unit="t", status="enabled")
        product = ProcessProduct(code="LI-GAS", name="Lithium Carbonate", type="li", unit="t", output_type="product", status="enabled")
        offgas = ProcessProduct(
            code="OFFGAS",
            name="Mixed Acid Roasting Offgas",
            type="waste_gas",
            unit="Nm3",
            output_type="waste_gas",
            treatment_cost=Decimal("2"),
            status="enabled",
        )
        db.add_all([material, product, offgas])
        db.flush()

        node = ProcessNode(code="N-OFFGAS", name="Mixed Acid Roasting Offgas Treatment", node_type="post_treatment", status="enabled", version="V1")
        db.add(node)
        db.flush()
        db.add_all(
            [
                ProcessNodeOutput(
                    node_id=node.id,
                    product_id=product.id,
                    output_type="product",
                    output_per_ton=Decimal("0.2"),
                    formula_type="fixed",
                    unit="t/t-BM",
                    is_main_product=True,
                ),
                ProcessNodeOutput(
                    node_id=node.id,
                    product_id=offgas.id,
                    output_type="waste_gas",
                    output_per_ton=Decimal("3"),
                    formula_type="fixed",
                    treatment_cost=Decimal("2"),
                    unit="Nm3/t-BM",
                ),
            ]
        )
        route = ProcessRoute(
            code="R-GAS",
            name="Waste Gas Route",
            input_material_id=material.id,
            final_product_id=product.id,
            status="enabled",
            version="V1",
        )
        db.add(route)
        db.flush()
        db.add(ProcessRouteNode(route_id=route.id, node_id=node.id, sort_order=1))
        db.add_all(
            [
                ProcessRegionPrice(
                    owner_type="material",
                    owner_id=material.id,
                    region_code="asia",
                    region_name="Asia",
                    currency="CNY",
                    unit_price=Decimal("100"),
                    unit="t",
                    status="enabled",
                ),
                ProcessRegionPrice(
                    owner_type="product",
                    owner_id=product.id,
                    region_code="asia",
                    region_name="Asia",
                    currency="CNY",
                    unit_price=Decimal("1000"),
                    unit="t",
                    status="enabled",
                ),
                ProcessRegionPrice(
                    owner_type="product",
                    owner_id=offgas.id,
                    region_code="asia",
                    region_name="Asia",
                    currency="CNY",
                    unit_price=Decimal("2"),
                    unit="Nm3",
                    status="enabled",
                ),
            ]
        )
        db.commit()

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": material.id, "amount": "10", "unit": "t"}],
                target_products=[product.id],
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )

        assert result["waste_outputs"][0]["code"] == "OFFGAS"
        assert result["waste_outputs"][0]["output_type"] == "waste_gas"
        assert result["waste_outputs"][0]["amount"] == "30.000000"
        assert result["opex"] == "1060.00"
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


def test_labor_cost_binding_is_counted_once_in_opex() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_calculation_data(db)
        node = db.scalar(select(ProcessNode).where(ProcessNode.code == "A1"))
        assert node is not None
        labor_cost = ProcessLaborCost(
            code="L1",
            name="生产操作工",
            type="production",
            unit="person-year",
            salary_period="year",
            welfare_factor=Decimal("1.2"),
            status="enabled",
        )
        db.add(labor_cost)
        db.flush()
        db.add(
            ProcessNodeLabor(
                node_id=node.id,
                labor_cost_id=labor_cost.id,
                headcount=Decimal("2"),
                load_factor=Decimal("1"),
                include_in_opex=True,
            )
        )
        db.add(
            ProcessRegionPrice(
                owner_type="labor",
                owner_id=labor_cost.id,
                region_code="asia",
                region_name="亚洲",
                currency="CNY",
                unit_price=Decimal("100000"),
                unit="person-year",
                status="enabled",
            )
        )
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

        assert result["labor_costs"][0]["amount"] == "2.000000"
        assert result["labor_costs"][0]["unit_price"] == "120000.00"
        assert result["labor_costs"][0]["cost"] == "240000.00"
        assert result["recommended_route"]["metrics"]["labor_cost"] == "240000.00"
        assert result["opex"] == "241380.00"
    engine.dispose()


def test_asset_and_labor_parameter_overrides_are_applied() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_calculation_data(db)
        equipment = db.scalar(select(ProcessNodeEquipment))
        node = db.scalar(select(ProcessNode).where(ProcessNode.code == "A1"))
        assert equipment is not None and node is not None
        labor_cost = ProcessLaborCost(
            code="L-OVERRIDE",
            name="操作工",
            type="production",
            unit="person-year",
            salary_period="year",
            welfare_factor=Decimal("1"),
            status="enabled",
        )
        db.add(labor_cost)
        db.flush()
        relation = ProcessNodeLabor(
            node_id=node.id,
            labor_cost_id=labor_cost.id,
            headcount=Decimal("1"),
            load_factor=Decimal("1"),
            include_in_opex=True,
        )
        db.add(relation)
        db.add(
            ProcessRegionPrice(
                owner_type="labor",
                owner_id=labor_cost.id,
                region_code="asia",
                region_name="亚洲",
                currency="CNY",
                unit_price=Decimal("100"),
                unit="person-year",
                status="enabled",
            )
        )
        db.commit()

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_products=[seeded["product_ids"][0]],
                region_code="asia",
                currency="CNY",
                parameter_overrides={
                    f"equipment:{equipment.id}:quantity": "2",
                    f"equipment:{equipment.id}:installation_factor": "1.5",
                    f"labor:{relation.id}:headcount": "3",
                    f"labor:{relation.id}:load_factor": "0.5",
                    f"labor:{relation.id}:unit_cost": "200",
                },
            )
        )

        assert result["capex"] == "300.00"
        assert result["labor_costs"][0]["amount"] == "1.500000"
        assert result["labor_costs"][0]["cost"] == "300.00"
        assert result["opex"] == "1680.00"
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


def test_category_recommendation_returns_complete_multi_output_candidate() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_complete_candidate_data(db)

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["li", "cu"],
                selected_options={"root_leach_path": "acid_leaching"},
                region_code="asia",
                currency="CNY",
                sort_criteria="npv",
                advanced_params={},
            )
        )

        assert result["no_route_reason"] is None
        assert len(result["matched_routes"]) == 1
        scheme = result["matched_routes"][0]
        assert scheme["selected_options"]["root_leach_path"] == "acid_leaching"
        assert set(scheme["node_codes"]) == {"A2", "C-LI", "C-CU", "C-CO", "W-FINAL"}
        assert "A1" not in scheme["node_codes"]
        assert "B1" not in scheme["node_codes"]
        assert {route["code"] for route in scheme["routes"]} == {
            "R-ACID-LI",
            "R-ACID-CU",
            "R-ACID-CO",
            "R-ACID-WASTE",
        }
        summary_by_code = {item["code"]: item for item in scheme["output_summary"]}
        assert set(summary_by_code) == {"LI", "CU", "CO", "WW", "SW"}
        assert summary_by_code["LI"]["output_type"] == "product"
        assert summary_by_code["CU"]["output_type"] == "product"
        assert summary_by_code["CO"]["output_type"] == "byproduct"
        assert summary_by_code["WW"]["output_type"] == "wastewater"
        assert summary_by_code["SW"]["output_type"] == "solid_waste"
        assert result["recommended_route"]["scheme_code"] == scheme["scheme_code"]
    engine.dispose()


def test_complete_candidate_merges_upstream_leaf_outputs_with_deeper_option_choice() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_partial_option_candidate_data(db)

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["li", "cu"],
                selected_options={"root_leach_path": "acid_leaching"},
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )

        assert result["no_route_reason"] is None
        assert len(result["matched_routes"]) == 1
        scheme = result["matched_routes"][0]
        assert scheme["selected_options"] == {
            "root_leach_path": "acid_leaching",
            "copper_removal": "iron_powder",
        }
        assert {route["code"] for route in scheme["routes"]} == {"R-PARTIAL-LI", "R-PARTIAL-CU"}
        assert {item["code"] for item in scheme["output_summary"]} == {"LI-PARTIAL", "CU-PARTIAL"}
    engine.dispose()


def test_category_recommendation_rejects_routes_with_conflicting_mutual_options() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_complete_candidate_data(db)
        material = db.get(ProcessMaterial, seeded["material_id"])
        lithium = db.scalar(select(ProcessProduct).where(ProcessProduct.code == "LI"))
        nodes = {node.code: node for node in db.scalars(select(ProcessNode)).all()}
        assert material is not None and lithium is not None

        _route_with_nodes(
            db,
            material.id,
            lithium.id,
            "R-BAD-MIXED-AND-ACID",
            [
                (nodes["A1"].id, "root_leach_path", "mixed_acid_roasting"),
                (nodes["A2"].id, "root_leach_path", "acid_leaching"),
                (nodes["C-LI"].id, None, None),
            ],
            [(lithium, "product", "0.20")],
        )
        db.commit()

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["li", "cu"],
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )

        assert result["matched_routes"]
        for scheme in result["matched_routes"]:
            assert not {"A1", "A2"}.issubset(set(scheme["node_codes"]))
            assert "R-BAD-MIXED-AND-ACID" not in {route["code"] for route in scheme["routes"]}
    engine.dispose()


def test_category_recommendation_rejects_legacy_routes_with_conflicting_nodes_without_options() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_complete_candidate_data(db)
        material = db.get(ProcessMaterial, seeded["material_id"])
        lithium = db.scalar(select(ProcessProduct).where(ProcessProduct.code == "LI"))
        nodes = {node.code: node for node in db.scalars(select(ProcessNode)).all()}
        assert material is not None and lithium is not None

        _route_with_nodes(
            db,
            material.id,
            lithium.id,
            "R-LEGACY-MIXED-AND-ACID",
            [
                (nodes["A1"].id, None, None),
                (nodes["A2"].id, None, None),
                (nodes["C-LI"].id, None, None),
            ],
            [(lithium, "product", "0.20")],
        )
        db.commit()

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["li", "cu"],
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )

        assert result["matched_routes"]
        for scheme in result["matched_routes"]:
            assert not {"A1", "A2"}.issubset(set(scheme["node_codes"]))
            assert "R-LEGACY-MIXED-AND-ACID" not in {route["code"] for route in scheme["routes"]}
    engine.dispose()


def test_category_recommendation_rejects_mixed_acid_route_without_tail_gas_treatment() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_complete_candidate_data(db)
        material = db.get(ProcessMaterial, seeded["material_id"])
        lithium = db.scalar(select(ProcessProduct).where(ProcessProduct.code == "LI"))
        nodes = {node.code: node for node in db.scalars(select(ProcessNode)).all()}
        assert material is not None and lithium is not None

        _route_with_nodes(
            db,
            material.id,
            lithium.id,
            "R-LEGACY-MIXED-MISSING-OFFGAS",
            [
                (nodes["A1"].id, None, None),
                (nodes["C-LI"].id, None, None),
            ],
            [(lithium, "product", "0.20")],
        )
        db.commit()

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["li"],
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )

        assert result["matched_routes"]
        for scheme in result["matched_routes"]:
            assert "R-LEGACY-MIXED-MISSING-OFFGAS" not in {route["code"] for route in scheme["routes"]}
            if "A1" in scheme["node_codes"]:
                assert "B1" in scheme["node_codes"]
                assert "B2" in scheme["node_codes"]
    engine.dispose()


def test_target_output_categories_use_and_semantics_without_excluding_extra_products() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_complete_candidate_data(db)

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["li", "cu"],
                selected_options={"root_leach_path": "acid_leaching"},
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )
        assert result["no_route_reason"] is None
        assert {item["code"] for item in result["matched_routes"][0]["output_summary"]} == {"LI", "CU", "CO", "WW", "SW"}

        impossible = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["li", "graphite"],
                selected_options={"root_leach_path": "acid_leaching"},
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )
        assert impossible["matched_routes"] == []
        assert "目标产出类别" in impossible["no_route_reason"]
    engine.dispose()


def test_target_output_categories_keep_ni_co_mn_separate_and_ignore_intermediates() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_complete_candidate_data(db)

        co_result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["co"],
                selected_options={"root_leach_path": "acid_leaching"},
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )
        assert co_result["no_route_reason"] is None
        assert "CO" in {item["code"] for item in co_result["matched_routes"][0]["output_summary"]}

        ni_result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["ni"],
                selected_options={"root_leach_path": "acid_leaching"},
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )
        assert ni_result["matched_routes"] == []
        assert "目标产出类别" in ni_result["no_route_reason"]

        mn_result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["mn"],
                selected_options={"root_leach_path": "acid_leaching"},
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )
        assert mn_result["matched_routes"] == []
        assert "目标产出类别" in mn_result["no_route_reason"]
    engine.dispose()


def test_graphite_category_requires_drying_node_and_product_form_output() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_graphite_category_data(db)

        untreated = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["graphite"],
                selected_options={"graphite_handling": "untreated_solid_waste"},
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )
        assert untreated["matched_routes"] == []
        assert "目标产出类别" in untreated["no_route_reason"]

        dried = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["graphite"],
                selected_options={"graphite_handling": "drying"},
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )
        assert dried["no_route_reason"] is None
        scheme = dried["matched_routes"][0]
        assert "B3" in scheme["node_codes"]
        assert {item["code"] for item in scheme["output_summary"]} == {"GRAPHITE-PROD"}
    engine.dispose()


def test_no_route_reason_reports_impossible_process_option_selection() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_complete_candidate_data(db)

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["li"],
                selected_options={"root_leach_path": "acid_leaching", "unknown_group": "missing"},
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )

        assert result["matched_routes"] == []
        assert "工艺选项" in result["no_route_reason"]
    engine.dispose()


def test_candidates_with_same_output_summary_remain_separate_by_process_choice() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_parallel_choice_data(db)

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["li"],
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )

        assert result["no_route_reason"] is None
        assert len(result["matched_routes"]) == 2
        assert {scheme["selected_options"]["root_leach_path"] for scheme in result["matched_routes"]} == {
            "acid_leaching",
            "mixed_acid_roasting",
        }
        assert [
            [(item["code"], item["amount"], item["output_type"]) for item in scheme["output_summary"]]
            for scheme in result["matched_routes"]
        ] == [[("LI-SAME", "2.000000", "product")], [("LI-SAME", "2.000000", "product")]]
    engine.dispose()


def test_category_financials_include_mixed_acid_tail_gas_treatment() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_complete_candidate_data(db)

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["li"],
                selected_options={"root_leach_path": "mixed_acid_roasting"},
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )

        scheme = result["matched_routes"][0]
        assert scheme["selected_options"]["root_leach_path"] == "mixed_acid_roasting"
        assert set(scheme["node_codes"]) == {"A1", "B1", "B2", "C-LI"}
        assert {item["code"] for item in scheme["output_summary"]} == {"LI", "OFFGAS"}
        offgas = next(item for item in result["waste_outputs"] if item["code"] == "OFFGAS")
        assert offgas["amount"] == "10.000000"
        assert offgas["cost"] == "20.00"
        assert result["recommended_route"]["metrics"]["waste_treatment_cost"] == "20.00"
        assert result["opex"] == "1020.00"
    engine.dispose()


def test_category_recommendation_keeps_candidate_when_output_coefficients_are_missing() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_missing_coefficient_data(db)

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["li"],
                region_code="asia",
                currency="CNY",
                advanced_params={},
            )
        )

        assert result["no_route_reason"] is None
        assert len(result["matched_routes"]) == 1
        summary = result["matched_routes"][0]["output_summary"]
        assert summary[0]["code"] == "LI-MISSING"
        assert summary[0]["amount"] == "0.000000"
        assert any("产出系数未配置" in warning for warning in result["warnings"])
    engine.dispose()


def test_financial_ranking_uses_complete_output_accounting_and_ignores_intermediate_flows() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seeded = _seed_ranking_and_intermediate_data(db)

        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": seeded["material_id"], "amount": "10", "unit": "t"}],
                target_output_categories=["li"],
                region_code="asia",
                currency="CNY",
                sort_criteria="npv",
                advanced_params={},
            )
        )

        assert result["matched_routes"][0]["selected_options"]["root_leach_path"] == "acid_leaching"
        assert result["matched_routes"][1]["selected_options"]["root_leach_path"] == "mixed_acid_roasting"
        assert "INTERMEDIATE" not in {item["code"] for item in result["matched_routes"][0]["output_summary"]}
        assert result["matched_routes"][0]["metrics"]["waste_treatment_cost"] == "0.00"
        assert result["matched_routes"][1]["metrics"]["waste_treatment_cost"] == "500.00"
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
    asset = ProcessAsset(
        code="EQ001",
        name="浸出槽",
        type="reactor_tank",
        asset_class="equipment",
        unit="set",
        status="enabled",
    )
    db.add(asset)
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
                asset_id=asset.id,
                equipment_name="浸出槽",
                quantity=Decimal("1"),
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
        ("asset", asset.id, Decimal("100"), "set"),
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


def _seed_complete_candidate_data(db: Session) -> dict[str, object]:
    material = ProcessMaterial(code="BM-CAT", name="Black Mass", type="battery_black_mass", unit="t", status="enabled")
    products = {
        "li": ProcessProduct(
            code="LI",
            name="Lithium Product",
            type="product",
            unit="t",
            output_type="product",
            target_output_category="li",
            is_product_form=True,
            status="enabled",
        ),
        "cu": ProcessProduct(
            code="CU",
            name="Copper Product",
            type="product",
            unit="t",
            output_type="product",
            target_output_category="cu",
            is_product_form=True,
            status="enabled",
        ),
        "co": ProcessProduct(
            code="CO",
            name="Cobalt Byproduct",
            type="product",
            unit="t",
            output_type="byproduct",
            target_output_category="co",
            is_product_form=True,
            status="enabled",
        ),
        "offgas": ProcessProduct(
            code="OFFGAS",
            name="Mixed Acid Offgas",
            type="waste_gas",
            unit="Nm3",
            output_type="waste_gas",
            is_product_form=False,
            treatment_cost=Decimal("2"),
            status="enabled",
        ),
        "ww": ProcessProduct(
            code="WW",
            name="Final Wastewater",
            type="wastewater",
            unit="t",
            output_type="wastewater",
            is_product_form=False,
            treatment_cost=Decimal("5"),
            status="enabled",
        ),
        "sw": ProcessProduct(
            code="SW",
            name="Final Solid Waste",
            type="solid_waste",
            unit="t",
            output_type="solid_waste",
            is_product_form=False,
            treatment_cost=Decimal("8"),
            status="enabled",
        ),
    }
    db.add(material)
    db.add_all(products.values())
    db.flush()

    nodes = {
        code: ProcessNode(code=code, name=name, node_type="hydrometallurgy", status="enabled", version="V1")
        for code, name in (
            ("A1", "Mixed Acid Roasting"),
            ("B1", "Mixed Acid Offgas Treatment"),
            ("B2", "Water Leaching"),
            ("A2", "Acid Leaching"),
            ("C-LI", "Lithium Finish"),
            ("C-CU", "Copper Finish"),
            ("C-CO", "Cobalt Finish"),
            ("W-FINAL", "Final Waste Handling"),
        )
    }
    db.add_all(nodes.values())
    db.flush()
    db.add(
        ProcessNodeOutput(
            node_id=nodes["B1"].id,
            product_id=products["offgas"].id,
            output_type="waste_gas",
            output_per_ton=Decimal("1"),
            formula_type="fixed",
            treatment_cost=Decimal("2"),
            unit="Nm3/t-BM",
        )
    )

    routes = [
        _route_with_nodes(
            db,
            material.id,
            products["li"].id,
            "R-MIX-LI",
            [
                (nodes["A1"].id, "root_leach_path", "mixed_acid_roasting"),
                (nodes["B1"].id, None, None),
                (nodes["B2"].id, None, None),
                (nodes["C-LI"].id, None, None),
            ],
            [(products["li"], "product", "0.20")],
        ),
        _route_with_nodes(
            db,
            material.id,
            products["li"].id,
            "R-ACID-LI",
            [(nodes["A2"].id, "root_leach_path", "acid_leaching"), (nodes["C-LI"].id, None, None)],
            [(products["li"], "product", "0.20")],
        ),
        _route_with_nodes(
            db,
            material.id,
            products["cu"].id,
            "R-ACID-CU",
            [(nodes["A2"].id, "root_leach_path", "acid_leaching"), (nodes["C-CU"].id, None, None)],
            [(products["cu"], "product", "0.10")],
        ),
        _route_with_nodes(
            db,
            material.id,
            products["co"].id,
            "R-ACID-CO",
            [(nodes["A2"].id, "root_leach_path", "acid_leaching"), (nodes["C-CO"].id, None, None)],
            [(products["co"], "byproduct", "0.05")],
        ),
        _route_with_nodes(
            db,
            material.id,
            products["sw"].id,
            "R-ACID-WASTE",
            [(nodes["A2"].id, "root_leach_path", "acid_leaching"), (nodes["W-FINAL"].id, None, None)],
            [(products["ww"], "wastewater", "0.30"), (products["sw"], "solid_waste", "0.04")],
        ),
    ]
    db.flush()

    price_specs = [("material", material.id, "100", "t")]
    price_specs.extend(
        ("product", product.id, price, product.unit)
        for product, price in (
            (products["li"], "1000"),
            (products["cu"], "500"),
            (products["co"], "300"),
            (products["offgas"], "2"),
            (products["ww"], "5"),
            (products["sw"], "8"),
        )
    )
    db.add_all(
        [
            ProcessRegionPrice(
                owner_type=owner_type,
                owner_id=owner_id,
                region_code="asia",
                region_name="Asia",
                currency="CNY",
                unit_price=Decimal(price),
                unit=unit,
                status="enabled",
            )
            for owner_type, owner_id, price, unit in price_specs
        ]
    )
    db.commit()
    return {"material_id": material.id, "route_ids": [route.id for route in routes]}


def _seed_partial_option_candidate_data(db: Session) -> dict[str, object]:
    material = ProcessMaterial(code="BM-PART", name="Black Mass", type="battery_black_mass", unit="t", status="enabled")
    lithium = ProcessProduct(
        code="LI-PARTIAL",
        name="Lithium Product",
        type="product",
        unit="t",
        output_type="product",
        target_output_category="li",
        is_product_form=True,
        status="enabled",
    )
    copper = ProcessProduct(
        code="CU-PARTIAL",
        name="Copper Product",
        type="product",
        unit="t",
        output_type="product",
        target_output_category="cu",
        is_product_form=True,
        status="enabled",
    )
    db.add_all([material, lithium, copper])
    db.flush()

    nodes = {
        code: ProcessNode(code=code, name=name, node_type="hydrometallurgy", status="enabled", version="V1")
        for code, name in (("A2", "Acid Leaching"), ("LI-F", "Lithium Finish"), ("B4", "Copper Removal"))
    }
    db.add_all(nodes.values())
    db.flush()
    routes = [
        _route_with_nodes(
            db,
            material.id,
            lithium.id,
            "R-PARTIAL-LI",
            [(nodes["A2"].id, "root_leach_path", "acid_leaching"), (nodes["LI-F"].id, None, None)],
            [(lithium, "product", "0.20")],
        ),
        _route_with_nodes(
            db,
            material.id,
            copper.id,
            "R-PARTIAL-CU",
            [
                (nodes["A2"].id, "root_leach_path", "acid_leaching"),
                (nodes["B4"].id, "copper_removal", "iron_powder"),
            ],
            [(copper, "product", "0.10")],
        ),
    ]
    db.add_all(
        [
            ProcessRegionPrice(
                owner_type=owner_type,
                owner_id=owner_id,
                region_code="asia",
                region_name="Asia",
                currency="CNY",
                unit_price=Decimal(price),
                unit="t",
                status="enabled",
            )
            for owner_type, owner_id, price in (
                ("material", material.id, "100"),
                ("product", lithium.id, "1000"),
                ("product", copper.id, "500"),
            )
        ]
    )
    db.commit()
    return {"material_id": material.id, "route_ids": [route.id for route in routes]}


def _route_with_nodes(
    db: Session,
    material_id: int,
    representative_product_id: int,
    code: str,
    node_specs: list[tuple[int, str | None, str | None]],
    output_specs: list[tuple[ProcessProduct, str, str]],
) -> ProcessRoute:
    route = ProcessRoute(
        code=code,
        name=f"{code} Route",
        input_material_id=material_id,
        final_product_id=representative_product_id,
        status="enabled",
        version="V1",
    )
    db.add(route)
    db.flush()
    db.add_all(
        [
            ProcessRouteNode(
                route_id=route.id,
                node_id=node_id,
                sort_order=index,
                option_group_code=option_group,
                option_code=option_code,
            )
            for index, (node_id, option_group, option_code) in enumerate(node_specs, start=1)
        ]
    )
    db.add_all(
        [
            ProcessCalculationOutput(
                route_id=route.id,
                output_type=output_type,
                product_id=product.id,
                output_name=product.name,
                formula_type="fixed",
                recovery_rate=Decimal("1"),
                unit=f"{product.unit}/t-BM",
                output_ratio=Decimal(ratio),
                treatment_cost=product.treatment_cost,
            )
            for product, output_type, ratio in output_specs
        ]
    )
    return route


def _seed_graphite_category_data(db: Session) -> dict[str, object]:
    material = ProcessMaterial(code="BM-GR", name="Black Mass With Graphite", type="battery_black_mass", unit="t", status="enabled")
    untreated_waste = ProcessProduct(
        code="GRAPHITE-WASTE",
        name="Untreated Graphite Residue",
        type="solid_waste",
        unit="t",
        output_type="solid_waste",
        target_output_category=None,
        is_product_form=False,
        treatment_cost=Decimal("5"),
        status="enabled",
    )
    graphite_product = ProcessProduct(
        code="GRAPHITE-PROD",
        name="Dried Graphite Product",
        type="product",
        unit="t",
        output_type="product",
        target_output_category="graphite",
        is_product_form=True,
        status="enabled",
    )
    db.add_all([material, untreated_waste, graphite_product])
    db.flush()

    nodes = {
        code: ProcessNode(code=code, name=name, node_type="hydrometallurgy", status="enabled", version="V1")
        for code, name in (("A2", "Acid Leaching"), ("B3", "Graphite Drying"), ("W-GR", "Untreated Graphite Waste"))
    }
    db.add_all(nodes.values())
    db.flush()

    routes = [
        _route_with_nodes(
            db,
            material.id,
            untreated_waste.id,
            "R-GR-WASTE",
            [(nodes["A2"].id, "graphite_handling", "untreated_solid_waste"), (nodes["W-GR"].id, None, None)],
            [(untreated_waste, "solid_waste", "0.60")],
        ),
        _route_with_nodes(
            db,
            material.id,
            graphite_product.id,
            "R-GR-DRIED",
            [(nodes["A2"].id, "graphite_handling", "drying"), (nodes["B3"].id, None, None)],
            [(graphite_product, "product", "0.55")],
        ),
    ]
    db.flush()
    db.add_all(
        [
            ProcessRegionPrice(
                owner_type=owner_type,
                owner_id=owner_id,
                region_code="asia",
                region_name="Asia",
                currency="CNY",
                unit_price=Decimal(price),
                unit=unit,
                status="enabled",
            )
            for owner_type, owner_id, price, unit in (
                ("material", material.id, "100", "t"),
                ("product", untreated_waste.id, "5", "t"),
                ("product", graphite_product.id, "200", "t"),
            )
        ]
    )
    db.commit()
    return {"material_id": material.id, "route_ids": [route.id for route in routes]}


def _seed_parallel_choice_data(db: Session) -> dict[str, object]:
    material = ProcessMaterial(code="BM-PAR", name="Black Mass", type="battery_black_mass", unit="t", status="enabled")
    product = ProcessProduct(
        code="LI-SAME",
        name="Same Lithium Product",
        type="product",
        unit="t",
        output_type="product",
        target_output_category="li",
        is_product_form=True,
        status="enabled",
    )
    db.add_all([material, product])
    db.flush()

    acid_node = ProcessNode(code="A2-SAME", name="Acid Leaching", node_type="hydrometallurgy", status="enabled", version="V1")
    roasting_node = ProcessNode(code="A1-SAME", name="Mixed Acid Roasting", node_type="hydrometallurgy", status="enabled", version="V1")
    db.add_all([acid_node, roasting_node])
    db.flush()
    routes = [
        _route_with_nodes(
            db,
            material.id,
            product.id,
            "R-SAME-ACID",
            [(acid_node.id, "root_leach_path", "acid_leaching")],
            [(product, "product", "0.20")],
        ),
        _route_with_nodes(
            db,
            material.id,
            product.id,
            "R-SAME-ROAST",
            [(roasting_node.id, "root_leach_path", "mixed_acid_roasting")],
            [(product, "product", "0.20")],
        ),
    ]
    db.add_all(
        [
            ProcessRegionPrice(
                owner_type=owner_type,
                owner_id=owner_id,
                region_code="asia",
                region_name="Asia",
                currency="CNY",
                unit_price=Decimal(price),
                unit=unit,
                status="enabled",
            )
            for owner_type, owner_id, price, unit in (
                ("material", material.id, "100", "t"),
                ("product", product.id, "1000", "t"),
            )
        ]
    )
    db.commit()
    return {"material_id": material.id, "route_ids": [route.id for route in routes]}


def _seed_missing_coefficient_data(db: Session) -> dict[str, object]:
    material = ProcessMaterial(code="BM-MISS", name="Black Mass", type="battery_black_mass", unit="t", status="enabled")
    product = ProcessProduct(
        code="LI-MISSING",
        name="Lithium Product Without Coefficient",
        type="product",
        unit="t",
        output_type="product",
        target_output_category="li",
        is_product_form=True,
        status="enabled",
    )
    db.add_all([material, product])
    db.flush()
    node = ProcessNode(code="A2-MISS", name="Acid Leaching", node_type="hydrometallurgy", status="enabled", version="V1")
    db.add(node)
    db.flush()
    route = _route_with_nodes(
        db,
        material.id,
        product.id,
        "R-MISSING",
        [(node.id, "root_leach_path", "acid_leaching")],
        [(product, "product", "0")],
    )
    db.add_all(
        [
            ProcessRegionPrice(
                owner_type="material",
                owner_id=material.id,
                region_code="asia",
                region_name="Asia",
                currency="CNY",
                unit_price=Decimal("100"),
                unit="t",
                status="enabled",
            ),
            ProcessRegionPrice(
                owner_type="product",
                owner_id=product.id,
                region_code="asia",
                region_name="Asia",
                currency="CNY",
                unit_price=Decimal("1000"),
                unit="t",
                status="enabled",
            ),
        ]
    )
    db.commit()
    return {"material_id": material.id, "route_ids": [route.id]}


def _seed_ranking_and_intermediate_data(db: Session) -> dict[str, object]:
    material = ProcessMaterial(code="BM-RANK", name="Black Mass", type="battery_black_mass", unit="t", status="enabled")
    product = ProcessProduct(
        code="LI-RANK",
        name="Lithium Product",
        type="product",
        unit="t",
        output_type="product",
        target_output_category="li",
        is_product_form=True,
        status="enabled",
    )
    expensive_waste = ProcessProduct(
        code="EXP-WASTE",
        name="Expensive Waste",
        type="solid_waste",
        unit="t",
        output_type="solid_waste",
        is_product_form=False,
        treatment_cost=Decimal("100"),
        status="enabled",
    )
    intermediate = ProcessProduct(
        code="INTERMEDIATE",
        name="Intermediate Stream",
        type="product",
        unit="t",
        output_type="product",
        target_output_category="li",
        is_product_form=False,
        status="enabled",
    )
    db.add_all([material, product, expensive_waste, intermediate])
    db.flush()

    acid_node = ProcessNode(code="A2-RANK", name="Acid Leaching", node_type="hydrometallurgy", status="enabled", version="V1")
    roast_node = ProcessNode(code="A1-RANK", name="Mixed Acid Roasting", node_type="hydrometallurgy", status="enabled", version="V1")
    finish_node = ProcessNode(code="F-RANK", name="Product Finishing", node_type="hydrometallurgy", status="enabled", version="V1")
    db.add_all([acid_node, roast_node, finish_node])
    db.flush()
    db.add(
        ProcessNodeOutput(
            node_id=finish_node.id,
            product_id=intermediate.id,
            output_type="product",
            output_per_ton=Decimal("0.30"),
            formula_type="fixed",
            unit="t/t-BM",
        )
    )
    routes = [
        _route_with_nodes(
            db,
            material.id,
            product.id,
            "R-RANK-ACID",
            [(acid_node.id, "root_leach_path", "acid_leaching"), (finish_node.id, None, None)],
            [(product, "product", "0.20")],
        ),
        _route_with_nodes(
            db,
            material.id,
            product.id,
            "R-RANK-ROAST",
            [(roast_node.id, "root_leach_path", "mixed_acid_roasting"), (finish_node.id, None, None)],
            [(product, "product", "0.20"), (expensive_waste, "solid_waste", "0.50")],
        ),
    ]
    db.add_all(
        [
            ProcessRegionPrice(
                owner_type=owner_type,
                owner_id=owner_id,
                region_code="asia",
                region_name="Asia",
                currency="CNY",
                unit_price=Decimal(price),
                unit=unit,
                status="enabled",
            )
            for owner_type, owner_id, price, unit in (
                ("material", material.id, "100", "t"),
                ("product", product.id, "1000", "t"),
                ("product", expensive_waste.id, "100", "t"),
                ("product", intermediate.id, "9999", "t"),
            )
        ]
    )
    db.commit()
    return {"material_id": material.id, "route_ids": [route.id for route in routes]}
