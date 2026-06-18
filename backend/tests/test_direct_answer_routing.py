"""Direct answer routing tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.langgraph.retrieval_graph import DIRECT_GREETING_ANSWER, RetrievalGraph  # noqa: E402
from app.services.qwen_orchestration_service import QwenOrchestrationService  # noqa: E402


def build_direct_graph() -> RetrievalGraph:
    graph = object.__new__(RetrievalGraph)
    graph.qwen = QwenOrchestrationService(db=None)  # type: ignore[arg-type]
    graph._compiled_graph = None
    return graph


def run_direct_question(question: str) -> dict:
    return build_direct_graph().run(question, "base_chat", "auto", None, SimpleNamespace(id=1))


def assert_direct_result(result: dict, intent: str, route: str) -> None:
    raw = result["raw"]
    assert raw["intent"] == intent
    assert raw["route"] == route
    assert raw["skip_retrieval"] is True
    assert result["used_retrievers"] == []
    assert result["evidences"] == []
    assert all(item["step"] not in {"查询拆解", "检索规划", "检索执行", "证据判断"} for item in result["agent_trace"])


def test_greeting_returns_fixed_answer_without_retrieval() -> None:
    result = run_direct_question("你好")

    assert result["answer"] == DIRECT_GREETING_ANSWER
    assert_direct_result(result, "greeting", "direct_greeting")


def test_identity_question_returns_botree_agent_answer_without_retrieval() -> None:
    result = run_direct_question("你是谁")

    assert result["answer"].startswith("我是博萃循环AI智能体")
    assert_direct_result(result, "greeting", "direct_greeting")


def test_simple_math_uses_general_qa_without_retrieval() -> None:
    result = run_direct_question("1+1=几")

    assert "2" in result["answer"]
    assert_direct_result(result, "pure_general_qa", "direct_general_qa")


def test_common_knowledge_uses_general_qa_without_retrieval() -> None:
    result = run_direct_question("水的沸点是多少")

    assert "100" in result["answer"]
    assert_direct_result(result, "pure_general_qa", "direct_general_qa")


def test_general_direct_answer_falls_back_when_model_returns_empty() -> None:
    class EmptyLLMService:
        def __init__(self, db: object) -> None:  # noqa: D107
            self.db = db

        def chat(
            self,
            messages: list[dict[str, Any]],  # noqa: ARG002
            model_type: str = "llm",  # noqa: ARG002
            max_tokens: int | None = None,  # noqa: ARG002
            disable_thinking: bool = False,  # noqa: ARG002
        ) -> str:
            return "  "

        def model_route(self, task: str, reason: str) -> dict[str, Any]:  # noqa: ARG002
            return {"task": task, "source": "database", "model_type": "answer_llm", "reason": reason}

    with patch("app.services.qwen_orchestration_service.LLMService", EmptyLLMService):
        result = run_direct_question("怎么学好物理化学")

    assert result["answer"]
    assert "未返回有效内容" in result["answer"]
    assert result["raw"]["model_routes"]["answer"]["source"] == "rules_fallback"
    assert_direct_result(result, "pure_general_qa", "direct_general_qa")


def test_project_overview_question_requires_rag() -> None:
    decision = QwenOrchestrationService(db=None).detect_route_decision("BMI 项目介绍", "base_chat", "auto")  # type: ignore[arg-type]

    assert decision["route"] == "project_rag"
    assert decision["skip_retrieval"] is False
    assert decision["intent"] in {"project_qa", "project_overview"}


def test_current_drawing_flow_question_requires_rag() -> None:
    decision = QwenOrchestrationService(db=None).detect_route_decision("这张图的流程是什么", "base_chat", "auto")  # type: ignore[arg-type]

    assert decision["route"] == "project_rag"
    assert decision["skip_retrieval"] is False
    assert decision["intent"] == "project_qa"
    assert decision["knowledge_scope"] == "project"


def assert_industry_rag_decision(question: str) -> None:
    decision = QwenOrchestrationService(db=None).detect_route_decision(question, "base_chat", "auto")  # type: ignore[arg-type]

    assert decision["intent"] == "industry_knowledge_qa"
    assert decision["route"] == "industry_knowledge_rag"
    assert decision["skip_retrieval"] is False
    assert decision["knowledge_scope"] == "industry"


def test_acid_leaching_basic_principle_requires_industry_knowledge_rag() -> None:
    decision = QwenOrchestrationService(db=None).detect_route_decision("酸浸的基本原理是什么", "base_chat", "auto")  # type: ignore[arg-type]

    assert decision["intent"] == "industry_knowledge_qa"
    assert decision["route"] == "industry_knowledge_rag"
    assert decision["skip_retrieval"] is False


def test_black_mass_question_requires_industry_knowledge_rag() -> None:
    assert_industry_rag_decision("黑粉是什么")


def test_pid_reading_question_requires_industry_knowledge_rag() -> None:
    assert_industry_rag_decision("P&ID 图怎么看")


def test_project_acid_leaching_flow_requires_rag() -> None:
    decision = QwenOrchestrationService(db=None).detect_route_decision("BMI 项目的酸浸流程是什么", "base_chat", "auto")  # type: ignore[arg-type]

    assert decision["route"] == "project_rag"
    assert decision["skip_retrieval"] is False
    assert decision["intent"] == "project_qa"
    assert decision["knowledge_scope"] == "project"


def test_current_drawing_material_flow_requires_project_rag() -> None:
    decision = QwenOrchestrationService(db=None).detect_route_decision("这张图里的物料流向是什么", "base_chat", "auto")  # type: ignore[arg-type]

    assert decision["route"] == "project_rag"
    assert decision["skip_retrieval"] is False
    assert decision["intent"] == "project_qa"
    assert decision["knowledge_scope"] == "project"


def test_greeting_with_project_question_still_requires_rag() -> None:
    decision = QwenOrchestrationService(db=None).detect_route_decision("你好，BMI 项目介绍", "base_chat", "auto")  # type: ignore[arg-type]

    assert decision["route"] == "project_rag"
    assert decision["skip_retrieval"] is False
    assert decision["intent"] in {"project_qa", "project_overview"}
