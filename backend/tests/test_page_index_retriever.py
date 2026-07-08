from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.retrieval.query_utils import extract_query_terms, score_text_relevance  # noqa: E402
from app.retrieval.retrievers.page_index_retriever import PageIndexRetriever  # noqa: E402


class FakeKeywordPolicy:
    def _terms(self, query: str) -> list[str]:
        return extract_query_terms(query)

    def _allowed_security_levels(self, user: object) -> list[str]:  # noqa: ARG002
        return ["public"]

    def _scope_allowed(
        self,
        knowledge_type: str,  # noqa: ARG002
        doc_project_id: int | None,  # noqa: ARG002
        knowledge_base_id: int,  # noqa: ARG002
        mode: str,  # noqa: ARG002
        project_id: int | None,  # noqa: ARG002
        user: object,  # noqa: ARG002
    ) -> bool:
        return True

    def _score(self, content: str, query: str, terms: list[str] | None = None) -> float:
        return score_text_relevance(content, query, terms or self._terms(query))

    def _source_type(self, knowledge_type: str, mode: str) -> str:  # noqa: ARG002
        return knowledge_type

    def _evidence_metadata(self, document: object, chunk: object, extra: dict | None = None) -> dict:
        return dict(extra or {})

    def _effective_mode(self, mode: str, project_id: int | None) -> str:  # noqa: ARG002
        return mode


class FakePageRepository:
    def __init__(self, diagram_rows: list[tuple[object, object, object]], general_rows: list[tuple[object, object, object]]) -> None:
        self.diagram_rows = diagram_rows
        self.general_rows = general_rows
        self.calls: list[dict[str, object]] = []

    def list_searchable_index_rows(self, security_levels: list[str], **kwargs: object) -> list[tuple[object, object, object]]:  # noqa: ARG002
        self.calls.append(dict(kwargs))
        if kwargs.get("diagram_only"):
            return list(self.diagram_rows)
        return list(self.general_rows)


class FakeProjectPolicy:
    def __init__(self, db: object) -> None:  # noqa: ARG002
        pass

    def project_chat_document_reject_reason(self, *args: object, **kwargs: object) -> None:
        return None

    def project_chat_chunk_reject_reason(self, *args: object, **kwargs: object) -> None:
        return None


def _row(
    *,
    page_index_id: int,
    document_id: int,
    chunk_id: int,
    file_name: str,
    chunk_content: str,
    drawing_no: str | None = None,
    document_type: str = "图纸",
    discipline: str = "工艺",
) -> tuple[object, object, object]:
    page_index = SimpleNamespace(
        id=page_index_id,
        document_id=document_id,
        chunk_id=chunk_id,
        page_no=1,
        drawing_no=drawing_no,
        index_text="TITLE BLOCK",
        security_level="public",
    )
    document = SimpleNamespace(
        id=document_id,
        knowledge_type="project",
        project_id=2,
        knowledge_base_id=1,
        file_name=file_name,
        document_name=file_name,
        drawing_name=file_name,
        document_type=document_type,
        discipline=discipline,
        drawing_no=drawing_no,
        security_level="public",
    )
    chunk = SimpleNamespace(
        id=chunk_id,
        document_id=document_id,
        version_no=1,
        content=chunk_content,
        chunk_status="active",
        knowledge_type="project",
        project_id=2,
        knowledge_base_id=1,
        security_level="public",
    )
    return page_index, document, chunk


def test_flow_query_prioritizes_real_diagram_before_index_and_list(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.retrieval.retrievers.page_index_retriever.ProjectDocumentPolicyService",
        FakeProjectPolicy,
    )
    retriever = object.__new__(PageIndexRetriever)
    retriever.db = None
    retriever.keyword_policy = FakeKeywordPolicy()
    retriever.page_repository = FakePageRepository(
        diagram_rows=[
            _row(
                page_index_id=1,
                document_id=101,
                chunk_id=1001,
                file_name="BCE2413-PS-30-002 Process Flow Diagram Index Rev.1B.pdf",
                chunk_content="index page",
                drawing_no="DWG.NO.",
            ),
            _row(
                page_index_id=2,
                document_id=102,
                chunk_id=1002,
                file_name="10-PS-0200-0000-001-R00_Process Flow Diagram.pdf",
                chunk_content="diagram page",
                drawing_no="10-PS-0200-0000-001",
            ),
        ],
        general_rows=[
            _row(
                page_index_id=3,
                document_id=103,
                chunk_id=1003,
                file_name="BCE2413-PS-40-005 Equipment List Rev.1B.pdf",
                chunk_content="Na2SO4 Evaporation&Crystallization",
                drawing_no="PS-40-005",
                document_type="设备资料",
                discipline="设备",
            )
        ],
    )

    results = retriever.search(
        query="Na2SO4蒸发流程",
        mode="project_chat",
        project_id=2,
        user=SimpleNamespace(id=1),
        limit=3,
    )

    assert results
    assert results[0].file_name == "10-PS-0200-0000-001-R00_Process Flow Diagram.pdf"
    assert results[0].metadata["prefer_diagram_documents"] is True
    assert retriever.page_repository.calls[0]["diagram_only"] is True
    assert retriever.page_repository.calls[0]["match_document_metadata"] is True


def test_structured_list_query_keeps_multiple_chunks_from_same_page(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.retrieval.retrievers.page_index_retriever.ProjectDocumentPolicyService",
        FakeProjectPolicy,
    )
    retriever = object.__new__(PageIndexRetriever)
    retriever.db = None
    retriever.keyword_policy = FakeKeywordPolicy()
    retriever.page_repository = FakePageRepository(
        diagram_rows=[],
        general_rows=[
            _row(
                page_index_id=10,
                document_id=308,
                chunk_id=51193,
                file_name="BCE2413-PS-40-007 Product List_Rev.1B.pdf",
                chunk_content="| No. | Product Name | Product Remarks |\n| 1 | Li2CO3 | / |",
            ),
            _row(
                page_index_id=11,
                document_id=308,
                chunk_id=51194,
                file_name="BCE2413-PS-40-007 Product List_Rev.1B.pdf",
                chunk_content="| 2 | Na2SO4 | / |",
            ),
            _row(
                page_index_id=12,
                document_id=308,
                chunk_id=51195,
                file_name="BCE2413-PS-40-007 Product List_Rev.1B.pdf",
                chunk_content="| 3 | Shell | / |",
            ),
        ],
    )

    results = retriever.search(
        query="该项目的最终产品有哪些",
        mode="project_chat",
        project_id=2,
        user=SimpleNamespace(id=1),
        limit=5,
    )

    assert [item.chunk_id for item in results[:3]] == [51193, 51194, 51195]
    assert retriever.page_repository.calls[0]["match_document_metadata"] is True
    assert "Product List" in retriever.page_repository.calls[0]["query_terms"]
