"""Graph index service tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.services.graph_index_service import ENTITY_TOKEN_MAX_LENGTH, GraphIndexService  # noqa: E402


def make_service() -> GraphIndexService:
    return object.__new__(GraphIndexService)


def make_document() -> SimpleNamespace:
    return SimpleNamespace(
        knowledge_base_id=1,
        project_id=2,
        id=3,
        version_no=1,
        drawing_no="20-PS-0302-3002-002",
    )


def make_chunk(content: str) -> SimpleNamespace:
    return SimpleNamespace(id=4, page_number=5, content=content)


def test_extract_entities_skips_overlong_ocr_code_token() -> None:
    service = make_service()
    long_ocr_token = "BD_" + "_".join(["H1B"] * 60)

    entities = service._extract_entities(  # type: ignore[arg-type]  # noqa: SLF001
        make_document(),
        make_chunk(f"{long_ocr_token} P-100 Pump normal_code A-101"),
    )

    names = {entity["entity_name"] for entity in entities}
    assert long_ocr_token not in names
    assert "P-100" in names
    assert all(len(entity["entity_name"]) <= ENTITY_TOKEN_MAX_LENGTH for entity in entities)
    assert all(
        entity["entity_code"] is None or len(entity["entity_code"]) <= ENTITY_TOKEN_MAX_LENGTH for entity in entities
    )


def test_entity_code_respects_database_length_limit() -> None:
    service = make_service()
    max_length_code = "A" * ENTITY_TOKEN_MAX_LENGTH
    overlong_code = "A" * (ENTITY_TOKEN_MAX_LENGTH + 1)

    assert service._entity_code(max_length_code, "code") == max_length_code  # noqa: SLF001
    assert service._entity_code(overlong_code, "code") is None  # noqa: SLF001
    assert service._entity_code("Pump", "term") is None  # noqa: SLF001
