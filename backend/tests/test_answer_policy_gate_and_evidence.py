"""Answer policy gate and evidence evaluation tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.agent.answer_generator import AnswerGenerator  # noqa: E402
from app.langgraph.retrieval_graph import RetrievalGraph  # noqa: E402
from app.retrieval.schemas import Evidence, EvidenceAsset  # noqa: E402
from app.services.answer_policy_gate_service import AnswerPolicyGateService  # noqa: E402
from app.services.evidence_access_guard_service import EvidenceAccessGuardService  # noqa: E402
from app.services.evidence_evaluator_service import EvidenceEvaluatorService, EvidenceStatus  # noqa: E402


def evidence(
    content: str = "项目资料正文显示：黑粉进入给料系统，经泵输送至浸出槽。",
    *,
    source_type: str = "project",
    project_id: int | None = 1,
    metadata: dict | None = None,
) -> Evidence:
    evidence_metadata = {"security_level": "public", **(metadata or {})}
    return Evidence(
        score=0.9,
        source_type=source_type,
        knowledge_base_id=1,
        project_id=project_id,
        document_id=10,
        chunk_id=20,
        drawing_no="PFD-001" if source_type in {"drawing", "pdf_visual"} else None,
        file_name="source.pdf",
        page_number=1,
        content=content,
        retriever="milvus",
        metadata=evidence_metadata,
    )


def test_project_chat_answer_policy_matrix() -> None:
    gate = AnswerPolicyGateService()
    cases = {
        "EMPTY": "refusal",
        "WEAK_ONLY": "limited_answer",
        "PARTIAL": "partial_answer_with_llm",
        "ENOUGH": "normal_answer",
        "CONFLICTED": "conflict_answer",
    }
    for status, action in cases.items():
        decision = gate.resolve(
            answer_policy="STRICT_KB",
            evidence_status=status,
            resolved_task_type="process_flow",
            answer_shape="process_steps",
            evidence=[evidence()] if status != "EMPTY" else [],
            chat_type="project_chat",
        )
        assert decision.action == action


def test_base_chat_answer_policy_matrix() -> None:
    gate = AnswerPolicyGateService()
    assert (
        gate.resolve(
            answer_policy="KB_FIRST",
            evidence_status="EMPTY",
            resolved_task_type="unknown",
            answer_shape="general",
            evidence=[],
            chat_type="base_chat",
        ).action
        == "ask_general_confirm"
    )
    assert (
        gate.resolve(
            answer_policy="KB_FIRST",
            evidence_status="EMPTY",
            resolved_task_type="unknown",
            answer_shape="general",
            evidence=[],
            is_obvious_common_knowledge=True,
            chat_type="base_chat",
        ).action
        == "general_answer"
    )
    assert (
        gate.resolve(
            answer_policy="KB_FIRST",
            evidence_status="WEAK_ONLY",
            resolved_task_type="process_flow",
            answer_shape="process_steps",
            evidence=[evidence(source_type="base", project_id=None)],
            chat_type="base_chat",
        ).action
        == "limited_answer"
    )
    assert (
        gate.resolve(
            answer_policy="KB_FIRST",
            evidence_status="PARTIAL",
            resolved_task_type="process_flow",
            answer_shape="process_steps",
            evidence=[evidence(source_type="base", project_id=None)],
            chat_type="base_chat",
        ).action
        == "partial_answer_with_llm"
    )
    assert (
        gate.resolve(
            answer_policy="KB_FIRST",
            evidence_status="ENOUGH",
            resolved_task_type="definition",
            answer_shape="general",
            evidence=[evidence(source_type="base", project_id=None)],
            chat_type="base_chat",
        ).action
        == "normal_answer"
    )


def test_general_allowed_project_fact_degrades() -> None:
    gate = AnswerPolicyGateService()
    decision = gate.resolve(
        answer_policy="GENERAL_ALLOWED",
        evidence_status="EMPTY",
        resolved_task_type="process_flow",
        answer_shape="process_steps",
        evidence=[],
        chat_type="base_chat",
        intent_type="project_fact",
        query_profile={"query_type": "process_flow", "knowledge_scope": "project"},
    )
    assert decision.action != "general_answer"
    assert "降级" in decision.reason


def test_drawing_process_question_not_directly_weak_only() -> None:
    evaluator = EvidenceEvaluatorService()
    result = evaluator.evaluate(
        question="这张 PFD 的黑粉进料流程是什么？",
        evidences=[evidence("TITLE\nRaw Material & Chemical Feeding\nPFD", source_type="pdf_visual")],
        judgement={
            "enough": True,
            "confidence": 0.78,
            "relevance": "full",
            "support_level": "full",
            "conflict": False,
        },
        resolved_task_type="process_flow",
        answer_shape="process_steps",
        query_profile={"query_type": "process_flow", "answer_shape": "process_steps"},
    )
    assert result.evidence_status != EvidenceStatus.WEAK_ONLY.value


def test_metadata_lookup_allows_title_and_version_as_strong_evidence() -> None:
    evaluator = EvidenceEvaluatorService()
    result = evaluator.evaluate(
        question="这个资料的图号和版本号是什么？",
        evidences=[evidence("TITLE\nRaw Material & Chemical Feeding\nRevision A", metadata={"metadata_only": True})],
        judgement={
            "enough": True,
            "confidence": 0.8,
            "relevance": "full",
            "support_level": "full",
            "conflict": False,
        },
        resolved_task_type="metadata_lookup",
        answer_shape="source_location",
        query_profile={"query_type": "metadata_lookup", "answer_shape": "source_location"},
    )
    assert result.evidence_status == EvidenceStatus.ENOUGH.value


def test_low_confidence_enough_is_downgraded_to_partial() -> None:
    evaluator = EvidenceEvaluatorService()
    result = evaluator.evaluate(
        question="黑粉进料量是多少？",
        evidences=[evidence("参数表正文显示：黑粉进料量为 2000 TPA。")],
        judgement={
            "enough": True,
            "confidence": 0.42,
            "relevance": "full",
            "support_level": "full",
            "conflict": False,
        },
        resolved_task_type="parameter_lookup",
        answer_shape="parameter_table",
        query_profile={"query_type": "exact_lookup", "answer_shape": "parameter_table"},
    )
    assert result.evidence_status == EvidenceStatus.PARTIAL.value


def test_final_evidence_guard_removes_permission_limited_evidence_before_prompt() -> None:
    graph = object.__new__(RetrievalGraph)
    graph.evidence_access_guard = EvidenceAccessGuardService(None)
    graph.evidence_evaluator = EvidenceEvaluatorService()
    guarded_evidence = evidence(metadata={"security_level": "confidential"})
    state = {
        "question": "项目参数是什么？",
        "chat_type": "project_chat",
        "project_id": 1,
        "user": SimpleNamespace(id=1, roles=[]),
        "evidences": [guarded_evidence],
        "evidence_judgement": {
            "enough": True,
            "confidence": 0.9,
            "relevance": "full",
            "support_level": "full",
            "conflict": False,
        },
        "resolved_task_type": "parameter_lookup",
        "resolved_answer_shape": "parameter_table",
        "query_profile": {"query_type": "exact_lookup", "answer_shape": "parameter_table"},
        "raw": {},
    }

    graph._apply_final_evidence_guard(state)  # noqa: SLF001

    assert state["evidences"] == []
    assert state["evidence_status"] == "EMPTY"
    assert state["evidence_evaluation"]["risk"] == "permission_limited"


def test_partial_answer_with_visual_evidence_uses_limited_vision_llm() -> None:
    generator = AnswerGenerator.__new__(AnswerGenerator)

    class FakeLLM:
        settings = SimpleNamespace(vision_llm_timeout_seconds=90)

        def __init__(self) -> None:
            self.called_model_type = ""
            self.messages = []

        def _build_image_parts(self, evidences: list[Evidence]) -> list[dict]:  # noqa: SLF001
            return [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]

        def chat(self, messages: list[dict], model_type: str, **_: object) -> str:
            self.called_model_type = model_type
            self.messages = messages
            return "受限视觉回答"

        def model_route(self, task: str, reason: str) -> dict:
            return {"task": task, "source": "fake", "reason": reason}

    fake_llm = FakeLLM()
    generator.llm_service = fake_llm
    generator.last_model_route = None
    visual_evidence = evidence("TITLE\nRaw Material & Chemical Feeding\nP&ID", source_type="pdf_visual")
    visual_evidence.assets.append(
        EvidenceAsset(
            asset_id=1,
            asset_type="page_preview",
            url="/assets/1",
            mime_type="image/png",
            file_name="page.png",
            file_size=128,
            page_number=1,
        )
    )

    answer = generator._partial_answer_with_llm(  # noqa: SLF001
        "Raw Material & Chemical Feeding 全流程",
        [visual_evidence],
        {"missing_aspects": ["流程步骤"]},
        {"query_type": "process_flow", "answer_shape": "process_steps"},
    )

    assert answer == "受限视觉回答"
    assert fake_llm.called_model_type == "vision_llm"
    assert isinstance(fake_llm.messages[1]["content"], list)
