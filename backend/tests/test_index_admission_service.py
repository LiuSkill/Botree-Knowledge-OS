from types import SimpleNamespace

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
    asset = SimpleNamespace(page_id=10, block_id=20, status="ready")

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


def test_unknown_ocr_quality_is_not_promoted_to_text_index() -> None:
    page = SimpleNamespace(id=10, page_no=1, clean_content="OCR candidate text", page_text="", source_hash="hash")

    text_page_numbers = IndexAdmissionService().apply_records([page], [], [], parser_name="mineru")

    assert text_page_numbers == set()
    assert page.index_admission_status == "metadata_only"
    assert "quality_metrics_missing" in page.index_admission_reason_json


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
