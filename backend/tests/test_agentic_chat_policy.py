import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.langgraph.retrieval_graph import (
    BASE_GENERAL_CONFIRM_ANSWER,
    GENERAL_ANSWER_PREFIX,
    PRESET_GREETING_ANSWER,
    PRESET_IDENTITY_ANSWER,
    RetrievalGraph,
)
from app.retrieval.schemas import Evidence
from app.services.chat_service import AWAITING_GENERAL_CONFIRM, ChatService


class _Plan:
    query_features = {}
    metadata = {}
    strategy = "test"
    rule_id = "test"
    confidence = 1.0
    qwen_used = False

    def to_dict(self):
        return {
            "selected_retrievers": ["page_index"],
            "fallback_retrievers": [],
            "fallback_ladder": [["page_index"]],
            "skipped_retrievers": [],
            "skip_reasons": {},
            "metadata": {},
            "weights": {},
        }


def _evidence(
    content: str = "项目资料正文显示：黑粉经给料系统进入浸出槽，再通过泵输送至过滤单元，包含上游和下游设备关系。",
    *,
    source_type: str = "project",
    project_id: int | None = 1,
) -> Evidence:
    return Evidence(
        score=0.95,
        source_type=source_type,
        knowledge_base_id=1,
        project_id=project_id,
        document_id=1,
        chunk_id=1,
        drawing_no=None,
        file_name="source.pdf",
        page_number=1,
        content=content,
        retriever="milvus",
    )


def _graph(monkeypatch, evidences=None, enough=True):
    graph = RetrievalGraph(None)
    graph._compiled_graph = None
    graph.retrieval_router = SimpleNamespace(
        available_retrievers=lambda: ["milvus", "keyword", "page_index"],
        execute_planned=lambda **kwargs: {
            "evidences": list(evidences or []),
            "used_retrievers": kwargs["retriever_names"],
            "executed_retrievers": kwargs["retriever_names"],
            "skipped_retrievers": [],
            "fallback_used": [],
            "fallback_trigger_reason": [],
            "query_scope": "项目知识库" if kwargs["chat_type"] == "project_chat" else "基础知识库",
            "mode": kwargs["mode"],
            "retriever_hits": {name: len(evidences or []) for name in kwargs["retriever_names"]},
            "retriever_elapsed_ms": {name: 1 for name in kwargs["retriever_names"]},
            "retriever_top_scores": {name: 0.95 for name in kwargs["retriever_names"]},
            "skip_reasons": {},
        },
    )
    graph.planner = SimpleNamespace(plan=lambda **kwargs: _Plan())
    graph.reranker = SimpleNamespace(
        last_details=[{"model": "real"}],
        last_runtime={"backend": "real"},
        rerank=lambda query, items, limit, **kwargs: list(items)[:limit],
    )
    graph.visual_evidence_service = SimpleNamespace(enrich=lambda question, items, features: items)
    graph.qwen.judge_evidence = lambda *args, **kwargs: {"enough": enough, "reason": "ok" if enough else "not enough"}
    graph.answer_generator.generate = lambda question, items, query_profile=None: "基于知识库回答"
    graph.answer_generator._partial_answer_with_llm = lambda *args, **kwargs: "受限部分回答"  # noqa: SLF001
    graph.answer_generator._general_answer = lambda *args, **kwargs: "通用回答"  # noqa: SLF001
    graph.answer_generator.last_model_route = {"source": "test"}
    return graph


def test_project_chat_greeting_uses_preset(monkeypatch):
    result = _graph(monkeypatch).run("你好", "project_chat", "auto", 1, SimpleNamespace(id=1))
    assert result["answer"] == PRESET_GREETING_ANSWER
    assert result["answer_type"] == "preset"
    assert result["raw"]["direct_llm_used"] is False


def test_project_chat_identity_uses_preset(monkeypatch):
    result = _graph(monkeypatch).run("你是谁", "project_chat", "auto", 1, SimpleNamespace(id=1))
    assert result["answer"] == PRESET_IDENTITY_ANSWER
    assert result["answer_type"] == "preset"


