from types import SimpleNamespace
import json

from app.services.index_admission_service import (
    AdmissionAssessment,
    IndexAdmissionService,
    IndexAdmissionStatus,
)


def test_visual_only_unit_enters_visual_index_without_text() -> None:
    result = IndexAdmissionService().assess(
        AdmissionAssessment(has_visual_asset=True, candidate_text="", source_traceable=True)
    )

    assert result.status is IndexAdmissionStatus.VISUAL_INDEXED
    assert result.required_indexes == ("visual",)


def test_high_aggregate_score_cannot_override_critical_structure_veto() -> None:
    result = IndexAdmissionService().assess(
        AdmissionAssessment(
            has_visual_asset=True,
            candidate_text="P-101 出口压力 1.2 MPa",
            ocr_confidence=0.99,
            valid_character_ratio=0.99,
            reading_order_score=0.99,
            terminology_score=0.99,
            source_traceable=True,
            critical_failures=("formula_integrity",),
        )
    )

    assert result.status is IndexAdmissionStatus.VISUAL_INDEXED
    assert result.required_indexes == ("visual",)
    assert "formula_integrity" in result.reasons


def test_untraceable_content_waits_for_manual_correction() -> None:
    result = IndexAdmissionService().assess(
        AdmissionAssessment(has_visual_asset=False, candidate_text="孤立识别文本", source_traceable=False)
    )

    assert result.status is IndexAdmissionStatus.WAITING_CORRECTION
    assert result.required_indexes == ()


def test_apply_records_persists_visual_only_admission_and_returns_no_text_page() -> None:
    page = SimpleNamespace(id=10, page_no=1, clean_content="", page_text="", source_hash="hash")
    block = SimpleNamespace(id=20, page_id=10, clean_text="", text="")
    asset = SimpleNamespace(
        page_id=10,
        block_id=20,
        status="ready",
        asset_type="block_image",
        file_name="page_0001_block_0001.png",
        metadata_json=json.dumps({"source_file_name": "drawing.pdf"}, ensure_ascii=False),
    )

    text_page_numbers = IndexAdmissionService().apply_records([page], [block], [asset])

    assert text_page_numbers == set()
    assert page.index_admission_status == "visual_indexed"
    assert block.index_admission_status == "visual_indexed"
    assert "no_reliable_text" in page.index_admission_reason_json


def test_apply_records_treats_null_page_and_block_text_as_empty() -> None:
    page = SimpleNamespace(id=10, page_no=1, clean_content=None, page_text=None, source_hash="hash")
    block = SimpleNamespace(id=20, page_id=10, clean_text=None, text=None)

    text_page_numbers = IndexAdmissionService().apply_records([page], [block], [])

    assert text_page_numbers == set()
    assert page.index_admission_status == "metadata_only"
    assert block.index_admission_status == "metadata_only"


def test_apply_records_prefers_empty_clean_text_over_raw_noise() -> None:
    page = SimpleNamespace(id=10, page_no=1, clean_content="", page_text="raw ocr noise", source_hash=None)

    text_page_numbers = IndexAdmissionService().apply_records([page], [], [], parser_name="mineru")

    assert text_page_numbers == set()
    assert page.index_admission_status == "metadata_only"
    assert "no_indexable_content" in page.index_admission_reason_json


def test_unknown_ocr_quality_is_not_promoted_to_text_index() -> None:
    page = SimpleNamespace(id=10, page_no=1, clean_content="OCR candidate text", page_text="", source_hash="hash")

    text_page_numbers = IndexAdmissionService().apply_records([page], [], [], parser_name="mineru")

    assert text_page_numbers == set()
    assert page.index_admission_status == "metadata_only"
    assert "quality_metrics_missing" in page.index_admission_reason_json


def test_converted_pdf_text_without_quality_is_promoted_to_text_index() -> None:
    page = SimpleNamespace(id=10, page_no=1, clean_content="Office converted report text", page_text="", source_hash="hash")

    text_page_numbers = IndexAdmissionService().apply_records(
        [page],
        [],
        [],
        parser_name="mineru",
        source_kind="converted_pdf",
    )

    assert text_page_numbers == {1}
    assert page.index_admission_status == "text_indexed"


