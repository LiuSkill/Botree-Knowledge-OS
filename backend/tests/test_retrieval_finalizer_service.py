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


def test_process_flow_visual_query_keeps_explicit_flow_diagram_document() -> None:
    guard = _Guard()
    reranker = SimpleNamespace(last_details=[], last_runtime={})
    flow = _evidence(1, "visual")
    flow.document_id = 117
    flow.file_name = "10-PS-0200-0000-001_Process Flow Diagram_Rev1.pdf"
    flow.assets.append(
        EvidenceAsset(1, "block_image", "/assets/1", "image/jpeg", "flow.jpg", 100, 1)
    )
    loop = _evidence(2, "visual")
    loop.document_id = 100
    loop.file_name = "Typical Loop Diagram.pdf"
    loop.assets.append(
        EvidenceAsset(2, "block_image", "/assets/2", "image/jpeg", "loop.jpg", 100, 1)
    )
    comment = _evidence(3, "page_index")
    comment.document_id = 111
    comment.file_name = "Comments of PID.xlsx"

    result = RetrievalFinalizerService(
        evidence_access_guard=guard,
        reranker=reranker,
    ).finalize(
        query="black mass collection system flow diagram",
        evidence_groups=[[flow, loop, comment]],
        merge_limit=20,
        rerank_candidate_limit=20,
        result_limit=10,
        chat_type="project_chat",
        project_id=2,
        user=SimpleNamespace(id=7),
        rerank=lambda candidates, limit: list(candidates)[:limit],
        visual_context={
            "visual_evidence": True,
            "query_profile": {"query_type": "process_flow", "need_visual_asset": True},
        },
        visual_limit=8,
    )

    assert [(item.document_id, item.file_name) for item in result.evidences] == [
        (117, "10-PS-0200-0000-001_Process Flow Diagram_Rev1.pdf")
    ]


def test_visual_context_without_process_flow_does_not_filter_documents() -> None:
    guard = _Guard()
    reranker = SimpleNamespace(last_details=[], last_runtime={})
    flow = _evidence(1, "visual")
    flow.document_id = 117
    flow.file_name = "10-PS-0200-0000-001_Process Flow Diagram_Rev1.pdf"
    flow.assets.append(
        EvidenceAsset(1, "block_image", "/assets/1", "image/jpeg", "flow.jpg", 100, 1)
    )
    comment = _evidence(2, "page_index")
    comment.document_id = 111
    comment.file_name = "Comments of PID.xlsx"

    result = RetrievalFinalizerService(
        evidence_access_guard=guard,
        reranker=reranker,
    ).finalize(
        query="show related drawings",
        evidence_groups=[[flow, comment]],
        merge_limit=20,
        rerank_candidate_limit=20,
        result_limit=10,
        chat_type="project_chat",
        project_id=2,
        user=SimpleNamespace(id=7),
        rerank=lambda candidates, limit: list(candidates)[:limit],
        visual_context={"visual_evidence": True},
        visual_limit=8,
    )

    assert [(item.document_id, item.file_name) for item in result.evidences] == [
        (117, "10-PS-0200-0000-001_Process Flow Diagram_Rev1.pdf"),
        (111, "Comments of PID.xlsx"),
    ]


def test_process_flow_visual_hit_survives_rrf_and_rerank_top_cutoff() -> None:
    """流程图视觉命中即使 RRF 分低，也要进入最终视觉证据。"""

    guard = _Guard()
    reranker = SimpleNamespace(last_details=[], last_runtime={})
    visual_context = {
        "category": "flow_diagram",
        "priority_score": 442,
        "figure_title": "（2）实验流程",
        "source_file_name": "BMI黑粉两段浸出实验实验报告.docx",
    }
    flow = _evidence(9, "visual")
    flow.document_id = 6128
    flow.chunk_id = -52099
    flow.file_name = "BMI黑粉两段浸出实验实验报告.docx"
    flow.page_number = 2
    flow.content = "视觉证据：BMI黑粉两段浸出实验实验报告.docx 第2页 （2）实验流程"
    flow.metadata.update({"asset_id": 52099, "visual_context": visual_context})
    flow.assets.append(
        EvidenceAsset(
            asset_id=52099,
            asset_type="block_image",
            url="/assets/52099",
            mime_type="image/jpeg",
            file_name="page_0002_block_0003.jpg",
            file_size=22113,
            page_number=2,
            block_id=283802,
            metadata={"visual_context": visual_context},
        )
    )
    page = _evidence(1, "page_index")
    keyword = _evidence(1, "keyword")
    milvus = _evidence(1, "milvus")

    def score_desc_rerank(candidates: list[Evidence], limit: int) -> list[Evidence]:
        return sorted(candidates, key=lambda item: float(item.score), reverse=True)[:limit]

    result = RetrievalFinalizerService(
        evidence_access_guard=guard,
        reranker=reranker,
    ).finalize(
        query="BMI 项目黑粉两段浸出实验实验流程图",
        evidence_groups=[[flow], [page], [keyword], [milvus]],
        merge_limit=20,
        rerank_candidate_limit=20,
        result_limit=1,
        chat_type="project_chat",
        project_id=1,
        user=SimpleNamespace(id=7),
        rerank=score_desc_rerank,
        visual_context={
            "visual_evidence": True,
            "query_profile": {"query_type": "process_flow", "need_visual_asset": True},
        },
        visual_limit=1,
    )

    assert [(item.retriever, item.document_id, item.page_number) for item in result.evidences] == [
        ("visual", 6128, 2)
    ]
    assert [asset.asset_id for asset in result.evidences[0].assets] == [52099]