def test_project_chat_obvious_common_knowledge_uses_project_kb_policy(monkeypatch):
    result = _graph(monkeypatch).run("1+1 等于几", "project_chat", "auto", 1, SimpleNamespace(id=1))
    assert "无法基于项目资料回答" in result["answer"]
    assert result["answer_type"] == "refusal"
    assert result["answer_policy"] == "STRICT_KB"
    assert result["evidence_status"] == "EMPTY"
    assert result["raw"]["direct_llm_used"] is False
    assert result["raw"]["answer_policy_decision"]["action"] == "refusal"
    assert result["evidences"] == []


def test_project_chat_kb_answer_requires_sources(monkeypatch):
    result = _graph(monkeypatch, [_evidence()], enough=True).run("项目资料中的设备参数是什么", "project_chat", "auto", 1, SimpleNamespace(id=1))
    assert result["answer_type"] == "normal_answer"
    assert result["evidence_status"] == "ENOUGH"
    assert result["evidences"]
    assert "milvus" in set(result["used_retrievers"])
    assert result["raw"]["answer_top_k"] == 10
    assert result["raw"]["reranker_used"] is True


def test_project_chat_without_evidence_refuses(monkeypatch):
    result = _graph(monkeypatch, [], enough=False).run("项目资料中不存在的问题", "project_chat", "auto", 1, SimpleNamespace(id=1))
    assert "无法基于项目资料回答" in result["answer"]
    assert result["answer_type"] == "refusal"
    assert result["evidence_status"] == "EMPTY"
    assert result["raw"]["direct_llm_used"] is False


def test_project_chat_weak_only_evidence_returns_limited_answer(monkeypatch):
    weak_evidence = _evidence("TITLE\nRaw Material & Chemical Feeding\nP&ID")
    result = _graph(monkeypatch, [weak_evidence], enough=False).run(
        "本项目的黑粉进料流程介绍",
        "project_chat",
        "auto",
        1,
        SimpleNamespace(id=1),
    )

    assert result["answer_type"] == "limited_answer"
    assert result["evidence_status"] == "WEAK_ONLY"
    assert result["answer"]
    assert "标题、图名或弱证据" in result["answer"]
    assert result["evidences"]


def test_project_chat_partial_evidence_returns_partial_answer(monkeypatch):
    partial_evidence = _evidence("项目资料正文显示：黑粉经给料系统进入浸出槽，再通过泵输送至后续过滤单元。")
    result = _graph(monkeypatch, [partial_evidence], enough=False).run(
        "本项目的黑粉进料流程介绍",
        "project_chat",
        "auto",
        1,
        SimpleNamespace(id=1),
    )

    assert result["answer_type"] == "partial_answer_with_llm"
    assert result["evidence_status"] == "PARTIAL"
    assert result["answer"] == "受限部分回答"


def test_project_chat_unauthorized_only_refuses(monkeypatch):
    graph = _graph(monkeypatch, [], enough=False)
    original_execute = graph.retrieval_router.execute_planned
    graph.retrieval_router.execute_planned = lambda **kwargs: {
        **original_execute(**kwargs),
        "skip_reasons": {"milvus": "未授权项目资料"},
    }
    result = graph.run("未授权项目资料中的参数是什么", "project_chat", "auto", 1, SimpleNamespace(id=1))
    assert result["answer_type"] == "refusal"
    assert result["evidence_status"] == "EMPTY"


def test_base_chat_greeting_uses_preset(monkeypatch):
    result = _graph(monkeypatch).run("你好", "base_chat", "auto", None, SimpleNamespace(id=1))
    assert result["answer"] == PRESET_GREETING_ANSWER
    assert result["answer_type"] == "preset"


def test_base_chat_water_formula_direct(monkeypatch):
    result = _graph(monkeypatch).run("水的化学式是什么", "base_chat", "auto", None, SimpleNamespace(id=1))
    assert result["answer_type"] == "general_llm"
    assert "H2O" in result["answer"]


