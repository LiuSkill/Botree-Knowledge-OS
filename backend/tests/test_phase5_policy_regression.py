"""Phase 5 policy regression tests.

覆盖 QuestionUnderstanding、PolicyResolver、RetrievalPolicyMatrix、EvidenceStatus
和 AnswerPolicyGate 的端到端策略链路，避免证据不足时再次出现空回答。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.langgraph.retrieval_graph import RetrievalGraph  # noqa: E402
from app.retrieval.schemas import Evidence  # noqa: E402


ALL_RETRIEVERS = ["project_metadata", "milvus", "keyword", "page_index", "ripgrep", "graphrag"]


def _evidence(content: str, retriever: str, chunk_id: int = 1) -> Evidence:
    return Evidence(
        score=0.95,
        source_type="project",
        knowledge_base_id=1,
        project_id=1,
        document_id=10,
        chunk_id=chunk_id,
        drawing_no="PID-001" if "P&ID" in content or "图纸" in content else None,
        file_name="source.pdf",
        page_number=2,
        content=content,
        retriever=retriever,
    )


class FakeRouter:
    def available_retrievers(self) -> list[str]:
        return list(ALL_RETRIEVERS)

    def execute_planned(self, **kwargs: Any) -> dict[str, Any]:
        query = str(kwargs.get("query") or "")
        retriever_names = list(kwargs.get("retriever_names") or [])
        evidences: list[Evidence] = []
        if "不存在" not in query and "没有的专业问题" not in query and "在哪张图纸" not in query:
            for index, retriever in enumerate(retriever_names, start=1):
                evidence = self._evidence_for_query(query, retriever, index)
                if evidence is not None:
                    evidences.append(evidence)
        return {
            "evidences": evidences,
            "used_retrievers": retriever_names,
            "executed_retrievers": retriever_names,
            "skipped_retrievers": [],
            "fallback_used": [],
            "fallback_trigger_reason": [],
            "query_scope": "项目知识库" if kwargs.get("chat_type") == "project_chat" else "基础知识库",
            "mode": kwargs.get("mode"),
            "retriever_hits": {name: len(evidences) for name in retriever_names},
            "retriever_elapsed_ms": {name: 1 for name in retriever_names},
            "retriever_top_scores": {name: 0.95 if evidences else 0.0 for name in retriever_names},
            "skip_reasons": {},
        }

    def _evidence_for_query(self, query: str, retriever: str, chunk_id: int) -> Evidence | None:
        if "项目介绍" in query or "Project项目介绍" in query:
            return _evidence(
                "项目概况正文显示：本项目为 2 x 2000 TPA Battery Black Mass Recycling Project，包含建设内容、处理规模、产品方案和工艺范围。",
                retriever,
                chunk_id,
            )
        if "进料量" in query or "是多少" in query:
            return _evidence("参数表正文显示：黑粉进料量为 2000 TPA，单位为 t/a，适用于原料进料系统。", retriever, chunk_id)
        if any(token in query for token in ("黑粉进料流程", "Black Mass Feeding", "Raw Material Feeding", "Raw Material & Chemical Feeding")):
            return _evidence("TITLE\nRaw Material & Chemical Feeding\nP&ID", retriever, chunk_id)
        return None


class FakeReranker:
    last_details: list[dict[str, Any]] = [{"model": "fake"}]
    last_runtime: dict[str, Any] = {"backend": "fake"}

    def rerank(self, query: str, evidences: list[Evidence], limit: int, **_: Any) -> list[Evidence]:  # noqa: ARG002
        return list(evidences)[:limit]


class FakeVisualEvidenceService:
    def enrich(self, question: str, evidences: list[Evidence], query_features: dict[str, Any]) -> list[Evidence]:  # noqa: ARG002
        return evidences


def _build_graph() -> RetrievalGraph:
    graph = RetrievalGraph(None)
    graph._compiled_graph = None
    graph.retrieval_router = FakeRouter()
    graph.reranker = FakeReranker()
    graph.visual_evidence_service = FakeVisualEvidenceService()
    graph.answer_generator.generate = lambda question, items, query_profile=None: "基于项目资料生成的正常回答"
    graph.answer_generator.last_model_route = {"source": "fake"}
    graph.qwen.judge_evidence = _judge_evidence
    graph.qwen.model_routes["evidence_judge"] = {"task": "evidence_judge", "source": "fake"}
    return graph


def _judge_evidence(question: str, evidences: list[Evidence], context: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
    text = "\n".join(item.content for item in evidences)
    enough = "项目概况正文" in text or "黑粉进料量为 2000 TPA" in text
    return {
        "enough": enough,
        "reason": "fake enough" if enough else "fake not enough",
        "suggested_retrievers": [],
        "suggested_queries": [],
    }


def _run(question: str, chat_type: str = "project_chat") -> dict[str, Any]:
    project_id = 1 if chat_type == "project_chat" else None
    return _build_graph().run(question, chat_type, "auto", project_id, SimpleNamespace(id=7))


def _assert_required_log_fields(result: dict[str, Any]) -> None:
    raw = result["raw"]
    for key in (
        "question_understanding",
        "policy_resolution",
        "retrieval_plan",
        "evidence_evaluation",
        "answer_policy_decision",
    ):
        assert key in raw
        assert raw[key] not in (None, "")


def test_project_overview_policy_matrix_regression() -> None:
    result = _run("2 x 2000 TPA Battery Black Mass Recycling Project项目介绍")

    raw = result["raw"]
    plan = raw["retrieval_plan"]
    assert raw["resolved_task_type"] == "project_overview"
    assert raw["resolved_answer_shape"] == "project_summary"
    assert {"project_metadata", "milvus", "keyword"}.issubset(set(plan["selected_retrievers"]))
    assert not {"page_index", "ripgrep", "graphrag"} & set(plan["selected_retrievers"])
    _assert_required_log_fields(result)


def test_black_mass_feeding_process_flow_policy_regression() -> None:
    result = _run("本项目的黑粉进料流程介绍")

    raw = result["raw"]
    plan = raw["retrieval_plan"]
    needs = raw["question_understanding"]["retrieval_needs"]
    rewrites = set(raw["question_understanding"]["query_rewrites"])
    assert raw["resolved_task_type"] == "process_flow"
    assert raw["resolved_answer_shape"] == "process_steps"
    assert needs["page_level_retrieval"] is True
    assert needs["visual_evidence"] is True
    assert {"milvus", "keyword", "page_index"}.issubset(set(plan["selected_retrievers"]))
    assert {"Black Mass Feeding", "Raw Material Feeding", "Raw Material & Chemical Feeding"}.issubset(rewrites)
    assert result["answer"].strip()
    _assert_required_log_fields(result)


def test_parameter_lookup_policy_regression() -> None:
    result = _run("这个项目黑粉进料量是多少？")

    raw = result["raw"]
    selected = set(raw["retrieval_plan"]["selected_retrievers"])
    assert raw["resolved_task_type"] == "parameter_lookup"
    assert {"milvus", "keyword", "page_index"}.issubset(selected)
    _assert_required_log_fields(result)


def test_document_location_policy_regression() -> None:
    result = _run("黑粉进料流程在哪张图纸第几页？")

    raw = result["raw"]
    selected = set(raw["retrieval_plan"]["selected_retrievers"])
    exact_text_search = raw["question_understanding"]["retrieval_needs"]["exact_text_search"]
    assert raw["resolved_task_type"] == "document_location" or (
        raw["resolved_task_type"] == "process_flow" and exact_text_search is True
    )
    assert {"page_index", "ripgrep"}.issubset(selected)
    _assert_required_log_fields(result)


def test_base_chat_empty_evidence_asks_general_confirm() -> None:
    result = _run("某个知识库没有的专业问题", chat_type="base_chat")

    raw = result["raw"]
    assert result["answer_policy"] == "KB_FIRST"
    assert result["evidence_status"] == "EMPTY"
    assert raw["answer_policy_decision"]["action"] == "ask_general_confirm"
    _assert_required_log_fields(result)


def test_project_chat_empty_evidence_refuses_without_general_confirm() -> None:
    result = _run("项目资料中不存在的问题")

    raw = result["raw"]
    assert result["answer_policy"] == "STRICT_KB"
    assert result["evidence_status"] == "EMPTY"
    assert raw["answer_policy_decision"]["action"] == "refusal"
    assert raw["answer_policy_decision"]["action"] != "ask_general_confirm"
    assert result["answer"].strip()
    _assert_required_log_fields(result)
