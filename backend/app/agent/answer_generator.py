"""Answer Generator

负责：
1. 基于检索证据调用真实 LLM 生成回答
2. 无证据时按知识范围选择无法确认提示或行业通用知识兜底
3. 统一同步与流式问答入口
"""

from collections.abc import Iterator
from typing import Any

from sqlalchemy.orm import Session

from app.retrieval.schemas import Evidence
from app.services.llm_service import LLMService

ANSWER_MODEL_TEXT = "answer_llm"
ANSWER_MODEL_VISION = "vision_llm"
ANSWER_MODEL_ANALYSIS = "analysis_llm"
COMPLEX_ANALYSIS_HINTS = (
    "综合",
    "分析",
    "对比",
    "比较",
    "影响",
    "原因",
    "关联",
    "关系",
    "跨系统",
    "compare",
    "analysis",
    "impact",
    "reason",
    "relationship",
)
TABLE_HINTS = ("|", "\t", "表格", "table", "min", "max", "wt%", "含量", "percentage")
ACTION_NORMAL_ANSWER = "normal_answer"
ACTION_LIMITED_ANSWER = "limited_answer"
ACTION_PARTIAL_ANSWER = "partial_answer"
ACTION_REFUSAL = "refusal"

PROJECT_REFUSAL_TEXT = "当前项目资料中未检索到与该问题相关的有效信息，无法基于项目资料回答。\n说明：不会使用通用知识编造项目事实。"


