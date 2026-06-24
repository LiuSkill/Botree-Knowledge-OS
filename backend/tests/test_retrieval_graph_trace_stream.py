"""
Retrieval Graph Trace Stream Tests

负责：
1. 验证 LangGraph 预处理阶段会产出 running/success trace_delta。
2. 验证前端 Thinking 所需的展示文案能从状态中正确生成。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.langgraph.retrieval_graph import RetrievalGraph  # noqa: E402


def test_prepare_node_specs_include_understanding_and_policy_resolution() -> None:
    """QuestionUnderstanding 与 PolicyResolver 应位于 query_profile 和 planner 之间。"""

    graph = object.__new__(RetrievalGraph)
    keys = [key for key, _ in graph._prepare_node_specs()]  # type: ignore[attr-defined]

    assert keys.index("query_profile") < keys.index("question_understanding")
    assert keys.index("question_understanding") < keys.index("policy_resolution")
    assert keys.index("policy_resolution") < keys.index("planner")


def test_prepare_stream_emits_running_success_and_prepared_events() -> None:
    """
    单节点替身验证：
    - prepare_stream 会先输出 running trace_delta
    - 节点完成后用相同 sequence 输出 success trace_delta
    - 最后输出 prepared state
    """

    graph = object.__new__(RetrievalGraph)

    def fake_prepare_specs() -> list[tuple[str, Any]]:
        def intent_node(state: dict[str, Any]) -> dict[str, Any]:
            state["intent"] = "project_qa"
            state.setdefault("trace", []).append(
                {
                    "sequence": state["raw"]["active_trace_sequence"],
                    "step": "意图识别",
                    "implementation": "rule_intent",
                    "status": "success",
                    "elapsed_ms": 1,
                    "details": {},
                }
            )
            return state

        return [("intent", intent_node)]

    graph._prepare_node_specs = fake_prepare_specs  # type: ignore[method-assign]

    events = list(graph.prepare_stream("Raw Material & Chemical Feeding 全流程", "project_chat", "auto", 1, object()))

    assert [event_name for event_name, _ in events] == ["trace_delta", "trace_delta", "prepared"]
    running = events[0][1]
    success = events[1][1]

    assert running["sequence"] == success["sequence"] == 1
    assert running["status"] == "running"
    assert running["display_text"] == "正在识别问题类型..."
    assert success["status"] == "success"
    assert success["display_text"] == "已识别为：项目资料问答"
    assert events[2][1]["intent"] == "project_qa"


def test_trace_delta_summary_text_uses_hits_evidence_and_visual_counts() -> None:
    """验证检索命中、证据数、图片数会进入 Thinking 摘要文案。"""

    graph = object.__new__(RetrievalGraph)
    state: dict[str, Any] = {
        "question": "Raw Material & Chemical Feeding 全流程",
        "chat_type": "project_chat",
        "mode": "auto",
        "project_id": 1,
        "intent": "project_qa",
        "sub_queries": ["Raw Material & Chemical Feeding 全流程"],
        "planned_retrievers": ["milvus", "keyword"],
        "skipped_retrievers": ["graphrag", "page_index"],
        "retriever_hits": {"milvus": 5, "keyword": 5},
        "evidences": [{}, {}, {}, {}, {}],
        "evidence_judgement": {"enough": True},
        "evidence_evaluation": {
            "evidence_status": "ENOUGH",
            "weak_evidence_count": 0,
            "strong_evidence_count": 5,
        },
        "visual_asset_count": 5,
        "raw": {},
    }

    planner_text = graph._trace_success_text("planner", state, {})  # type: ignore[arg-type]
    retrieval_text = graph._trace_success_text("retrieval", state, {})  # type: ignore[arg-type]
    evidence_text = graph._trace_success_text("evidence_judge", state, {})  # type: ignore[arg-type]
    visual_text = graph._trace_success_text("visual_reading", state, {})  # type: ignore[arg-type]

    assert planner_text == "选择：语义检索 + 关键词检索\n跳过：图谱检索、页级检索"
    assert retrieval_text == "Milvus 命中 5 条\nKeyword 命中 5 条"
    assert evidence_text == "证据状态：ENOUGH，强证据 5 条，弱证据 0 条，合并后保留 5 条证据\n关联 5 张图纸图片"
    assert visual_text == "已输入 5 张图纸图片给视觉模型"


def test_query_profile_trace_translates_industry_answer_shape() -> None:
    """行业基础知识画像不应在 Thinking 中展示 raw code: general。"""

    graph = object.__new__(RetrievalGraph)
    state: dict[str, Any] = {
        "query_profile": {
            "query_type": "industry_knowledge_qa",
            "answer_shape": "general",
            "knowledge_scope": "industry",
        }
    }

    profile_text = graph._trace_success_text("query_profile", state, {})  # type: ignore[arg-type]

    assert profile_text == "已生成查询画像：行业基础知识问答 / 行业知识回答"


def test_question_understanding_and_policy_resolution_trace_text() -> None:
    """新增问题理解/策略解析节点应输出可读摘要。"""

    graph = object.__new__(RetrievalGraph)
    state: dict[str, Any] = {
        "question_understanding": {
            "task_type": "process_flow",
            "answer_shape": "process_steps",
            "query_rewrites": ["本项目的黑粉进料流程介绍", "Black Mass Feeding", "Raw Material Feeding"],
        },
        "policy_resolution": {
            "resolved_task_type": "process_flow",
            "answer_policy": "STRICT_KB",
            "knowledge_scope": "project",
            "conflict_detected": True,
        },
    }

    understanding_text = graph._trace_success_text("question_understanding", state, {})  # type: ignore[arg-type]
    policy_text = graph._trace_success_text("policy_resolution", state, {})  # type: ignore[arg-type]

    assert "process_flow / process_steps" in understanding_text
    assert "Black Mass Feeding" in understanding_text
    assert "process_flow / STRICT_KB / project" in policy_text
    assert "冲突：是" in policy_text


def test_industry_no_evidence_answer_basis_mentions_model_knowledge() -> None:
    """行业知识库无命中时，回答依据需说明使用模型通用知识。"""

    graph = object.__new__(RetrievalGraph)
    state: dict[str, Any] = {
        "chat_type": "base_chat",
        "query_profile": {"knowledge_scope": "industry", "query_type": "industry_knowledge_qa"},
        "evidences": [],
    }

    basis_text = graph._answer_basis_text(state)  # type: ignore[arg-type]

    assert basis_text == "未检索到行业知识库资料，基于模型通用知识回答"
