from __future__ import annotations

from types import SimpleNamespace

from app.services.chat_memory_service import MemoryIntentResult, SessionMemorySnapshot, TurnContext
from app.services.multi_intent_models import IntentSubQuestion, QuestionIntent, QuestionIntentPlan
from app.services.turn_execution_plan_service import TurnExecutionPlanService


def _single_plan(name: str, question: str) -> QuestionIntentPlan:
    return QuestionIntentPlan(
        intents=[
            QuestionIntent(
                id="intent-1",
                order=1,
                name=name,
                original_target=question,
                question=question,
                sub_questions=[IntentSubQuestion(id="intent-1-sub-1", order=1, question=question)],
            )
        ]
    )


def test_build_plan_for_independent_question_keeps_only_current_message_intent(monkeypatch) -> None:
    service = TurnExecutionPlanService(None)
    service.qwen = SimpleNamespace(plan_question_intents=lambda *args, **kwargs: _single_plan("装机功率统计", "列出装机功率并汇总"))
    turn_context = TurnContext(
        turn_id=18,
        session_id=3,
        session_memory=SessionMemorySnapshot(),
        original_question="本项目的总装机功率是多少？分别列出然后汇总",
        effective_question="本项目的总装机功率是多少？分别列出然后汇总",
        memory_mode="scope_only",
        memory_trigger_mode="scope_only",
        memory_referenced_context_ids=[],
        stable_scope={"chat_type": "project_chat", "project_id": 9},
        reference_resolution={},
        answer_preferences={},
        answer_memory_context={},
        memory_trace={"decision_reason": "stable_scope_only_complete_question", "topic_shift": {"strong": True}},
    )

    plan = service.build_plan(
        "本项目的总装机功率是多少？分别列出然后汇总",
        turn_context,
        "project_chat",
        9,
        "session-9",
    )

    assert plan.turn_id == 18
    assert plan.memory_mode == "scope_only"
    assert plan.original_question == "本项目的总装机功率是多少？分别列出然后汇总"
    assert plan.effective_question == "本项目的总装机功率是多少？分别列出然后汇总"
    assert plan.stable_scope == {"chat_type": "project_chat", "project_id": 9}
    assert plan.referenced_context_ids == []
    assert [item.id for item in plan.intents] == ["intent-1"]
    assert [item.source for item in plan.intents] == ["current_message"]


def test_build_plan_reactivates_explicit_history_intent_only_when_referenced() -> None:
    service = TurnExecutionPlanService(None)
    service.qwen = SimpleNamespace(plan_question_intents=lambda *args, **kwargs: _single_plan("不应被使用", "不应被使用"))
    turn_context = TurnContext(
        turn_id=19,
        session_id=3,
        session_memory=SessionMemorySnapshot(
            last_intent_results=[
                MemoryIntentResult(id="intent-1", name="比较 A", order=1, sub_questions=["比较 A 的成本"]),
                MemoryIntentResult(id="intent-2", name="比较 B", order=2, sub_questions=["比较 B 的成本"]),
            ]
        ),
        original_question="第二个详细说明",
        effective_question="关于比较 B；比较 B 的成本，第二个详细说明",
        memory_mode="rewrite_single",
        memory_trigger_mode="rewrite_single",
        memory_referenced_context_ids=["intent::intent-2"],
        stable_scope={"chat_type": "project_chat", "project_id": 9},
        reference_resolution={"mode": "explicit_history_reference", "context_id": "intent::intent-2"},
        answer_preferences={},
        answer_memory_context={},
        memory_trace={"decision_reason": "explicit_reference_rewrite", "topic_shift": {"strong": False}},
    )

    plan = service.build_plan("第二个详细说明", turn_context, "project_chat", 9, "session-9")

    assert plan.turn_id == 19
    assert plan.memory_mode == "rewrite_single"
    assert plan.referenced_context_ids == ["intent::intent-2"]
    assert [item.id for item in plan.intents] == ["intent-2"]
    assert [item.source for item in plan.intents] == ["explicit_history_reference"]
    assert plan.intents[0].question == "关于比较 B；比较 B 的成本，第二个详细说明"
