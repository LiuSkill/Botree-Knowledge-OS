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
    LIMITED_ANSWER = "limited_answer"
    PARTIAL_ANSWER = "partial_answer"
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
    ) -> AnswerPolicyDecision:
        policy = str(answer_policy or "")
        status = str(evidence_status or EvidenceStatus.EMPTY.value)

        if policy == AnswerPolicy.STRICT_KB.value:
            return self._resolve_project_chat(status, evidence)
        if policy == AnswerPolicy.GENERAL_ALLOWED.value:
            return AnswerPolicyDecision(
                action=AnswerAction.NORMAL_ANSWER.value,
                reason="GENERAL_ALLOWED 允许直接回答",
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
                action=AnswerAction.PARTIAL_ANSWER.value,
                reason="project_chat 有部分正文证据但不足以完整回答，输出部分回答",
            )
        if status == EvidenceStatus.ENOUGH.value and evidence:
            return AnswerPolicyDecision(
                action=AnswerAction.NORMAL_ANSWER.value,
                reason="project_chat 项目证据足够，生成正常回答",
            )
        if status == EvidenceStatus.CONFLICTED.value:
            action = AnswerAction.PARTIAL_ANSWER.value if evidence else AnswerAction.REFUSAL.value
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
        if status == EvidenceStatus.CONFLICTED.value:
            return AnswerPolicyDecision(
                action=AnswerAction.REFUSAL.value,
                reason="base_chat 知识库证据冲突，无法直接回答",
            )
        if evidence or is_obvious_common_knowledge:
            return AnswerPolicyDecision(
                action=AnswerAction.NORMAL_ANSWER.value,
                reason="base_chat/KB_FIRST 有证据或明显常识，可正常回答",
            )
        return AnswerPolicyDecision(
            action=AnswerAction.ASK_GENERAL_CONFIRM.value,
            reason="base_chat/KB_FIRST 无可用证据，需确认通用回答",
        )