class AnswerGenerator:
    """回答生成器。"""

    def __init__(self, db: Session) -> None:
        self.llm_service = LLMService(db)
        self.last_model_route: dict[str, Any] | None = None

    def generate(
        self,
        question: str,
        evidences: list[Evidence],
        query_profile: dict[str, Any] | None = None,
    ) -> str:
        """生成完整回答。"""

        model_type, reason = self._select_answer_model(question, evidences)
        if not evidences:
            answer = self.llm_service.answer_with_evidence(
                question,
                evidences,
                model_type=model_type,
                query_profile=query_profile,
            )
            self.last_model_route = self._no_evidence_model_route(query_profile, reason)
            return answer
        if model_type == ANSWER_MODEL_VISION:
            answer = self.llm_service.answer_with_multimodal_evidence(question, evidences, query_profile=query_profile)
        else:
            answer = self.llm_service.answer_with_evidence(
                question,
                evidences,
                model_type=model_type,
                query_profile=query_profile,
            )
        self.last_model_route = self.llm_service.model_route("answer", reason)
        return answer

    def generate_by_action(
        self,
        question: str,
        evidences: list[Evidence],
        *,
        action: str,
        query_profile: dict[str, Any] | None = None,
        evidence_evaluation: dict[str, Any] | None = None,
        **_: Any,
    ) -> str:
        """按 AnswerPolicyGate 的动作生成回答。"""

        if action == ACTION_NORMAL_ANSWER:
            return self.generate(question, evidences, query_profile=query_profile)
        if action == ACTION_LIMITED_ANSWER:
            self.last_model_route = self._rule_answer_route("证据仅包含标题、图名或弱证据，生成有限回答")
            return self._limited_answer(question, evidences, evidence_evaluation or {})
        if action == ACTION_PARTIAL_ANSWER:
            self.last_model_route = self._rule_answer_route("证据不完整，生成部分回答")
            return self._partial_answer(question, evidences, evidence_evaluation or {})
        if action == ACTION_REFUSAL:
            self.last_model_route = self._rule_answer_route("项目资料无有效证据，生成拒答")
            return PROJECT_REFUSAL_TEXT

        self.last_model_route = self._rule_answer_route(f"未知回答动作 {action}，生成拒答")
        return PROJECT_REFUSAL_TEXT

    def stream_generate(
        self,
        question: str,
        evidences: list[Evidence],
        query_profile: dict[str, Any] | None = None,
        **_: Any,
    ) -> Iterator[str]:
        """流式生成回答。"""

        model_type, reason = self._select_answer_model(question, evidences)
        if not evidences:
            yield from self.llm_service.stream_answer_with_evidence(
                question,
                evidences,
                model_type=model_type,
                query_profile=query_profile,
            )
            self.last_model_route = self._no_evidence_model_route(query_profile, reason)
            return
        if model_type == ANSWER_MODEL_VISION:
            yield from self.llm_service.stream_answer_with_multimodal_evidence(
                question,
                evidences,
                query_profile=query_profile,
            )
        else:
            yield from self.llm_service.stream_answer_with_evidence(
                question,
                evidences,
                model_type=model_type,
                query_profile=query_profile,
            )
        self.last_model_route = self.llm_service.model_route("answer", reason)

    def _select_answer_model(self, question: str, evidences: list[Evidence]) -> tuple[str, str]:
        """
        根据证据形态选择最终回答模型。

        规则优先级：
        - 图纸图片需要视觉模型读取，优先于文本综合分析；
        - 大证据量或强综合分析信号升级到 analysis_llm；
        - 其余普通文本回答使用 answer_llm。
        """

        evidence_count = len(evidences)
        visual_asset_count = sum(len(evidence.assets) for evidence in evidences)
        if evidence_count == 0:
            return ANSWER_MODEL_TEXT, "未召回证据，按知识范围选择空证据回答策略"
        if visual_asset_count > 0:
            return ANSWER_MODEL_VISION, f"命中 {visual_asset_count} 张图纸图片，需要视觉模型综合回答"
        if self._is_complex_analysis(question, evidences):
            return ANSWER_MODEL_ANALYSIS, "命中复杂综合分析信号，升级到综合分析模型"
        return ANSWER_MODEL_TEXT, "普通文本资料问答，使用标准回答模型"

    def _is_complex_analysis(self, question: str, evidences: list[Evidence]) -> bool:
        normalized_question = question.lower()
        has_analysis_hint = any(token in normalized_question or token in question for token in COMPLEX_ANALYSIS_HINTS)
        if not has_analysis_hint:
            return False

        evidence_count = len(evidences)
        visual_asset_count = sum(len(evidence.assets) for evidence in evidences)
        table_signal_count = self._table_signal_count(evidences)
        document_count = len({evidence.document_id for evidence in evidences})
        drawing_count = len({evidence.drawing_no for evidence in evidences if evidence.drawing_no})
        return (
            evidence_count >= 5
            or visual_asset_count >= 2
            or table_signal_count >= 3
            or document_count >= 3
            or drawing_count >= 2
        )

    def _table_signal_count(self, evidences: list[Evidence]) -> int:
        count = 0
        for evidence in evidences:
            content = evidence.content.lower()
            if any(token in content for token in TABLE_HINTS):
                count += 1
        return count

    def _no_evidence_model_route(self, query_profile: dict[str, Any] | None, reason: str) -> dict[str, Any]:
        """无证据回答的模型路由：行业兜底会实际调用模型，其他场景不调用。"""

        profile = query_profile or {}
        if str(profile.get("knowledge_scope") or "") == "industry":
            return self.llm_service.model_route("answer", "行业知识库未召回证据，使用模型通用知识兜底回答")
        return {"task": "answer", "source": "not_called", "reason": reason}

    def _limited_answer(self, question: str, evidences: list[Evidence], evidence_evaluation: dict[str, Any]) -> str:
        topic = self._topic_text(question)
        lines = [
            f"基于当前项目资料，只检索到与「{topic}」相关的标题、图名或弱证据，未检索到足够的正文流程/参数/说明，因此无法给出完整回答。"
        ]
        evidence_lines = self._evidence_excerpt_lines(evidences)
        if evidence_lines:
            lines.append("可引用的弱证据如下，但这些内容只能证明资料中出现过相关标题或图名，不能支撑完整项目结论：")
            lines.extend(evidence_lines)
        missing = evidence_evaluation.get("missing_aspects") or []
        if missing:
            lines.append(f"当前缺失的信息包括：{'、'.join(str(item) for item in missing)}。")
        return "\n".join(lines)

    def _partial_answer(self, question: str, evidences: list[Evidence], evidence_evaluation: dict[str, Any]) -> str:
        topic = self._topic_text(question)
        lines = [
            f"基于当前项目资料，只检索到与「{topic}」相关的部分正文片段，信息不完整，以下仅概括已能从现有证据中确认的内容："
        ]
        evidence_lines = self._evidence_excerpt_lines(evidences)
        if evidence_lines:
            lines.extend(evidence_lines)
        else:
            lines.append("现有证据片段不足以提炼明确内容。")
        missing = evidence_evaluation.get("missing_aspects") or []
        if missing:
            lines.append(f"尚缺少：{'、'.join(str(item) for item in missing)}。因此不能补写未被项目资料明确支持的流程、参数或设备关系。")
        return "\n".join(lines)

    def _evidence_excerpt_lines(self, evidences: list[Evidence]) -> list[str]:
        lines: list[str] = []
        for index, evidence in enumerate(evidences[:3], start=1):
            source_parts = [str(evidence.file_name or "项目资料")]
            if evidence.page_number:
                source_parts.append(f"第 {evidence.page_number} 页")
            if evidence.drawing_no:
                source_parts.append(f"图号 {evidence.drawing_no}")
            source = "，".join(source_parts)
            lines.append(f"[{index}] {source}：{self._clip_content(evidence.content)}")
        return lines

    def _topic_text(self, question: str) -> str:
        return self._clip_content(question, limit=60) or "该问题"

    def _clip_content(self, content: str, limit: int = 140) -> str:
        text = str(content or "").replace("\r", " ").replace("\n", " ").strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit]}..."

    def _rule_answer_route(self, reason: str) -> dict[str, Any]:
        return {"task": "answer", "source": "rules", "reason": reason}
