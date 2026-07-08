from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.retrieval.retrievers.ripgrep_retriever import RipgrepRetriever  # noqa: E402


def test_ripgrep_short_circuits_when_binary_missing() -> None:
    retriever = object.__new__(RipgrepRetriever)
    retriever.db = None
    retriever.settings = SimpleNamespace(ripgrep_binary="rg")
    retriever._binary_available = None

    calls = {"allowed": 0}

    def fail_if_called(*args: object, **kwargs: object) -> list[object]:
        calls["allowed"] += 1
        raise AssertionError("binary missing should short-circuit before loading searchable indexes")

    retriever._allowed_page_indexes = fail_if_called  # type: ignore[method-assign]

    with patch("app.retrieval.retrievers.ripgrep_retriever.shutil.which", return_value=None):
        result = retriever.search("Na2SO4蒸发流程", "project_chat", 2, user=SimpleNamespace(), limit=5)

    assert result == []
    assert calls["allowed"] == 0


class FakeKeywordPolicy:
    def _source_type(self, knowledge_type: str, mode: str) -> str:  # noqa: ARG002
        return knowledge_type

    def _evidence_metadata(self, document: object, chunk: object, extra: dict | None = None) -> dict:
        return dict(extra or {})


class FakeProjectPolicy:
    def __init__(self, db: object) -> None:  # noqa: ARG002
        pass

    def project_chat_document_reject_reason(self, *args: object, **kwargs: object) -> None:
        return None

    def project_chat_chunk_reject_reason(self, *args: object, **kwargs: object) -> None:
        return None


def _rg_row(path: Path, chunk_id: int, chunk_content: str) -> tuple[object, object, object]:
    page_index = SimpleNamespace(
        id=chunk_id,
        chunk_id=chunk_id,
        text_mirror_path=str(path),
        page_no=3,
        drawing_no=None,
        security_level="public",
    )
    document = SimpleNamespace(
        id=308,
        knowledge_type="project",
        knowledge_base_id=1,
        project_id=2,
        file_name="BCE2413-PS-40-007 Product List_Rev.1B.pdf",
        document_name="BCE2413-PS-40-007 Product List_Rev.1B.pdf",
        drawing_name=None,
        drawing_no=None,
        document_type="PDF",
        security_level="public",
    )
    chunk = SimpleNamespace(
        id=chunk_id,
        content=chunk_content,
        chunk_status="active",
        security_level="public",
    )
    return page_index, document, chunk


def test_ripgrep_maps_same_page_mirror_back_to_multiple_chunks(tmp_path, monkeypatch) -> None:
    mirror_path = tmp_path / "page_3.md"
    retriever = object.__new__(RipgrepRetriever)
    retriever.db = None
    retriever.settings = SimpleNamespace(ripgrep_binary="rg", ripgrep_timeout_ms=1000)
    retriever.keyword_policy = FakeKeywordPolicy()
    retriever._binary_available = True
    retriever._allowed_page_indexes = lambda *args, **kwargs: [  # type: ignore[method-assign]
        _rg_row(mirror_path, 51193, "| No. | Product Name | Product Remarks |\n| 1 | Li2CO3 | / |"),
        _rg_row(mirror_path, 51194, "| 2 | Na2SO4 | / |"),
        _rg_row(mirror_path, 51195, "| 3 | Shell | / |"),
    ]
    monkeypatch.setattr(
        "app.retrieval.retrievers.ripgrep_retriever.ProjectDocumentPolicyService",
        FakeProjectPolicy,
    )

    rg_output = "\n".join(
        [
            json.dumps(
                {
                    "type": "match",
                    "data": {
                        "path": {"text": str(mirror_path)},
                        "lines": {"text": "| No. | Product Name | Product Remarks |"},
                    },
                }
            )
        ]
    )

    with patch(
        "app.retrieval.retrievers.ripgrep_retriever.subprocess.run",
        return_value=SimpleNamespace(stdout=rg_output),
    ):
        results = retriever.search("该项目的最终产品有哪些", "project_chat", 2, user=SimpleNamespace(id=1), limit=5)

    assert [item.chunk_id for item in results[:3]] == [51193, 51194, 51195]
