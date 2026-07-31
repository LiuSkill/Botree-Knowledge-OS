"""本轮执行计划的强类型模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.multi_intent_models import IntentSubQuestion, QuestionIntentPlan, coerce_question_intent_plan


class PlannedIntent(BaseModel):
    """本轮计划中的单个问答意图。"""

    id: str
    order: int = Field(ge=1)
    name: str = Field(min_length=1)
    source: Literal["current_message", "explicit_history_reference"] = "current_message"
    original_target: str = Field(min_length=1)
    question: str = Field(min_length=1)
    sub_questions: list[IntentSubQuestion] = Field(min_length=1)


class TurnExecutionPlan(BaseModel):
    """本轮问答唯一且不可变的执行计划。"""

    turn_id: int | None = None
    plan_version: int = 1
    original_question: str = Field(min_length=1)
    effective_question: str = Field(min_length=1)
    memory_mode: Literal["skip", "scope_only", "rewrite_single"] = "skip"
    stable_scope: dict[str, Any] = Field(default_factory=dict)
    referenced_context_ids: list[str] = Field(default_factory=list)
    intents: list[PlannedIntent] = Field(min_length=1, max_length=3)
    omitted_targets: list[str] = Field(default_factory=list)
    topic_shift: dict[str, Any] = Field(default_factory=dict)
    memory_decision_reason: str | None = None

    @property
    def requires_orchestration(self) -> bool:
        return len(self.intents) > 1 or any(len(item.sub_questions) > 1 for item in self.intents)

    @property
    def planned_intent_ids(self) -> list[str]:
        return [item.id for item in self.intents]

    @property
    def primary_intent(self) -> PlannedIntent:
        return self.intents[0]


def plan_from_question_intent_plan(
    value: TurnExecutionPlan | QuestionIntentPlan | list[dict[str, Any]],
    *,
    turn_id: int | None,
    original_question: str,
    effective_question: str,
    memory_mode: str,
    stable_scope: dict[str, Any] | None = None,
    referenced_context_ids: list[str] | None = None,
    topic_shift: dict[str, Any] | None = None,
    memory_decision_reason: str | None = None,
) -> TurnExecutionPlan:
    """将旧 QuestionIntentPlan 兼容收敛为 TurnExecutionPlan。"""

    if isinstance(value, TurnExecutionPlan):
        return value
    plan = coerce_question_intent_plan(value)
    intents = [
        PlannedIntent(
            id=intent.id,
            order=intent.order,
            name=intent.name,
            source="current_message",
            original_target=intent.original_target,
            question=intent.question,
            sub_questions=[item.model_copy(deep=True) for item in intent.sub_questions],
        )
        for intent in plan.intents
    ]
    return TurnExecutionPlan(
        turn_id=turn_id,
        original_question=original_question,
        effective_question=effective_question,
        memory_mode=memory_mode if memory_mode in {"skip", "scope_only", "rewrite_single"} else "skip",
        stable_scope=dict(stable_scope or {}),
        referenced_context_ids=list(referenced_context_ids or []),
        intents=intents,
        omitted_targets=list(plan.omitted_targets),
        topic_shift=dict(topic_shift or {}),
        memory_decision_reason=memory_decision_reason,
    )
