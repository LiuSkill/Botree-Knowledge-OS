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

    def stream_generate(
        self,
        question: str,
        evidences: list[Evidence],
        query_profile: dict[str, Any] | None = None,
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
