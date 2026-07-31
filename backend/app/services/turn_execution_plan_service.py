"""构建本轮唯一执行计划。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.chat_memory_service import MemoryIntentResult, TurnContext
from app.services.multi_intent_models import IntentSubQuestion
from app.services.qwen_orchestration_service import QwenOrchestrationService
from app.services.turn_execution_models import PlannedIntent, TurnExecutionPlan, plan_from_question_intent_plan


class TurnExecutionPlanService:
    """把记忆补全后的本轮问题收敛为单一执行计划。"""

    PLAN_VERSION = 1

    def __init__(self, db: Session | None) -> None:
        self.db = db
        self.qwen = QwenOrchestrationService(db)

    def build_plan(
        self,
        original_question: str,
        turn_context: TurnContext | None,
        chat_type: str,
        project_id: int | None,
        business_id: str | int | None,
        *,
        mode: str = "auto",
    ) -> TurnExecutionPlan:
        """按当前消息、显式历史引用和稳定范围构建本轮权威计划。"""

        context = turn_context
        effective_question = str(getattr(context, "effective_question", original_question) or original_question)
        memory_mode = str(getattr(context, "memory_mode", getattr(context, "memory_trigger_mode", "skip")) or "skip")
        stable_scope = dict(getattr(context, "stable_scope", {}) or {})
        stable_scope.setdefault("chat_type", chat_type)
        if project_id is not None:
            stable_scope["project_id"] = project_id
        referenced_context_ids = list(getattr(context, "memory_referenced_context_ids", []) or [])
        topic_shift = dict((getattr(context, "memory_trace", {}) or {}).get("topic_shift") or {})
        memory_decision_reason = str((getattr(context, "memory_trace", {}) or {}).get("decision_reason") or "")
        turn_id = getattr(context, "turn_id", None)

        referenced_intent = self._referenced_history_intent(context)
        if referenced_intent is not None:
            sub_question = IntentSubQuestion(
                id=f"{referenced_intent.id}-sub-1",
                order=1,
                question=effective_question,
            )
            return TurnExecutionPlan(
                turn_id=turn_id,
                plan_version=self.PLAN_VERSION,
                original_question=original_question,
                effective_question=effective_question,
                memory_mode="rewrite_single",
                stable_scope=stable_scope,
                referenced_context_ids=referenced_context_ids or [f"intent::{referenced_intent.id}"],
                intents=[
                    PlannedIntent(
                        id=referenced_intent.id,
                        order=1,
                        name=referenced_intent.name,
                        source="explicit_history_reference",
                        original_target=referenced_intent.name,
                        question=effective_question,
                        sub_questions=[sub_question],
                    )
                ],
                omitted_targets=[],
                topic_shift=topic_shift,
                memory_decision_reason=memory_decision_reason,
            )

        plan_seed = effective_question if memory_mode == "rewrite_single" else original_question
        qwen_plan = self.qwen.plan_question_intents(
            plan_seed,
            chat_type,
            mode,
            business_id=business_id,
        )
        return plan_from_question_intent_plan(
            qwen_plan,
            turn_id=turn_id,
            original_question=original_question,
            effective_question=effective_question if memory_mode == "rewrite_single" else original_question,
            memory_mode=memory_mode if memory_mode in {"skip", "scope_only", "rewrite_single"} else "skip",
            stable_scope=stable_scope,
            referenced_context_ids=referenced_context_ids,
            topic_shift=topic_shift,
            memory_decision_reason=memory_decision_reason,
        ).model_copy(update={"plan_version": self.PLAN_VERSION})

    @staticmethod
    def _referenced_history_intent(turn_context: TurnContext | None) -> MemoryIntentResult | None:
        if turn_context is None:
            return None
        referenced_ids = list(getattr(turn_context, "memory_referenced_context_ids", []) or [])
        if not any(str(item).startswith("intent::") for item in referenced_ids):
            return None
        intent_map = {
            item.id: item
            for item in list((getattr(turn_context, "session_memory", None) or {}).last_intent_results)
            if item.id
        } if getattr(turn_context, "session_memory", None) is not None else {}
        for context_id in referenced_ids:
            if not str(context_id).startswith("intent::"):
                continue
            intent_id = str(context_id).split("intent::", 1)[1]
            if intent_id in intent_map:
                return intent_map[intent_id]
        return None
