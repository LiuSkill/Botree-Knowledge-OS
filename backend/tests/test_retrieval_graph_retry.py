"""Retrieval graph retry tests."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.langgraph.retrieval_graph import RetrievalGraph  # noqa: E402
from app.retrieval.schemas import Evidence  # noqa: E402


def make_evidence(chunk_id: int, retriever: str = "page_index") -> Evidence:
    return Evidence(
        score=0.91,
        source_type="project",
        knowledge_base_id=1,
        project_id=1,
        document_id=11,
        chunk_id=chunk_id,
        drawing_no="10-PS-0101-3002-003",
        file_name="pid.pdf",
        page_number=2,
        content="补充证据显示流程起点、终点和主要设备。",
        retriever=retriever,
    )


class FakeRouter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def available_retrievers(self) -> list[str]:
        return ["page_index", "ripgrep", "milvus"]

    def execute_planned(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        retriever = kwargs["retriever_names"][0]
        return {
            "mode": kwargs["mode"],
            "query_scope": "项目资料",
            "used_retrievers": [retriever],
            "executed_retrievers": [retriever],
            "skipped_retrievers": [],
            "skip_reasons": {},
            "fallback_ladder": [kwargs["retriever_names"]],
            "fallback_used": [],
            "fallback_trigger_reason": [],
            "evidences": [make_evidence(200 + len(self.calls), retriever)],
            "retriever_hits": {retriever: 1},
            "retriever_elapsed_ms": {retriever: 3},
            "retriever_top_scores": {retriever: 0.91},
        }


class FakeReranker:
    def __init__(self) -> None:
        self.last_details: list[dict[str, Any]] = []

    def rerank(self, query: str, evidences: list[Evidence], limit: int) -> list[Evidence]:  # noqa: ARG002
        return sorted(evidences, key=lambda item: item.score, reverse=True)[:limit]


class FakeVisualEvidenceService:
    def enrich(
        self,
        question: str,  # noqa: ARG002
        evidences: list[Evidence],
        query_features: dict[str, Any],  # noqa: ARG002
    ) -> list[Evidence]:
        return evidences


class FakeQwen:
    def __init__(self) -> None:
        self.calls = 0
        self.model_routes = {"evidence_judge": {"task": "evidence_judge", "source": "fake"}}

    def judge_evidence(
        self,
        question: str,  # noqa: ARG002
        evidences: list[Evidence],  # noqa: ARG002
        context: dict[str, Any],  # noqa: ARG002
    ) -> dict[str, Any]:
        self.calls += 1
        return {"enough": True, "reason": "补充证据后足够", "suggested_retrievers": [], "suggested_queries": []}


def build_graph() -> RetrievalGraph:
    graph = object.__new__(RetrievalGraph)
    graph.retrieval_router = FakeRouter()
    graph.reranker = FakeReranker()
    graph.visual_evidence_service = FakeVisualEvidenceService()
    graph.qwen = FakeQwen()
    return graph


def base_state() -> dict[str, Any]:
    return {
        "question": "Raw Material & Chemical Feeding 全流程是什么？",
        "chat_type": "project_chat",
        "mode": "project_chat",
        "project_id": 1,
        "user": None,
        "intent": "project_qa",
        "sub_queries": ["Raw Material & Chemical Feeding 全流程"],
        "query_profile": {"query_type": "process_flow", "answer_shape": "process_steps"},
        "query_features": {},
        "evidences": [make_evidence(101, "milvus")],
        "evidence_judgement": {
            "enough": False,
            "reason": "缺少终点",
            "suggested_retrievers": ["page_index", "unknown"],
            "suggested_queries": ["Raw Material & Chemical Feeding 终点 主要设备"],
        },
        "used_retrievers": ["milvus"],
        "executed_retrievers": ["milvus"],
        "skipped_retrievers": [],
        "skip_reasons": {},
        "retriever_hits": {"milvus": 1},
        "retriever_elapsed_ms": {"milvus": 2},
        "retriever_top_scores": {"milvus": 0.8},
        "model_routes": {},
        "trace": [],
        "raw": {"run_id": "test-run", "active_trace_display_key": "retry_retrieval"},
    }


def test_retry_retrieval_runs_at_most_once_and_filters_unknown_retriever() -> None:
    graph = build_graph()
    state = graph._retry_retrieval_node(base_state())  # noqa: SLF001

    assert state["raw"]["retry_count"] == 1
    assert state["raw"]["retry_retrievers"] == ["page_index"]
    assert state["raw"]["retry_query_count"] == 1
    assert state["evidence_judgement"]["enough"] is True
    assert graph.retrieval_router.calls[0]["retriever_names"] == ["page_index"]
    assert graph.qwen.calls == 1

    state["raw"]["active_trace_display_key"] = "retry_retrieval"
    state = graph._retry_retrieval_node(state)  # noqa: SLF001

    assert state["raw"]["retry_count"] == 1
    assert len(graph.retrieval_router.calls) == 1
    assert graph.qwen.calls == 1

