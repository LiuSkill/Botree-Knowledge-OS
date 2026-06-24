"""Policy resolver service.

负责：
1. 将 chat_type、旧 intent、query_profile 与 QuestionUnderstanding 的信号合并
2. 输出 resolved_task_type / answer_policy / knowledge_scope 等最终策略字段
3. 本阶段只写入新字段，不覆盖旧主流程字段
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.services.question_understanding_service import AnswerPolicy, AnswerShape, KnowledgeScope, TaskType


@dataclass(frozen=True)
class ModePolicy:
    """由会话模式决定的系统级策略。"""

    answer_policy: str
    knowledge_scope: str
    allow_general_project_fact: bool
    no_evidence_policy: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PolicyResolution:
    """最终策略解析结果。"""

    resolved_task_type: str
    resolved_answer_shape: str
    answer_policy: str
    knowledge_scope: str
    conflict_detected: bool
    conflict_reason: str
    resolution_rule: str
    original_intent: str | None
    query_profile_task_type: str | None
    question_understanding_task_type: str | None
    answer_shape: str
    mode_policy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModePolicyService:
    """根据会话模式生成基础策略。"""

    def resolve(
        self,
        *,
        chat_type: str,
        project_id: int | None,
        user_id: int | None,  # noqa: ARG002 - 预留给后续用户级授权策略
        task_type: str | None = None,
        intent: str | None = None,
    ) -> ModePolicy:
        if chat_type == "project_chat" or project_id is not None:
            return ModePolicy(
                answer_policy=AnswerPolicy.STRICT_KB.value,
                knowledge_scope=KnowledgeScope.PROJECT.value,
                allow_general_project_fact=False,
                no_evidence_policy=None,
                reason="project_chat 永远使用 STRICT_KB，禁止通用知识补充项目事实",
            )
        if intent == "greeting" or task_type == TaskType.CASUAL.value:
            return ModePolicy(
                answer_policy=AnswerPolicy.GENERAL_ALLOWED.value,
                knowledge_scope=KnowledgeScope.BASE.value,
                allow_general_project_fact=True,
                no_evidence_policy=None,
                reason="问候/闲聊可走预设或通用回答",
            )
        return ModePolicy(
            answer_policy=AnswerPolicy.KB_FIRST.value,
            knowledge_scope=KnowledgeScope.BASE.value,
            allow_general_project_fact=True,
            no_evidence_policy=AnswerPolicy.ASK_GENERAL_CONFIRM.value,
            reason="base_chat 默认 KB_FIRST，无证据后可 ASK_GENERAL_CONFIRM",
        )


class PolicyResolver:
    """解决旧 intent、query_profile 和 QuestionUnderstanding 的策略冲突。"""

    _TASK_TO_SHAPE: dict[str, str] = {
        TaskType.PROJECT_OVERVIEW.value: AnswerShape.PROJECT_SUMMARY.value,
        TaskType.PROCESS_FLOW.value: AnswerShape.PROCESS_STEPS.value,
        TaskType.COMPARISON.value: AnswerShape.COMPARISON_TABLE.value,
        TaskType.PARAMETER_LOOKUP.value: AnswerShape.PARAMETER_TABLE.value,
        TaskType.DOCUMENT_LOCATION.value: AnswerShape.SOURCE_LOCATION.value,
        TaskType.DEFINITION.value: AnswerShape.DIRECT_ANSWER.value,
    }
    _INTENT_TO_TASK: dict[str, str] = {
        "project_overview": TaskType.PROJECT_OVERVIEW.value,
        "process_flow": TaskType.PROCESS_FLOW.value,
        "comparison": TaskType.COMPARISON.value,
        "exact_lookup": TaskType.PARAMETER_LOOKUP.value,
        "page_location": TaskType.DOCUMENT_LOCATION.value,
        "greeting": TaskType.CASUAL.value,
    }
    _QUERY_TYPE_TO_TASK: dict[str, str] = {
        "project_overview": TaskType.PROJECT_OVERVIEW.value,
        "process_flow": TaskType.PROCESS_FLOW.value,
        "comparison": TaskType.COMPARISON.value,
        "exact_lookup": TaskType.PARAMETER_LOOKUP.value,
        "page_location": TaskType.DOCUMENT_LOCATION.value,
        "industry_knowledge_qa": TaskType.DEFINITION.value,
        "pure_general_qa": TaskType.CASUAL.value,
    }

    def __init__(self, mode_policy_service: ModePolicyService | None = None) -> None:
        self.mode_policy_service = mode_policy_service or ModePolicyService()

    def resolve(
        self,
        *,
        chat_type: str,
        project_id: int | None,
        user_id: int | None,
        intent: str | None,
        query_profile: dict[str, Any] | None,
        question_understanding: dict[str, Any] | Any,
    ) -> PolicyResolution:
        profile = query_profile or {}
        understanding = self._to_dict(question_understanding)
        original_intent = str(intent or "") or None
        question_task = str(understanding.get("task_type") or TaskType.UNKNOWN.value)
        profile_task = self._task_from_query_profile(profile)
        intent_task = self._task_from_intent(original_intent)

        resolved_task_type, resolution_rule = self._resolve_task_type(
            question_task=question_task,
            profile_task=profile_task,
            intent_task=intent_task,
            query_profile=profile,
        )
        resolved_answer_shape = self._answer_shape_for_task(resolved_task_type)
        mode_policy = self.mode_policy_service.resolve(
            chat_type=chat_type,
            project_id=project_id,
            user_id=user_id,
            task_type=resolved_task_type,
            intent=original_intent,
        )
        knowledge_scope = self._resolve_knowledge_scope(chat_type, profile, understanding, mode_policy)
        answer_policy = mode_policy.answer_policy
        conflict_detected, conflict_reason = self._detect_conflict(
            resolved_task_type=resolved_task_type,
            intent_task=intent_task,
            profile_task=profile_task,
            question_task=question_task,
            original_intent=original_intent,
        )
        full_rule = resolution_rule
        if chat_type == "project_chat" or project_id is not None:
            full_rule = f"{resolution_rule};mode_policy_project_chat_strict_kb"

        return PolicyResolution(
            resolved_task_type=resolved_task_type,
            resolved_answer_shape=resolved_answer_shape,
            answer_policy=answer_policy,
            knowledge_scope=knowledge_scope,
            conflict_detected=conflict_detected,
            conflict_reason=conflict_reason,
            resolution_rule=full_rule,
            original_intent=original_intent,
            query_profile_task_type=profile_task,
            question_understanding_task_type=question_task,
            answer_shape=resolved_answer_shape,
            mode_policy=mode_policy.to_dict(),
        )

    def _resolve_task_type(
        self,
        *,
        question_task: str,
        profile_task: str | None,
        intent_task: str | None,
        query_profile: dict[str, Any],
    ) -> tuple[str, str]:
        if question_task == TaskType.PROCESS_FLOW.value:
            return TaskType.PROCESS_FLOW.value, "question_understanding_process_flow_priority"
        if query_profile.get("query_type") == "process_flow":
            return TaskType.PROCESS_FLOW.value, "query_profile_process_flow_priority"
        if profile_task and profile_task != TaskType.UNKNOWN.value:
            return profile_task, "query_profile_task_type"
        if intent_task and intent_task != TaskType.UNKNOWN.value:
            return intent_task, "intent_task_type"
        if question_task != TaskType.UNKNOWN.value:
            return question_task, "question_understanding_task_type"
        return TaskType.UNKNOWN.value, "fallback_unknown"

    def _task_from_query_profile(self, profile: dict[str, Any]) -> str | None:
        query_type = str(profile.get("query_type") or "")
        if query_type == "graph_reasoning" and profile.get("answer_shape") == "process_steps":
            return TaskType.PROCESS_FLOW.value
        return self._QUERY_TYPE_TO_TASK.get(query_type)

    def _task_from_intent(self, intent: str | None) -> str | None:
        if not intent:
            return None
        return self._INTENT_TO_TASK.get(intent)

    def _answer_shape_for_task(self, task_type: str) -> str:
        return self._TASK_TO_SHAPE.get(task_type, AnswerShape.DIRECT_ANSWER.value)

    def _resolve_knowledge_scope(
        self,
        chat_type: str,
        query_profile: dict[str, Any],
        understanding: dict[str, Any],
        mode_policy: ModePolicy,
    ) -> str:
        if chat_type == "project_chat":
            return KnowledgeScope.PROJECT.value
        understanding_scope = str(understanding.get("knowledge_scope") or "")
        profile_scope = str(query_profile.get("knowledge_scope") or "")
        if understanding_scope in {KnowledgeScope.INDUSTRY.value, KnowledgeScope.AUTHORIZED_INTERNAL.value}:
            return understanding_scope
        if profile_scope == KnowledgeScope.INDUSTRY.value:
            return KnowledgeScope.INDUSTRY.value
        return mode_policy.knowledge_scope

    def _detect_conflict(
        self,
        *,
        resolved_task_type: str,
        intent_task: str | None,
        profile_task: str | None,
        question_task: str | None,
        original_intent: str | None,
    ) -> tuple[bool, str]:
        conflicts: list[str] = []
        generic_intents = {"project_qa", "knowledge_qa", "industry_knowledge_qa", "pure_general_qa", "general_qa"}
        if (
            original_intent
            and original_intent not in generic_intents
            and intent_task
            and intent_task != resolved_task_type
            and intent_task != TaskType.UNKNOWN.value
        ):
            conflicts.append(f"intent={intent_task} 与 resolved_task_type={resolved_task_type} 不一致")
        if profile_task and profile_task != resolved_task_type and profile_task != TaskType.UNKNOWN.value:
            conflicts.append(f"query_profile={profile_task} 与 resolved_task_type={resolved_task_type} 不一致")
        if question_task and question_task != resolved_task_type and question_task != TaskType.UNKNOWN.value:
            conflicts.append(f"question_understanding={question_task} 与 resolved_task_type={resolved_task_type} 不一致")
        return bool(conflicts), "；".join(conflicts)

    def _to_dict(self, value: dict[str, Any] | Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if hasattr(value, "to_dict"):
            return value.to_dict()
        return {}
