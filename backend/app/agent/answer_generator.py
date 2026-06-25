"""Answer Generator

负责：
1. 基于检索证据调用真实 LLM 生成回答
2. 无证据时按知识范围选择无法确认提示或行业通用知识兜底
3. 统一同步与流式问答入口
"""

import json
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
ACTION_GENERAL_ANSWER = "general_answer"
ACTION_LIMITED_ANSWER = "limited_answer"
ACTION_PARTIAL_ANSWER = "partial_answer"
ACTION_PARTIAL_ANSWER_WITH_LLM = "partial_answer_with_llm"
ACTION_CONFLICT_ANSWER = "conflict_answer"
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
        if action == ACTION_GENERAL_ANSWER:
            return self._general_answer(question, query_profile=query_profile)
        if action == ACTION_LIMITED_ANSWER:
            self.last_model_route = self._rule_answer_route("证据仅包含标题、图名或弱证据，生成有限回答")
            return self._limited_answer(question, evidences, evidence_evaluation or {})
        if action == ACTION_PARTIAL_ANSWER_WITH_LLM:
            return self._partial_answer_with_llm(question, evidences, evidence_evaluation or {}, query_profile or {})
        if action == ACTION_PARTIAL_ANSWER:
            self.last_model_route = self._rule_answer_route("证据不完整，生成部分回答")
            return self._partial_answer(question, evidences, evidence_evaluation or {})
        if action == ACTION_CONFLICT_ANSWER:
            self.last_model_route = self._rule_answer_route("证据存在冲突，生成冲突说明")
            return self._conflict_answer(question, evidences, evidence_evaluation or {})
        if action == ACTION_REFUSAL:
            self.last_model_route = self._rule_answer_route("无有效可用证据，生成拒答")
            return self._refusal_answer(question, evidence_evaluation or {}, query_profile or {})

        self.last_model_route = self._rule_answer_route(f"未知回答动作 {action}，生成拒答")
        return PROJECT_REFUSAL_TEXT

    def stream_generate(
        self,
        question: str,
        evidences: list[Evidence],
        query_profile: dict[str, Any] | None = None,
        action: str = ACTION_NORMAL_ANSWER,
        evidence_evaluation: dict[str, Any] | None = None,
        **_: Any,
    ) -> Iterator[str]:
        """流式生成回答。"""

        if action == ACTION_GENERAL_ANSWER:
            yield from self._stream_general_answer(question, query_profile=query_profile)
            return
        if action == ACTION_PARTIAL_ANSWER_WITH_LLM:
            yield from self._stream_partial_answer_with_llm(
                question,
                evidences,
                evidence_evaluation or {},
                query_profile or {},
            )
            return
        if action != ACTION_NORMAL_ANSWER:
            yield self.generate_by_action(
                question,
                evidences,
                action=action,
                query_profile=query_profile,
                evidence_evaluation=evidence_evaluation,
            )
            return

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
        lines.append("建议补充正文页、图纸解析结果、参数表或设备关系说明后再检索；如需使用通用知识补充，请先确认。")
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

    def _partial_answer_with_llm(
        self,
        question: str,
        evidences: list[Evidence],
        evidence_evaluation: dict[str, Any],
        query_profile: dict[str, Any],
    ) -> str:
        """使用受限 prompt 让 LLM 只整理已被证据支持的部分。"""

        if not evidences:
            self.last_model_route = self._rule_answer_route("无可用证据，受限 LLM 回答降级为规则部分回答")
            return self._partial_answer(question, evidences, evidence_evaluation)
        if self._should_use_limited_vision(evidences, query_profile):
            image_parts = self.llm_service._build_image_parts(evidences)  # noqa: SLF001
            if image_parts:
                answer = self.llm_service.chat(
                    self._build_partial_multimodal_messages(
                        question,
                        evidences,
                        evidence_evaluation,
                        query_profile,
                        image_parts,
                    ),
                    model_type=ANSWER_MODEL_VISION,
                    timeout_seconds=self.llm_service.settings.vision_llm_timeout_seconds,
                    max_tokens=1400,
                    disable_thinking=True,
                )
                self.last_model_route = self.llm_service.model_route(
                    "answer",
                    "证据不足但存在图纸图片，使用受限视觉 LLM 生成部分回答",
                )
                return answer
        messages = self._build_partial_llm_messages(question, evidences, evidence_evaluation, query_profile)
        answer = self.llm_service.chat(messages, model_type=ANSWER_MODEL_TEXT, max_tokens=1200, disable_thinking=True)
        self.last_model_route = self.llm_service.model_route("answer", "证据不足但存在可回答部分，使用受限 LLM 生成部分回答")
        return answer

    def _stream_partial_answer_with_llm(
        self,
        question: str,
        evidences: list[Evidence],
        evidence_evaluation: dict[str, Any],
        query_profile: dict[str, Any],
    ) -> Iterator[str]:
        if not evidences:
            yield self._partial_answer(question, evidences, evidence_evaluation)
            self.last_model_route = self._rule_answer_route("无可用证据，受限 LLM 流式回答降级为规则部分回答")
            return
        if self._should_use_limited_vision(evidences, query_profile):
            image_parts = self.llm_service._build_image_parts(evidences)  # noqa: SLF001
            if image_parts:
                yield from self.llm_service.stream_chat(
                    self._build_partial_multimodal_messages(
                        question,
                        evidences,
                        evidence_evaluation,
                        query_profile,
                        image_parts,
                    ),
                    model_type=ANSWER_MODEL_VISION,
                    timeout_seconds=self.llm_service.settings.vision_llm_timeout_seconds,
                    max_tokens=1400,
                    disable_thinking=True,
                )
                self.last_model_route = self.llm_service.model_route(
                    "answer",
                    "证据不足但存在图纸图片，流式使用受限视觉 LLM",
                )
                return
        messages = self._build_partial_llm_messages(question, evidences, evidence_evaluation, query_profile)
        yield from self.llm_service.stream_chat(
            messages,
            model_type=ANSWER_MODEL_TEXT,
            max_tokens=1200,
            disable_thinking=True,
        )
        self.last_model_route = self.llm_service.model_route("answer", "证据不足但存在可回答部分，流式使用受限 LLM")

    def _general_answer(self, question: str, query_profile: dict[str, Any] | None = None) -> str:
        messages = self._build_general_messages(question, query_profile or {})
        answer = self.llm_service.chat(messages, model_type=ANSWER_MODEL_TEXT, max_tokens=800, disable_thinking=True)
        self.last_model_route = self.llm_service.model_route("answer", "GENERAL_ALLOWED 通用回答，不生成知识库引用")
        return answer

    def _stream_general_answer(
        self,
        question: str,
        query_profile: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        yield from self.llm_service.stream_chat(
            self._build_general_messages(question, query_profile or {}),
            model_type=ANSWER_MODEL_TEXT,
            max_tokens=800,
            disable_thinking=True,
        )
        self.last_model_route = self.llm_service.model_route("answer", "GENERAL_ALLOWED 流式通用回答，不生成知识库引用")

    def _build_partial_llm_messages(
        self,
        question: str,
        evidences: list[Evidence],
        evidence_evaluation: dict[str, Any],
        query_profile: dict[str, Any],
    ) -> list[dict[str, str]]:
        context = {
            "question": question,
            "query_profile": query_profile,
            "answerable_parts": evidence_evaluation.get("answerable_parts") or [],
            "missing_aspects": evidence_evaluation.get("missing_aspects") or [],
            "suggested_queries": evidence_evaluation.get("suggested_queries") or [],
            "evidences": self._evidence_excerpt_lines(evidences[:8]),
        }
        return [
            {
                "role": "system",
                "content": (
                    "你是知识库问答的受限回答器。你只能回答证据中明确支持的内容。"
                    "不得补全未检索到的流程、参数、设备关系、项目事实。"
                    "回答必须分为三节：1. 已能确认的信息；2. 资料不足，无法确认的信息；"
                    "3. 缺失证据或建议补充检索方向。"
                    "如果证据不能支持某个部分，必须明确说“当前资料未检索到”。"
                    "不要伪造来源，不要使用通用知识补齐项目事实。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(context, ensure_ascii=False),
            },
        ]

    def _build_partial_multimodal_messages(
        self,
        question: str,
        evidences: list[Evidence],
        evidence_evaluation: dict[str, Any],
        query_profile: dict[str, Any],
        image_parts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        context = {
            "question": question,
            "query_profile": query_profile,
            "answerable_parts": evidence_evaluation.get("answerable_parts") or [],
            "missing_aspects": evidence_evaluation.get("missing_aspects") or [],
            "suggested_queries": evidence_evaluation.get("suggested_queries") or [],
            "evidences": self._evidence_excerpt_lines(evidences[:8]),
            "visual_instruction": "图片证据已随消息提供，请只说明图纸图片中能直接看出的流程、设备、管线、箭头和仪表标识。",
        }
        return [
            {
                "role": "system",
                "content": (
                    "你是知识库问答的受限视觉回答器。你只能回答文字证据或图片证据中明确支持的内容。"
                    "不得补全未检索到、未在图中识别到的流程、参数、设备关系、项目事实。"
                    "回答必须分为三节：1. 已能确认的信息；2. 资料不足，无法确认的信息；"
                    "3. 缺失证据或建议补充检索方向。"
                    "如果图片分辨率或文字证据不能支持某个部分，必须明确说“当前资料未检索到”。"
                    "不要伪造来源，不要使用通用知识补齐项目事实。"
                ),
            },
            {
                "role": "user",
                "content": [{"type": "text", "text": json.dumps(context, ensure_ascii=False)}, *image_parts],
            },
        ]

    def _should_use_limited_vision(self, evidences: list[Evidence], query_profile: dict[str, Any]) -> bool:
        if not any(evidence.assets for evidence in evidences):
            return False
        answer_shape = str(query_profile.get("answer_shape") or "")
        query_type = str(query_profile.get("query_type") or "")
        visual_shapes = {
            "process_steps",
            "flow_description",
            "equipment_relation",
            "parameter_lookup",
            "parameter_table",
            "drawing_understanding",
            "material_flow",
            "source_location",
        }
        visual_query_types = {"process_flow", "graph_reasoning", "page_location", "exact_lookup", "metadata_lookup"}
        if answer_shape in visual_shapes or query_type in visual_query_types:
            return True
        return any(self._is_drawing_like_evidence(evidence) for evidence in evidences)

    def _is_drawing_like_evidence(self, evidence: Evidence) -> bool:
        metadata = evidence.metadata or {}
        source_text = " ".join(
            str(value or "").lower()
            for value in (
                evidence.source_type,
                evidence.retriever,
                evidence.drawing_no,
                metadata.get("source_type"),
                metadata.get("asset_type"),
                metadata.get("parser"),
                metadata.get("document_type"),
                metadata.get("layout_type"),
            )
        )
        return any(token in source_text for token in ("drawing", "image", "pdf_visual", "mineru_layout", "pfd", "pid", "p&id"))

    def _build_general_messages(self, question: str, query_profile: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你可以回答问候、身份说明、明显常识或简单公式问题。"
                    "不得声称答案来自知识库，不要编造项目资料、文件名、图号或引用。"
                    "如果问题涉及项目事实或专业资料，应提示需要知识库证据。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"question": question, "query_profile": query_profile}, ensure_ascii=False),
            },
        ]

    def _conflict_answer(self, question: str, evidences: list[Evidence], evidence_evaluation: dict[str, Any]) -> str:
        lines = [
            "检索到的资料之间存在冲突，当前无法基于知识库给出确定结论。",
            f"问题：{self._topic_text(question)}",
        ]
        conflict_ids = evidence_evaluation.get("conflict_evidence_ids") or []
        if conflict_ids:
            lines.append(f"冲突证据编号：{', '.join(str(item) for item in conflict_ids[:6])}")
        evidence_lines = self._evidence_excerpt_lines(evidences)
        if evidence_lines:
            lines.append("可展示的相关证据摘要：")
            lines.extend(evidence_lines)
        lines.append("建议优先核对资料版本、审核状态、来源优先级和发布日期后再确认。")
        return "\n".join(lines)

    def _refusal_answer(
        self,
        question: str,
        evidence_evaluation: dict[str, Any],
        query_profile: dict[str, Any],
    ) -> str:
        reason_code = self._refusal_reason_code(evidence_evaluation, query_profile)
        messages = {
            "no_project_evidence": "当前项目资料中未检索到相关有效信息，无法基于项目资料回答。",
            "conflict_evidence": "检索到的资料存在冲突，无法给出确定结论。",
            "permission_denied": "当前权限下没有可访问的相关资料，无法回答。",
            "invalid_question": "问题不明确或缺少有效业务含义，请补充项目、资料或具体对象。",
            "out_of_scope": "该问题超出当前知识库或项目范围，无法基于现有资料回答。",
            "unsafe_generalization": "该问题涉及项目事实，不能使用通用知识补答。",
        }
        detail = messages.get(reason_code, PROJECT_REFUSAL_TEXT)
        return f"{detail}\n拒答原因：{reason_code}\n问题：{self._topic_text(question)}"

    def _refusal_reason_code(self, evidence_evaluation: dict[str, Any], query_profile: dict[str, Any]) -> str:
        risk = str(evidence_evaluation.get("risk") or "")
        status = str(evidence_evaluation.get("evidence_status") or "")
        if risk == "permission_limited":
            return "permission_denied"
        if risk == "conflict" or status == "CONFLICTED":
            return "conflict_evidence"
        if str(query_profile.get("query_validity") or "") == "invalid":
            return "invalid_question"
        if risk == "irrelevant":
            return "out_of_scope"
        if risk == "unsafe_generalization":
            return "unsafe_generalization"
        return "no_project_evidence"

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