def test_base_chat_kb_hit_answers_with_sources(monkeypatch):
    result = _graph(
        monkeypatch,
        [_evidence("基础知识库正文显示：黑粉进料量为 2000 TPA，单位为 t/a，资料可支持回答。", source_type="base", project_id=None)],
        enough=True,
    ).run(
        "知识库命中问题",
        "base_chat",
        "auto",
        None,
        SimpleNamespace(id=1),
    )
    assert result["answer_type"] == "normal_answer"
    assert result["evidences"]


def test_base_chat_no_evidence_asks_for_general_confirm(monkeypatch):
    result = _graph(monkeypatch, [], enough=False).run("知识库无资料问题", "base_chat", "auto", None, SimpleNamespace(id=1))
    assert result["answer"] == BASE_GENERAL_CONFIRM_ANSWER
    assert result["answer_type"] == "ask_general_confirm"
    assert result["need_user_confirm"] is True


def test_industry_question_is_not_obvious_common_knowledge(monkeypatch):
    result = _graph(monkeypatch, [], enough=False).run("酸浸原理是什么", "base_chat", "auto", None, SimpleNamespace(id=1))
    assert result["answer_type"] == "ask_general_confirm"
    assert result["raw"]["direct_llm_used"] is False


def test_base_chat_pending_confirm_and_reject(monkeypatch):
    service = ChatService.__new__(ChatService)
    service.db = None
    service.repository = SimpleNamespace(update_session=lambda session: None)
    service._persist_agent_result = lambda payload, user, session, agent_result: agent_result
    monkeypatch.setattr("app.services.chat_service.QwenOrchestrationService", lambda db: SimpleNamespace(answer_general_question=lambda question: "通用答案"))

    session = SimpleNamespace(
        id=1,
        conversation_state=AWAITING_GENERAL_CONFIRM,
        pending_chat_type="base_chat",
        pending_general_question="原始问题",
    )
    payload = SimpleNamespace(message="可以", chat_type="base_chat", mode="auto")
    result = service._try_handle_general_confirmation(payload, SimpleNamespace(id=1), session)
    assert result["answer"].startswith(GENERAL_ANSWER_PREFIX)
    assert result["raw"]["direct_llm_used"] is True
    assert session.conversation_state == "NORMAL"

    session.conversation_state = AWAITING_GENERAL_CONFIRM
    session.pending_chat_type = "base_chat"
    session.pending_general_question = "原始问题"
    payload.message = "不用"
    result = service._try_handle_general_confirmation(payload, SimpleNamespace(id=1), session)
    assert result["answer_type"] == "cancelled"
    assert result["raw"]["refused"] is True
    assert session.conversation_state == "NORMAL"


def test_invalid_query_short_circuits_without_heavy_nodes(monkeypatch):
    result = _graph(monkeypatch).run("哈哈哈", "project_chat", "auto", 1, SimpleNamespace(id=1))
    assert result["answer_type"] == "clarify"
    assert result["evidence_status"] == "INVALID_QUERY"
    steps = [item["implementation"] for item in result["agent_trace"]]
    assert "planner" not in steps
    assert "router+reranker" not in steps
    assert result["used_retrievers"] == []


def test_base_chat_pending_new_question_clears_pending(monkeypatch):
    service = ChatService.__new__(ChatService)
    service.db = None
    service.repository = SimpleNamespace(update_session=lambda session: None)
    service._persist_agent_result = lambda payload, user, session, agent_result: agent_result
    session = SimpleNamespace(
        id=1,
        conversation_state=AWAITING_GENERAL_CONFIRM,
        pending_chat_type="base_chat",
        pending_general_question="原始问题",
    )
    payload = SimpleNamespace(message="什么是黑粉", chat_type="base_chat", mode="auto")
    result = service._try_handle_general_confirmation(payload, SimpleNamespace(id=1), session)
    assert result is None
    assert session.conversation_state == "NORMAL"
    assert session.pending_general_question is None
