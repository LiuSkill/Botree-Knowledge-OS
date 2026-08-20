"""Default process route data generated from the updated route drawing."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "scripts"))

from app.core.database import seed_process_config_defaults, sync_mixed_acid_residue_route_defaults  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.process_config import (  # noqa: E402
    ProcessCalculationOutput,
    ProcessMaterial,
    ProcessNode,
    ProcessNodeOutput,
    ProcessProduct,
    ProcessRoute,
    ProcessRouteNode,
)
from app.models.user import User  # noqa: E402
from app.schemas.process_calculator import ProcessCalculatorRequest  # noqa: E402
from app.services.process_calculator_service import ProcessCalculatorService  # noqa: E402
from import_financial_calculator_excel import build_product_route_paths  # noqa: E402


MUTUALLY_EXCLUSIVE_CODE_GROUPS = (
    {"A1", "A2"},
    {"B8", "B9"},
    {"B3", "B7"},
    {"D1", "D2"},
    {"F1", "F2"},
    {"E3", "E4"},
    {"F5", "F10"},
    {"F6", "G5", "F7", "F8"},
)

MUTUALLY_EXCLUSIVE_NAME_GROUPS = (
    {"混酸焙烧", "酸浸"},
    {"水浸渣酸浸", "氧化镍钴渣产品"},
    {"石墨干燥", "石墨渣废固"},
    {"树脂除氟(PREL)", "硫酸锂深度化学除杂"},
    {"工业级碳酸锂干燥包装", "碳化热析"},
    {"MHP沉淀", "P204萃取"},
    {"锰溶液除杂", "碳酸锰沉淀"},
    {"BC196共萃", "C272萃取钴", "P507萃取钴", "P507萃镍镁"},
)


def test_default_process_routes_follow_updated_drawing_semantics() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with session_factory() as db:
        _seed_admin(db)
        seed_process_config_defaults(db)
        db.commit()

        products = {product.code: product for product in db.scalars(select(ProcessProduct)).all()}
        assert products["P17"].target_output_category == "graphite"
        assert products["P17"].is_product_form is True
        assert products["P18"].output_type == "solid_waste"
        assert products["P18"].target_output_category is None
        assert products["P18"].is_product_form is False
        assert products["P39"].name == "氧化镍钴渣"
        assert products["P39"].output_type == "product"
        assert products["P39"].target_output_category is None
        assert products["P39"].is_product_form is True

        nodes_by_code = {node.code: node for node in db.scalars(select(ProcessNode)).all()}
        nodes_by_id = {node.id: node for node in nodes_by_code.values()}
        assert nodes_by_code["B1"].name == "混酸焙烧尾气处理"
        assert nodes_by_code["B3"].name == "石墨干燥"
        assert nodes_by_code["B7"].name == "石墨渣废固"
        assert nodes_by_code["B8"].name == "水浸渣酸浸"
        assert nodes_by_code["B9"].name == "氧化镍钴渣产品"
        assert nodes_by_code["F10"].name == "碳酸锰沉淀"
        node_outputs = list(db.scalars(select(ProcessNodeOutput).where(ProcessNodeOutput.is_deleted.is_(False))).all())
        assert any(
            output.node_id == nodes_by_code["B7"].id
            and output.product_id == products["P18"].id
            and output.output_type == "solid_waste"
            for output in node_outputs
        )

        route_nodes_by_route_id: dict[int, list[ProcessRouteNode]] = {}
        for route_node in db.scalars(select(ProcessRouteNode).order_by(ProcessRouteNode.sort_order.asc())).all():
            route_nodes_by_route_id.setdefault(route_node.route_id, []).append(route_node)

        assert route_nodes_by_route_id
        for route in db.scalars(select(ProcessRoute)).all():
            route_nodes = route_nodes_by_route_id[route.id]
            node_codes = [nodes_by_id[item.node_id].code for item in route_nodes]
            for group in MUTUALLY_EXCLUSIVE_CODE_GROUPS:
                assert len(group.intersection(node_codes)) <= 1, route.code
            assert [item.option_code for item in route_nodes if item.option_group_code == "root_leach_path"] in (
                ["mixed_acid_roasting"],
                ["acid_leaching"],
            )
            if "A1" in node_codes:
                assert "B1" in node_codes, route.code
                assert "B2" in node_codes, route.code
            if "A1" in node_codes and {"B3", "B4", "B5", "B6", "B7", "C3", "E3", "E4"}.intersection(node_codes):
                assert "B8" in node_codes, route.code
            if route.final_product_id == products["P17"].id:
                assert node_codes in (
                    ["A2", "B3"],
                    ["A1", "B1", "B2", "B8", "B3"],
                ), route.code
            if route.final_product_id == products["P39"].id:
                assert node_codes == ["A1", "B1", "B2", "B9"], route.code

        lithium_route = db.scalar(select(ProcessRoute).where(ProcessRoute.code == "A1-B1-B2-C1-D1-E1"))
        assert lithium_route is not None
        lithium_nodes = route_nodes_by_route_id[lithium_route.id]
        node_params = {
            nodes_by_id[item.node_id].code: json.loads(item.node_params_json)
            for item in lithium_nodes
            if item.node_params_json
        }
        assert node_params["B1"]["parent_node_code"] == "A1"
        assert node_params["B1"]["parallel_group_code"] == "mixed_acid_primary_outputs"
        assert node_params["B1"]["continues_route"] is False
        assert node_params["B2"]["parent_node_code"] == "A1"
        assert node_params["B2"]["parallel_group_code"] == "mixed_acid_primary_outputs"
        assert node_params["B2"]["continues_route"] is True
        downstream_route = db.scalar(select(ProcessRoute).where(ProcessRoute.code == "A1-B1-B2-B8-B3-B4"))
        assert downstream_route is not None
        downstream_nodes = route_nodes_by_route_id[downstream_route.id]
        downstream_params = {
            nodes_by_id[item.node_id].code: json.loads(item.node_params_json)
            for item in downstream_nodes
            if item.node_params_json
        }
        assert downstream_params["B3"]["parent_node_code"] == "B8"
        assert downstream_params["B3"]["parallel_group_code"] == "acid_leach_primary_outputs"
        assert downstream_params["B3"]["continues_route"] is False
        assert downstream_params["B4"]["parent_node_code"] == "B8"
        assert downstream_params["B4"]["parallel_group_code"] == "acid_leach_primary_outputs"
        assert downstream_params["B4"]["continues_route"] is True


def test_default_process_config_json_contains_route_output_summary() -> None:
    data = json.loads((BASE_DIR / "app" / "core" / "process_config_defaults.json").read_text(encoding="utf-8"))
    route = next(item for item in data["routes"] if item["code"] == "A1-B1-B2-C1-D1-E1")
    oxide_route = next(item for item in data["routes"] if item["code"] == "A1-B1-B2-B9")
    b1_node = next(item for item in data["nodes"] if item["code"] == "B1")

    output_types = {item["output_type"] for item in route["calculation_outputs"]}
    assert output_types == {"product"}
    assert all(item.get("code") != "P38" for item in data["products"])
    assert all(item.get("product_code") != "P38" for item in route["calculation_outputs"])
    assert all(
        output.get("product_code") != "P38"
        for node in data["nodes"]
        for output in node.get("outputs", [])
    )
    assert b1_node.get("outputs", []) == []
    assert oxide_route["final_product_code"] == "P39"
    assert any(item["output_name"] == "氧化镍钴渣" for item in oxide_route["calculation_outputs"])


def test_default_calculator_recommends_mixed_acid_route_for_li_and_ni() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with session_factory() as db:
        _seed_admin(db)
        seed_process_config_defaults(db)
        db.commit()

        material = db.scalar(select(ProcessMaterial).where(ProcessMaterial.code == "M1"))
        assert material is not None
        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": material.id, "amount": "5000", "unit": "t"}],
                target_output_categories=["ni", "li"],
                region_code="americas",
                currency="USD",
                sort_criteria="npv",
                advanced_params={},
            )
        )

        assert result["no_route_reason"] is None
        assert result["matched_routes"]
        scheme = result["matched_routes"][0]
        assert scheme["selected_options"]["root_leach_path"] == "mixed_acid_roasting"
        b1_outputs = [
            output
            for route in scheme["routes"]
            for node in route["nodes"]
            if node["code"] == "B1"
            for output in node["outputs"]
        ]
        assert all(output["product_code"] != "P38" for output in b1_outputs)
        assert all(item["code"] != "P38" for item in scheme["output_summary"])
        assert all(item["code"] != "P38" for item in result["waste_outputs"])
        assert all("尾气" not in warning for warning in scheme["warnings"])
        categories = {
            item["code"]
            for item in scheme["output_summary"]
            if item["output_type"] in {"product", "byproduct"}
        }
        assert {"P1", "P11"}.issubset(categories)
    engine.dispose()


def test_default_calculator_single_target_categories_choose_different_structures() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with session_factory() as db:
        _seed_admin(db)
        seed_process_config_defaults(db)
        db.commit()

        material = db.scalar(select(ProcessMaterial).where(ProcessMaterial.code == "M1"))
        assert material is not None
        service = ProcessCalculatorService(db)

        li_result = service.calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": material.id, "amount": "5000", "unit": "t"}],
                target_output_categories=["li"],
                region_code="americas",
                currency="USD",
                sort_criteria="npv",
                advanced_params={},
            )
        )
        ni_result = service.calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": material.id, "amount": "5000", "unit": "t"}],
                target_output_categories=["ni"],
                region_code="americas",
                currency="USD",
                sort_criteria="npv",
                advanced_params={},
            )
        )

        assert li_result["no_route_reason"] is None
        assert ni_result["no_route_reason"] is None
        li_scheme = li_result["matched_routes"][0]
        ni_scheme = ni_result["matched_routes"][0]
        assert li_scheme["scheme_code"] != ni_scheme["scheme_code"]
        assert li_scheme["selected_options"]["root_leach_path"] == "mixed_acid_roasting"
        assert ni_scheme["selected_options"]["root_leach_path"] == "acid_leaching"
        assert "P1" in {item["code"] for item in li_scheme["output_summary"]}
        assert "P11" in {item["code"] for item in ni_scheme["output_summary"]}
    engine.dispose()


def test_default_calculator_route_refs_include_selected_solid_waste_outputs() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with session_factory() as db:
        _seed_admin(db)
        seed_process_config_defaults(db)
        db.commit()

        material = db.scalar(select(ProcessMaterial).where(ProcessMaterial.code == "M1"))
        assert material is not None
        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": material.id, "amount": "5000", "unit": "t"}],
                target_output_categories=["ni"],
                selected_options={"graphite_handling": "untreated_solid_waste"},
                region_code="americas",
                currency="USD",
                sort_criteria="npv",
                advanced_params={},
            )
        )

        assert result["no_route_reason"] is None
        assert result["matched_routes"]
        scheme = result["matched_routes"][0]
        assert scheme["selected_options"]["graphite_handling"] == "untreated_solid_waste"
        b7_outputs = [
            output
            for route in scheme["routes"]
            for node in route["nodes"]
            if node["code"] == "B7"
            for output in node["outputs"]
        ]
        assert any(output["output_type"] == "solid_waste" and output["product_code"] == "P18" for output in b7_outputs)
    engine.dispose()


def test_default_calculator_graphite_product_and_waste_outputs_are_exclusive() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with session_factory() as db:
        _seed_admin(db)
        seed_process_config_defaults(db)
        db.commit()

        material = db.scalar(select(ProcessMaterial).where(ProcessMaterial.code == "M1"))
        assert material is not None

        drying = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": material.id, "amount": "5000", "unit": "t"}],
                target_output_categories=["ni"],
                selected_options={"graphite_handling": "drying"},
                region_code="americas",
                currency="USD",
                sort_criteria="npv",
                advanced_params={},
            )
        )

        assert drying["no_route_reason"] is None
        drying_scheme = drying["matched_routes"][0]
        drying_summary_codes = {item["code"] for item in drying_scheme["output_summary"]}
        assert "P17" in drying_summary_codes
        assert "P18" not in drying_summary_codes
        b3_outputs = [
            output
            for route in drying_scheme["routes"]
            for node in route["nodes"]
            if node["code"] == "B3"
            for output in node["outputs"]
        ]
        assert any(output["output_type"] == "product" and output["product_code"] == "P17" for output in b3_outputs)

        untreated = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": material.id, "amount": "5000", "unit": "t"}],
                target_output_categories=["ni"],
                selected_options={"graphite_handling": "untreated_solid_waste"},
                region_code="americas",
                currency="USD",
                sort_criteria="npv",
                advanced_params={},
            )
        )

        assert untreated["no_route_reason"] is None
        untreated_scheme = untreated["matched_routes"][0]
        untreated_summary_codes = {item["code"] for item in untreated_scheme["output_summary"]}
        assert "P18" in untreated_summary_codes
        assert "P17" not in untreated_summary_codes
        b7_outputs = [
            output
            for route in untreated_scheme["routes"]
            for node in route["nodes"]
            if node["code"] == "B7"
            for output in node["outputs"]
        ]
        assert any(output["output_type"] == "solid_waste" and output["product_code"] == "P18" for output in b7_outputs)
    engine.dispose()


def test_default_water_purification_has_single_solid_waste_output() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with session_factory() as db:
        _seed_admin(db)
        seed_process_config_defaults(db)
        db.commit()

        legacy_variant = db.scalar(
            select(ProcessProduct).where(ProcessProduct.code == "P19", ProcessProduct.is_deleted.is_(False))
        )
        assert legacy_variant is None
        c3_node = db.scalar(select(ProcessNode).where(ProcessNode.code == "C3"))
        assert c3_node is not None
        c3_outputs = db.execute(
            select(ProcessNodeOutput, ProcessProduct)
            .join(ProcessProduct, ProcessProduct.id == ProcessNodeOutput.product_id)
            .where(ProcessNodeOutput.node_id == c3_node.id, ProcessNodeOutput.is_deleted.is_(False))
        ).all()
        assert [(product.code, output.output_type) for output, product in c3_outputs] == [("P20", "solid_waste")]

        material = db.scalar(select(ProcessMaterial).where(ProcessMaterial.code == "M1"))
        assert material is not None
        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": material.id, "amount": "5000", "unit": "t"}],
                target_output_categories=["ni"],
                selected_options={"copper_removal": "iron_powder"},
                region_code="americas",
                currency="USD",
                sort_criteria="npv",
                advanced_params={},
            )
        )

        assert result["no_route_reason"] is None
        scheme = result["matched_routes"][0]
        summary_codes = {item["code"] for item in scheme["output_summary"]}
        assert "P20" in summary_codes
        assert "P19" not in summary_codes
        c3_route_outputs = [
            output
            for route in scheme["routes"]
            for node in route["nodes"]
            if node["code"] == "C3"
            for output in node["outputs"]
        ]
        assert {(output["product_code"], output["output_type"]) for output in c3_route_outputs} == {
            ("P20", "solid_waste")
        }
    engine.dispose()


def test_startup_sync_deduplicates_default_node_outputs() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with session_factory() as db:
        _seed_admin(db)
        seed_process_config_defaults(db)
        db.commit()

        c3_node = db.scalar(select(ProcessNode).where(ProcessNode.code == "C3"))
        p20_product = db.scalar(select(ProcessProduct).where(ProcessProduct.code == "P20"))
        assert c3_node is not None and p20_product is not None
        db.add(
            ProcessNodeOutput(
                node_id=c3_node.id,
                product_id=p20_product.id,
                output_type="solid_waste",
                output_per_ton=Decimal("0.131468"),
                formula_type="fixed",
                scale_param=json.dumps(
                    {
                        "source_sheet": "产出",
                        "node_output_role": "waste_treatment",
                        "binding_rule": "route_tree",
                        "node_name": "水解除杂",
                    },
                    ensure_ascii=False,
                ),
                unit="t/t-BM",
                sort_order=99,
                is_deleted=False,
            )
        )
        db.commit()

        sync_mixed_acid_residue_route_defaults(db)
        db.commit()

        c3_outputs = db.execute(
            select(ProcessNodeOutput, ProcessProduct)
            .join(ProcessProduct, ProcessProduct.id == ProcessNodeOutput.product_id)
            .where(ProcessNodeOutput.node_id == c3_node.id, ProcessNodeOutput.is_deleted.is_(False))
        ).all()
        assert [(product.code, output.output_type) for output, product in c3_outputs] == [("P20", "solid_waste")]
    engine.dispose()


def test_startup_sync_deletes_legacy_mixed_acid_tail_gas_output() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with session_factory() as db:
        _seed_admin(db)
        seed_process_config_defaults(db)
        db.commit()

        a1_node = db.scalar(select(ProcessNode).where(ProcessNode.code == "A1"))
        b1_node = db.scalar(select(ProcessNode).where(ProcessNode.code == "B1"))
        assert a1_node is not None and b1_node is not None
        p38_product = ProcessProduct(
            code="P38",
            name="混酸焙烧尾气处理废气",
            type="waste_gas",
            unit="Nm3/t-BM",
            output_type="waste_gas",
            is_product_form=False,
            status="enabled",
            is_deleted=False,
        )
        db.add(p38_product)
        db.flush()
        b1_node.name = "混酸焙烧尾气"
        for node in (a1_node, b1_node):
            db.add(
                ProcessNodeOutput(
                    node_id=node.id,
                    product_id=p38_product.id,
                    output_type="waste_gas",
                    output_per_ton=Decimal("0"),
                    formula_type="fixed",
                    unit="Nm3/t-BM",
                    sort_order=99,
                    is_deleted=False,
                )
            )
        db.commit()

        sync_mixed_acid_residue_route_defaults(db)
        db.commit()

        assert b1_node.name == "混酸焙烧尾气处理"
        assert p38_product.is_deleted is True
        a1_outputs = db.execute(
            select(ProcessNodeOutput, ProcessProduct)
            .join(ProcessProduct, ProcessProduct.id == ProcessNodeOutput.product_id)
            .where(ProcessNodeOutput.node_id == a1_node.id, ProcessNodeOutput.is_deleted.is_(False))
        ).all()
        b1_outputs = db.execute(
            select(ProcessNodeOutput, ProcessProduct)
            .join(ProcessProduct, ProcessProduct.id == ProcessNodeOutput.product_id)
            .where(ProcessNodeOutput.node_id == b1_node.id, ProcessNodeOutput.is_deleted.is_(False))
        ).all()
        assert [(product.code, output.output_type) for output, product in a1_outputs] == []
        assert [(product.code, output.output_type) for output, product in b1_outputs] == []
    engine.dispose()


def test_startup_sync_backfills_existing_process_route_semantics() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with session_factory() as db:
        _seed_admin(db)
        seed_process_config_defaults(db)
        db.commit()

        for product in db.scalars(select(ProcessProduct).where(ProcessProduct.code.in_(("P1", "P11")))):
            product.target_output_category = None
            product.is_product_form = False
        b1_node = db.scalar(select(ProcessNode).where(ProcessNode.code == "B1"))
        assert b1_node is not None
        for output in db.scalars(select(ProcessNodeOutput).where(ProcessNodeOutput.node_id == b1_node.id)):
            db.delete(output)
        b3_node = db.scalar(select(ProcessNode).where(ProcessNode.code == "B3"))
        graphite_waste = db.scalar(select(ProcessProduct).where(ProcessProduct.code == "P18"))
        assert b3_node is not None and graphite_waste is not None
        db.add(
            ProcessNodeOutput(
                node_id=b3_node.id,
                product_id=graphite_waste.id,
                output_type="solid_waste",
                output_per_ton=Decimal("0.615385"),
                formula_type="fixed",
                scale_param=json.dumps(
                    {
                        "source_sheet": "产出",
                        "node_output_role": "waste_treatment",
                        "binding_rule": "route_tree",
                        "node_name": "石墨干燥",
                    },
                    ensure_ascii=False,
                ),
                unit="t/t-BM",
                sort_order=99,
                remark="节点三废产出",
                is_deleted=False,
            )
        )
        c3_node = db.scalar(select(ProcessNode).where(ProcessNode.code == "C3"))
        assert c3_node is not None
        legacy_water_purification_waste = db.scalar(select(ProcessProduct).where(ProcessProduct.code == "P19"))
        if legacy_water_purification_waste is None:
            legacy_water_purification_waste = ProcessProduct(
                code="P19",
                name="水解除杂渣(铁粉法)",
                type="solid_waste",
                unit="t/t-BM",
                output_type="solid_waste",
                is_product_form=False,
                status="enabled",
                is_deleted=False,
            )
            db.add(legacy_water_purification_waste)
            db.flush()
        else:
            legacy_water_purification_waste.name = "水解除杂渣(铁粉法)"
            legacy_water_purification_waste.output_type = "solid_waste"
            legacy_water_purification_waste.is_product_form = False
            legacy_water_purification_waste.status = "enabled"
            legacy_water_purification_waste.is_deleted = False
            legacy_water_purification_waste.deleted_at = None
        existing_legacy_c3_output = db.scalar(
            select(ProcessNodeOutput)
            .where(
                ProcessNodeOutput.node_id == c3_node.id,
                ProcessNodeOutput.product_id == legacy_water_purification_waste.id,
                ProcessNodeOutput.output_type == "solid_waste",
            )
            .limit(1)
        )
        if existing_legacy_c3_output is None:
            db.add(
                ProcessNodeOutput(
                    node_id=c3_node.id,
                    product_id=legacy_water_purification_waste.id,
                    output_type="solid_waste",
                    output_per_ton=Decimal("0.220603"),
                    formula_type="fixed",
                    scale_param=json.dumps(
                        {
                            "source_sheet": "产出",
                            "node_output_role": "waste_treatment",
                            "binding_rule": "route_tree",
                            "node_name": "水解除杂",
                        },
                        ensure_ascii=False,
                    ),
                    unit="t/t-BM",
                    sort_order=99,
                    remark="节点三废产出",
                    is_deleted=False,
                )
            )
        oxide_product = db.scalar(select(ProcessProduct).where(ProcessProduct.code == "P39"))
        assert oxide_product is not None
        oxide_product.is_deleted = True
        oxide_route = db.scalar(select(ProcessRoute).where(ProcessRoute.code == "A1-B1-B2-B9"))
        assert oxide_route is not None
        oxide_route.is_deleted = True
        for relation in db.scalars(select(ProcessRouteNode).where(ProcessRouteNode.route_id == oxide_route.id)):
            relation.is_deleted = True
        for output in db.scalars(select(ProcessCalculationOutput).where(ProcessCalculationOutput.route_id == oxide_route.id)):
            output.is_deleted = True
        lithium_route = db.scalar(select(ProcessRoute).where(ProcessRoute.code == "A1-B1-B2-C1-D1-E1"))
        assert lithium_route is not None
        for relation in db.scalars(select(ProcessRouteNode).where(ProcessRouteNode.route_id == lithium_route.id)):
            relation.option_group_code = None
            relation.option_code = None
        for route in db.scalars(select(ProcessRoute).where(ProcessRoute.code.like("A1-B1-B2-B%"))):
            route.is_deleted = True
            for relation in db.scalars(select(ProcessRouteNode).where(ProcessRouteNode.route_id == route.id)):
                relation.is_deleted = True
            for output in db.scalars(select(ProcessCalculationOutput).where(ProcessCalculationOutput.route_id == route.id)):
                output.is_deleted = True
        db.commit()

        sync_mixed_acid_residue_route_defaults(db)
        db.commit()

        product_categories = {
            product.code: product.target_output_category
            for product in db.scalars(select(ProcessProduct).where(ProcessProduct.code.in_(("P1", "P11"))))
        }
        assert product_categories == {"P1": "li", "P11": "ni"}
        synced_oxide_product = db.scalar(select(ProcessProduct).where(ProcessProduct.code == "P39"))
        synced_oxide_route = db.scalar(select(ProcessRoute).where(ProcessRoute.code == "A1-B1-B2-B9"))
        assert synced_oxide_product is not None and synced_oxide_product.is_deleted is False
        assert synced_oxide_route is not None and synced_oxide_route.is_deleted is False
        synced_b1_outputs = db.execute(
            select(ProcessNodeOutput, ProcessProduct)
            .join(ProcessProduct, ProcessProduct.id == ProcessNodeOutput.product_id)
            .where(ProcessNodeOutput.node_id == b1_node.id, ProcessNodeOutput.is_deleted.is_(False))
        ).all()
        assert all(product.code != "P38" for _, product in synced_b1_outputs)
        assert (
            db.scalar(
                select(ProcessProduct).where(
                    ProcessProduct.code == "P38",
                    ProcessProduct.is_deleted.is_(False),
                )
            )
            is None
        )
        synced_b3_outputs = db.execute(
            select(ProcessNodeOutput, ProcessProduct)
            .join(ProcessProduct, ProcessProduct.id == ProcessNodeOutput.product_id)
            .where(ProcessNodeOutput.node_id == b3_node.id, ProcessNodeOutput.is_deleted.is_(False))
        ).all()
        assert {(product.code, output.output_type) for output, product in synced_b3_outputs} == {("P17", "product")}
        synced_c3_outputs = db.execute(
            select(ProcessNodeOutput, ProcessProduct)
            .join(ProcessProduct, ProcessProduct.id == ProcessNodeOutput.product_id)
            .where(ProcessNodeOutput.node_id == c3_node.id, ProcessNodeOutput.is_deleted.is_(False))
        ).all()
        assert {(product.code, output.output_type) for output, product in synced_c3_outputs} == {("P20", "solid_waste")}
        synced_legacy_water_purification_waste = db.scalar(select(ProcessProduct).where(ProcessProduct.code == "P19"))
        assert synced_legacy_water_purification_waste is not None
        assert synced_legacy_water_purification_waste.is_deleted is True
        route_nodes = list(
            db.scalars(
                select(ProcessRouteNode)
                .where(ProcessRouteNode.route_id == lithium_route.id, ProcessRouteNode.is_deleted.is_(False))
                .order_by(ProcessRouteNode.sort_order.asc())
            )
        )
        assert route_nodes[0].option_group_code == "root_leach_path"
        assert route_nodes[0].option_code == "mixed_acid_roasting"

        material = db.scalar(select(ProcessMaterial).where(ProcessMaterial.code == "M1"))
        assert material is not None
        result = ProcessCalculatorService(db).calculate(
            ProcessCalculatorRequest(
                materials=[{"material_id": material.id, "amount": "5000", "unit": "t"}],
                target_output_categories=["ni", "li"],
                region_code="americas",
                currency="USD",
                sort_criteria="npv",
                advanced_params={},
            )
        )
        assert result["no_route_reason"] is None
        assert result["matched_routes"]
    engine.dispose()


def test_startup_sync_soft_deletes_legacy_invalid_mixed_acid_routes() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with session_factory() as db:
        _seed_admin(db)
        seed_process_config_defaults(db)
        db.commit()

        material = db.scalar(select(ProcessMaterial).where(ProcessMaterial.code == "M1"))
        product = db.scalar(select(ProcessProduct).where(ProcessProduct.code == "P11"))
        nodes = {node.code: node for node in db.scalars(select(ProcessNode)).all()}
        assert material is not None and product is not None

        bad_routes = [
            ("A1-B2-A2-LEGACY", ["A1", "B2", "A2"]),
            ("A1-B2-MISSING-B1-LEGACY", ["A1", "B2"]),
            (
                "A1-B1-B2-B4-C3-D3-E4-F6-G5-H2-I2",
                ["A1", "B1", "B2", "B4", "C3", "D3", "E4", "F6", "G5", "H2", "I2"],
            ),
        ]
        for route_code, node_codes in bad_routes:
            route = ProcessRoute(
                code=route_code,
                name=route_code,
                input_material_id=material.id,
                final_product_id=product.id,
                status="enabled",
                version="V1",
                is_deleted=False,
            )
            db.add(route)
            db.flush()
            for index, node_code in enumerate(node_codes, start=1):
                db.add(ProcessRouteNode(route_id=route.id, node_id=nodes[node_code].id, sort_order=index, is_deleted=False))
            db.add(
                ProcessCalculationOutput(
                    route_id=route.id,
                    output_type="product",
                    product_id=product.id,
                    output_name=product.name,
                    formula_type="fixed",
                    recovery_rate="1",
                    unit="t/t-BM",
                    output_ratio="0.1",
                    is_deleted=False,
                )
            )
        db.commit()

        sync_mixed_acid_residue_route_defaults(db)
        db.commit()

        for route_code, _ in bad_routes:
            route = db.scalar(select(ProcessRoute).where(ProcessRoute.code == route_code))
            assert route is not None
            assert route.is_deleted is True
            assert db.scalars(
                select(ProcessRouteNode).where(ProcessRouteNode.route_id == route.id, ProcessRouteNode.is_deleted.is_(False))
            ).first() is None
            assert db.scalars(
                select(ProcessCalculationOutput).where(
                    ProcessCalculationOutput.route_id == route.id,
                    ProcessCalculationOutput.is_deleted.is_(False),
                )
            ).first() is None
    engine.dispose()


def test_route_generation_rules_match_updated_drawing() -> None:
    paths = build_product_route_paths()

    lithium_path = paths["精制硫酸锂溶液"][0]
    assert lithium_path[:3] == ["混酸焙烧", "混酸焙烧尾气处理", "水浸"]
    assert paths["氧化镍钴渣"] == [["混酸焙烧", "混酸焙烧尾气处理", "水浸", "氧化镍钴渣产品"]]
    assert paths["石墨渣产品"] == [
        ["酸浸", "石墨干燥"],
        ["混酸焙烧", "混酸焙烧尾气处理", "水浸", "水浸渣酸浸", "石墨干燥"],
    ]
    assert all("碳酸锰沉淀" in path and "锰溶液除杂" not in path for path in paths["粗制碳酸锰"])

    cobalt_paths = paths["电池级硫酸钴"]
    assert any("BC196共萃" in path for path in cobalt_paths)
    assert any("C272萃取钴" in path for path in cobalt_paths)
    assert any("P507萃取钴" in path for path in cobalt_paths)
    for route_paths in paths.values():
        for path in route_paths:
            for group in MUTUALLY_EXCLUSIVE_NAME_GROUPS:
                assert len(group.intersection(path)) <= 1, path
            if "混酸焙烧" in path:
                assert "混酸焙烧尾气处理" in path
                assert "水浸" in path
            if "混酸焙烧" in path and {"石墨干燥", "石墨渣废固", "除铜-铁粉法", "除铜-硫化法", "除铜-萃取法"}.intersection(path):
                assert "水浸渣酸浸" in path


def _seed_admin(db: Session) -> None:
    db.add(User(username="admin", password_hash="x", real_name="Admin", status="enabled"))
    db.commit()
