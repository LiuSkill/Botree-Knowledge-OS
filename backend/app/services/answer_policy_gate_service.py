"""Answer policy gate service.

负责：
1. 使用新策略字段 answer_policy / evidence_status 决定最终回答动作。
2. 阻止 project_chat 在证据不足时使用通用知识补齐项目事实。
3. 输出可审计的 action 与 reason。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from app.retrieval.schemas import Evidence
from app.services.evidence_evaluator_service import EvidenceStatus
from app.services.question_understanding_service import AnswerPolicy


class AnswerAction(str, Enum):
    """答案生成动作。"""

    NORMAL_ANSWER = "normal_answer"
    GENERAL_ANSWER = "general_answer"
    LIMITED_ANSWER = "limited_answer"
    PARTIAL_ANSWER = "partial_answer"
    PARTIAL_ANSWER_WITH_LLM = "partial_answer_with_llm"
    CONFLICT_ANSWER = "conflict_answer"
    REFUSAL = "refusal"
    ASK_GENERAL_CONFIRM = "ask_general_confirm"


@dataclass(frozen=True)
class AnswerPolicyDecision:
    """答案门控决策。"""

    action: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AnswerPolicyGateService:
    """根据新策略和证据状态决定回答动作。"""

    def resolve(
        self,
        *,
        answer_policy: str,
        evidence_status: str,
        resolved_task_type: str,
        answer_shape: str,
        evidence: list[Evidence],
        is_obvious_common_knowledge: bool = False,
        chat_type: str | None = None,
        intent_type: str | None = None,
        query_profile: dict[str, Any] | None = None,
    ) -> AnswerPolicyDecision:
        policy = str(answer_policy or "")
        status = str(evidence_status or EvidenceStatus.EMPTY.value)
        profile = query_profile or {}

        if policy == AnswerPolicy.STRICT_KB.value:
            return self._resolve_project_chat(status, evidence)
        if policy == AnswerPolicy.GENERAL_ALLOWED.value:
            degraded_policy = self._general_allowed_degraded_policy(
                chat_type=chat_type,
                intent_type=intent_type,
                query_profile=profile,
                resolved_task_type=resolved_task_type,
                answer_shape=answer_shape,
                is_obvious_common_knowledge=is_obvious_common_knowledge,
            )
            if degraded_policy == AnswerPolicy.STRICT_KB.value:
                decision = self._resolve_project_chat(status, evidence)
                return AnswerPolicyDecision(
                    action=decision.action,
                    reason=f"GENERAL_ALLOWED 遇到项目事实类问题，降级为 STRICT_KB：{decision.reason}",
                )
            if degraded_policy == AnswerPolicy.KB_FIRST.value:
                decision = self._resolve_base_chat(status, evidence, is_obvious_common_knowledge)
                return AnswerPolicyDecision(
                    action=decision.action,
                    reason=f"GENERAL_ALLOWED 遇到知识库约束类问题，降级为 KB_FIRST：{decision.reason}",
                )
            return AnswerPolicyDecision(
                action=AnswerAction.GENERAL_ANSWER.value,
                reason="GENERAL_ALLOWED 仅命中问候、身份、明显常识或简单计算，允许通用回答",
            )
        if policy == AnswerPolicy.KB_FIRST.value:
            return self._resolve_base_chat(status, evidence, is_obvious_common_knowledge)
        if policy == AnswerPolicy.ASK_GENERAL_CONFIRM.value:
            return AnswerPolicyDecision(
                action=AnswerAction.ASK_GENERAL_CONFIRM.value,
                reason="策略要求先征询是否使用通用知识",
            )

        return AnswerPolicyDecision(
            action=AnswerAction.REFUSAL.value,
            reason=(
                f"未识别的新回答策略：{policy or '<empty>'}，"
                f"task={resolved_task_type or '-'}，shape={answer_shape or '-'}"
            ),
        )

    def _resolve_project_chat(self, status: str, evidence: list[Evidence]) -> AnswerPolicyDecision:
        if status == EvidenceStatus.EMPTY.value:
            return AnswerPolicyDecision(
                action=AnswerAction.REFUSAL.value,
                reason="project_chat/STRICT_KB 无有效项目证据，拒绝使用通用知识补齐项目事实",
            )
        if status == EvidenceStatus.WEAK_ONLY.value:
            return AnswerPolicyDecision(
                action=AnswerAction.LIMITED_ANSWER.value,
                reason="project_chat 仅有标题、图名、页眉等弱证据，只能输出有限回答",
            )
        if status == EvidenceStatus.PARTIAL.value:
            return AnswerPolicyDecision(
                action=AnswerAction.PARTIAL_ANSWER_WITH_LLM.value,
                reason="project_chat 有部分正文证据但不足以完整回答，使用受限 LLM 输出部分回答",
            )
        if status == EvidenceStatus.ENOUGH.value and evidence:
            return AnswerPolicyDecision(
                action=AnswerAction.NORMAL_ANSWER.value,
                reason="project_chat 项目证据足够，生成正常回答",
            )
        if status == EvidenceStatus.CONFLICTED.value:
            action = AnswerAction.CONFLICT_ANSWER.value if evidence else AnswerAction.REFUSAL.value
            return AnswerPolicyDecision(action=action, reason="project_chat 项目证据存在冲突，不能给出完整确定结论")
        return AnswerPolicyDecision(
            action=AnswerAction.REFUSAL.value,
            reason=f"project_chat 未满足回答条件：evidence_status={status}",
        )

    def _resolve_base_chat(
        self,
        status: str,
        evidence: list[Evidence],
        is_obvious_common_knowledge: bool,
    ) -> AnswerPolicyDecision:
        if status == EvidenceStatus.EMPTY.value and not is_obvious_common_knowledge:
            return AnswerPolicyDecision(
                action=AnswerAction.ASK_GENERAL_CONFIRM.value,
                reason="base_chat/KB_FIRST 无知识库证据，需先询问是否使用通用知识",
            )
        if status == EvidenceStatus.EMPTY.value and is_obvious_common_knowledge:
            return AnswerPolicyDecision(
                action=AnswerAction.GENERAL_ANSWER.value,
                reason="base_chat/KB_FIRST 无知识库证据但属于明显常识，允许通用回答且不挂知识库引用",
            )
        if status == EvidenceStatus.WEAK_ONLY.value:
            return AnswerPolicyDecision(
                action=AnswerAction.LIMITED_ANSWER.value,
                reason="base_chat/KB_FIRST 仅有弱证据，输出有限回答并提示可确认是否通用补充",
            )
        if status == EvidenceStatus.PARTIAL.value:
            return AnswerPolicyDecision(
                action=AnswerAction.PARTIAL_ANSWER_WITH_LLM.value,
                reason="base_chat/KB_FIRST 有部分证据，使用受限 LLM 回答并提示可确认是否通用补充",
            )
        if status == EvidenceStatus.ENOUGH.value and evidence:
            return AnswerPolicyDecision(
                action=AnswerAction.NORMAL_ANSWER.value,
                reason="base_chat/KB_FIRST 知识库证据充足，生成正常回答",
            )
        if status == EvidenceStatus.CONFLICTED.value:
            action = AnswerAction.CONFLICT_ANSWER.value if evidence else AnswerAction.REFUSAL.value
            return AnswerPolicyDecision(
                action=action,
                reason="base_chat 知识库证据冲突，无法直接回答",
            )
        return AnswerPolicyDecision(
            action=AnswerAction.ASK_GENERAL_CONFIRM.value,
            reason="base_chat/KB_FIRST 无可用证据，需确认通用回答",
        )

    def _general_allowed_degraded_policy(
        self,
        *,
        chat_type: str | None,
        intent_type: str | None,
        query_profile: dict[str, Any],
        resolved_task_type: str,
        answer_shape: str,
        is_obvious_common_knowledge: bool,
    ) -> str | None:
        """GENERAL_ALLOWED 只放行轻量通用问题，业务/项目事实降级回知识库策略。"""

        intent = str(intent_type or "")
        query_type = str(query_profile.get("query_type") or "")
        scope = str(query_profile.get("knowledge_scope") or "")
        task = str(resolved_task_type or "")
        shape = str(answer_shape or query_profile.get("answer_shape") or "")
        general_allowed = {
            "greeting",
            "identity",
            "bot_identity",
            "help",
            "obvious_common_knowledge",
            "simple_math_or_formula",
            "casual",
        }
        if intent in general_allowed or is_obvious_common_knowledge or query_type == "simple_math_or_formula":
            if scope in {"project", "industry"}:
                return AnswerPolicy.STRICT_KB.value if chat_type == "project_chat" or scope == "project" else AnswerPolicy.KB_FIRST.value
            return None
        if intent == "industry_knowledge" or scope == "industry" or query_type == "industry_knowledge_qa":
            return AnswerPolicy.KB_FIRST.value
        project_markers = {
            "project_fact",
            "process_flow",
            "equipment_relation",
            "equipment_lookup",
            "parameter_lookup",
            "project_overview",
            "graph_reasoning",
            "page_location",
            "exact_lookup",
            "comparison",
        }
        project_shapes = {"process_steps", "flow_description", "equipment_relation", "parameter_table", "source_location"}
        if (
            intent in project_markers
            or task in project_markers
            or query_type in project_markers
            or shape in project_shapes
            or scope == "project"
            or chat_type == "project_chat"
        ):
            return AnswerPolicy.STRICT_KB.value if chat_type == "project_chat" or scope == "project" else AnswerPolicy.KB_FIRST.value
        return AnswerPolicy.KB_FIRST.value