def test_apply_records_only_admits_structured_visual_assets_and_rejects_noise_assets() -> None:
    page = SimpleNamespace(
        id=10,
        page_no=1,
        page_title="一次浸出工艺流程",
        clean_content="图1 一次浸出工艺流程图",
        page_text="",
        source_hash="hash",
    )
    caption_block = SimpleNamespace(
        id=19,
        page_id=10,
        block_index=1,
        block_type="text",
        clean_text="图1 一次浸出工艺流程图",
        text="图1 一次浸出工艺流程图",
        filter_status="kept",
        filter_reason=None,
        metadata_json=None,
    )
    flow_block = SimpleNamespace(
        id=20,
        page_id=10,
        block_index=2,
        block_type="image",
        clean_text="",
        text="",
        filter_status="kept",
        filter_reason=None,
        metadata_json=None,
    )
    logo_block = SimpleNamespace(
        id=21,
        page_id=10,
        block_index=3,
        block_type="image",
        clean_text="",
        text="",
        filter_status="filtered",
        filter_reason="signature_control_block",
        metadata_json=None,
    )
    flow_asset = SimpleNamespace(
        page_id=10,
        block_id=20,
        status="ready",
        asset_type="block_image",
        file_name="page_0001_block_0002.png",
        metadata_json=json.dumps({"source_file_name": "BMI项目黑粉一次浸出实验实验报告.docx"}, ensure_ascii=False),
    )
    logo_asset = SimpleNamespace(
        page_id=10,
        block_id=21,
        status="ready",
        asset_type="block_image",
        file_name="page_0001_block_0003.png",
        metadata_json=json.dumps({"source_file_name": "BMI项目黑粉一次浸出实验实验报告.docx"}, ensure_ascii=False),
    )

    text_page_numbers = IndexAdmissionService().apply_records(
        [page],
        [caption_block, flow_block, logo_block],
        [flow_asset, logo_asset],
    )

    flow_visual = json.loads(flow_asset.metadata_json)["visual_admission"]
    logo_visual = json.loads(logo_asset.metadata_json)["visual_admission"]
    assert text_page_numbers == set()
    assert page.index_admission_status == "visual_indexed"
    assert flow_block.index_admission_status == "visual_indexed"
    assert logo_block.index_admission_status == "metadata_only"
    assert flow_visual["status"] == "accepted"
    assert flow_visual["category"] == "flow_diagram"
    assert flow_visual["figure_title"] == "图1 一次浸出工艺流程图"
    assert "BMI项目黑粉一次浸出实验实验报告.docx" in flow_visual["context_text"]
    assert logo_visual["status"] == "rejected"
    assert "excluded_filter_reason:signature_control_block" in logo_visual["reasons"]


def test_original_pdf_text_without_quality_uses_inferred_metrics() -> None:
    page = SimpleNamespace(
        id=10,
        page_no=1,
        clean_content=(
            "前言\n"
            "本文件规定了车用动力电池回收利用再生利用过程中的材料回收要求。\n"
            "本文件适用于退役锂离子动力电池材料回收、污染控制与质量管理。"
        ),
        page_text="",
        source_hash="hash",
        cleaning_metadata_json=json.dumps(
            {
                "removed_line_count": 2,
                "removed_block_count": 2,
                "repeated_edge_noise_applied": True,
            },
            ensure_ascii=False,
        ),
    )

    text_page_numbers = IndexAdmissionService().apply_records(
        [page],
        [],
        [],
        parser_name="mineru",
        source_kind="original",
    )

    metadata = json.loads(page.cleaning_metadata_json)
    assert text_page_numbers == {1}
    assert page.index_admission_status == "text_indexed"
    assert metadata["quality_inference"]["source"] == "mineru_original_pdf_heuristic"
    assert metadata["quality"]["ocr_confidence"] >= 0.7
    assert "quality_metrics_missing" not in page.index_admission_reason_json


def test_original_pdf_noise_stays_out_of_text_index_even_after_inference() -> None:
    page = SimpleNamespace(
        id=10,
        page_no=1,
        clean_content="P-101 / A-01\n<><><> ----\nA1 | B2 | C3\nLCP-01 / T-09",
        page_text="",
        source_hash="hash",
        cleaning_metadata_json=json.dumps({"removed_line_count": 0, "removed_block_count": 0}, ensure_ascii=False),
    )

    text_page_numbers = IndexAdmissionService().apply_records(
        [page],
        [],
        [],
        parser_name="mineru",
        source_kind="original",
    )

    metadata = json.loads(page.cleaning_metadata_json)
    assert text_page_numbers == set()
    assert page.index_admission_status == "metadata_only"
    assert metadata["quality"]["reading_order_score"] < IndexAdmissionService.TEXT_QUALITY_THRESHOLD
    assert "text_quality_below_threshold" in page.index_admission_reason_json


def test_empty_untraceable_page_is_metadata_only() -> None:
    result = IndexAdmissionService().assess(
        AdmissionAssessment(has_visual_asset=False, candidate_text="", source_traceable=False)
    )

    assert result.status is IndexAdmissionStatus.METADATA_ONLY
    assert result.required_indexes == ("metadata",)
    assert "no_indexable_content" in result.reasons


def test_explicit_quality_metadata_controls_text_admission() -> None:
    page = SimpleNamespace(id=10, page_no=1, clean_content="qualified OCR candidate", page_text="", source_hash="hash")
    parsed_page = {
        "page_number": 1,
        "quality": {
            "ocr_confidence": 0.95,
            "valid_character_ratio": 0.96,
            "reading_order_score": 0.91,
            "terminology_score": 0.9,
        },
    }

    text_page_numbers = IndexAdmissionService().apply_records(
        [page], [], [], parsed_pages=[parsed_page], parser_name="mineru"
    )

    assert text_page_numbers == {1}
    assert page.index_admission_status == "text_indexed"
