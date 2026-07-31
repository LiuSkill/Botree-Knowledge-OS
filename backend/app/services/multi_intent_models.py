"""多意图问答的内部强类型模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class IntentSubQuestion(BaseModel):
    """可独立检索与判断的最小问题单元。"""

    id: str
    order: int = Field(ge=1)
    question: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)


class QuestionIntent(BaseModel):
    """一次提问中的独立业务目标。"""

    id: str
    order: int = Field(ge=1)
    name: str = Field(min_length=1)
    original_target: str = Field(min_length=1)
    question: str = Field(min_length=1)
    sub_questions: list[IntentSubQuestion] = Field(min_length=1)


class QuestionIntentPlan(BaseModel):
    """经过预算收敛后的多意图规划。"""

    intents: list[QuestionIntent] = Field(min_length=1, max_length=3)
    omitted_targets: list[str] = Field(default_factory=list)
    understanding: str | None = None

    @property
    def requires_orchestration(self) -> bool:
        return len(self.intents) > 1 or any(len(item.sub_questions) > 1 for item in self.intents)


class SubQuestionExecution(BaseModel):
    """单个子问题的执行结果。"""

    sub_question: IntentSubQuestion
    status: Literal["completed", "failed", "timeout"]
    answerability_status: Literal["answered", "partially_answered", "insufficient_evidence", "unavailable"] = "unavailable"
    elapsed_ms: int = Field(ge=0)
    answer: str
    evidence_summary: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    risk_notices: list[str] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict, exclude=True)
    failure_reason: str | None = None


class IntentExecution(BaseModel):
    """单个问答意图的聚合执行结果。"""

    intent: QuestionIntent
    status: Literal["completed", "failed", "timeout"]
    answerability_status: Literal["answered", "partially_answered", "insufficient_evidence", "unavailable"] = "unavailable"
    elapsed_ms: int = Field(ge=0)
    sub_results: list[SubQuestionExecution] = Field(default_factory=list)
    answer: str
    evidence_summary: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    risk_notices: list[str] = Field(default_factory=list)
    failure_reason: str | None = None


def coerce_question_intent_plan(value: QuestionIntentPlan | list[dict[str, Any]]) -> QuestionIntentPlan:
    """兼容旧调用方传入的字典列表，并立即收敛为强类型模型。"""

    if isinstance(value, QuestionIntentPlan):
        return value
    intents: list[QuestionIntent] = []
    for order, item in enumerate(value[:3], start=1):
        question = str(item.get("question") or "").strip()
        raw_sub_questions = item.get("sub_questions") if isinstance(item.get("sub_questions"), list) else [question]
        sub_questions = [
            IntentSubQuestion(
                id=f"intent-{order}-sub-{sub_order}",
                order=sub_order,
                question=str(sub_question.get("question") if isinstance(sub_question, dict) else sub_question).strip(),
                depends_on=[str(dep) for dep in sub_question.get("depends_on", [])] if isinstance(sub_question, dict) else [],
            )
            for sub_order, sub_question in enumerate(raw_sub_questions, start=1)
            if str(sub_question.get("question") if isinstance(sub_question, dict) else sub_question).strip()
        ]
        intents.append(
            QuestionIntent(
                id=f"intent-{order}",
                order=order,
                name=str(item.get("name") or f"意图 {order}"),
                original_target=str(item.get("original_target") or question),
                question=question,
                sub_questions=sub_questions,
            )
        )
    omitted_targets = [str(item.get("original_target") or item.get("question") or "") for item in value[3:]]
    return QuestionIntentPlan(intents=intents, omitted_targets=[item for item in omitted_targets if item])
