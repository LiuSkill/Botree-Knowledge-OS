from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.retrieval.schemas import Evidence, EvidenceAsset
from app.services.evidence_access_guard_service import EvidenceGuardResult
from app.services.retrieval_finalizer_service import RetrievalFinalizerService


def _evidence(chunk_id: int, retriever: str, *, metadata_only: bool = False) -> Evidence:
    return Evidence(
        score=0.9 - chunk_id / 1000,
        source_type="project",
        knowledge_base_id=1,
        project_id=1,
        document_id=10,
        chunk_id=chunk_id,
        drawing_no=None,
        file_name="source.pdf",
        page_number=1,
        content=f"evidence-{chunk_id}",
        retriever=retriever,
        metadata={"security_level": "public", "metadata_only": metadata_only},
    )


class _Guard:
    def __init__(self) -> None:
        self.calls = 0

    def filter_evidences(self, **kwargs: Any) -> EvidenceGuardResult:
        self.calls += 1
        return EvidenceGuardResult(evidences=list(kwargs["evidences"]))


class _Visual:
    def enrich(self, question: str, evidences: list[Evidence], query_features: dict[str, Any]) -> list[Evidence]:  # noqa: ARG002
        if evidences:
            evidences[0].assets.append(
                EvidenceAsset(
                    asset_id=1,
                    asset_type="page_preview",
                    url="/assets/1",
                    mime_type="image/png",
                    file_name="page.png",
                    file_size=100,
                    page_number=1,
                )
            )
        return evidences


def test_finalize_owns_merge_guard_rerank_filter_and_visual_enrichment() -> None:
    guard = _Guard()
    reranker = SimpleNamespace(last_details=[{"backend": "fake"}], last_runtime={"backend": "fake"})
    rerank_calls: list[list[int]] = []

    def rerank(candidates: list[Evidence], limit: int) -> list[Evidence]:
        rerank_calls.append([item.chunk_id for item in candidates])
        return list(candidates)[:limit]

    result = RetrievalFinalizerService(
        evidence_access_guard=guard,
        reranker=reranker,
        visual_evidence_service=_Visual(),
    ).finalize(
        query="show drawing",
        evidence_groups=[[_evidence(1, "milvus")], [_evidence(2, "keyword", metadata_only=True)]],
        merge_limit=20,
        rerank_candidate_limit=20,
        result_limit=10,
        chat_type="project_chat",
        project_id=1,
        user=SimpleNamespace(id=7),
        rerank=rerank,
        visual_context={"visual_evidence": True},
        visual_limit=8,
    )

    assert guard.calls == 1
    assert rerank_calls == [[1, 2]]
    assert [item.chunk_id for item in result.evidences] == [1]
    assert result.metadata_filtered_count == 1
    assert result.visual_asset_count == 1
    assert result.pre_rerank_guard["accepted"] == 2
