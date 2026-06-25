"""Evidence evaluator service.

负责：
1. 将检索证据划分为空、弱证据、部分证据、充分证据和冲突证据。
2. 输出 AnswerPolicyGate 可直接消费的证据状态与缺失项。
3. 保守区分标题/页眉等弱证据和正文/流程/参数等强证据，避免弱证据被误当项目事实。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from app.retrieval.query_utils import boilerplate_multiplier, normalize_query_text
from app.retrieval.schemas import Evidence


class EvidenceStatus(str, Enum):
    """答案门控使用的新证据状态。"""

    EMPTY = "EMPTY"
    WEAK_ONLY = "WEAK_ONLY"
    PARTIAL = "PARTIAL"
    ENOUGH = "ENOUGH"
    CONFLICTED = "CONFLICTED"


@dataclass(frozen=True)
class EvidenceEvaluation:
    """证据评估结果。"""

    evidence_status: str
    weak_evidence_count: int
    strong_evidence_count: int
    missing_aspects: list[str] = field(default_factory=list)
    should_retry: bool = False
    allow_limited_answer: bool = False
    confidence: float = 0.0
    relevance: str = "none"
    support_level: str = "none"
    conflict: bool = False
    conflict_evidence_ids: list[int] = field(default_factory=list)
    answerable_parts: list[str] = field(default_factory=list)
    risk: str = "none"
    content_strength: str = "none"
    query_support: str = "none"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvidenceEvaluatorService:
    """基于确定性规则评估证据强弱。"""

    _LEVELS = {"none": 0, "weak": 1, "partial": 2, "full": 3}
    _TITLE_HINTS = (
        "title",
        "图名",
        "图纸名称",
        "封面",
        "cover",
        "p&id",
        "pid",
        "pfd",
        "process flow diagram",
        "piping & instrumentation diagram",
        "raw material & chemical feeding",
        "black mass feeding",
    )
    _HEADER_HINTS = (
        "co., ltd",
        "company",
        "公司",
        "有限公司",
        "project",
        "项目名称",
        "页眉",
        "页脚",
        "page",
        "revision",
    )
    _TABLE_HEADER_HINTS = ("序号", "名称", "编号", "位号", "规格", "单位", "备注", "description", "item", "unit")
    _PROCESS_HINTS = (
        "流程",
        "步骤",
        "首先",
        "然后",
        "经",
        "经过",
        "通过",
        "送至",
        "进入",
        "流向",
        "来自",
        "排至",
        "返回",
        "连接",
        "上游",
        "下游",
        "入口",
        "出口",
        "浸出",
        "过滤",
        "压滤",
        "离心",
        "沉淀",
        "萃取",
        "反萃",
        "from",
        "to",
        "into",
        "outlet",
        "inlet",
        "feed",
        "discharge",
        "overflow",
        "underflow",
    )
    _EQUIPMENT_HINTS = ("泵", "槽", "罐", "釜", "塔", "阀", "管线", "离心机", "压滤机", "过滤器", "反应器")
    _PARAMETER_PATTERN = re.compile(
        r"\d+(?:\.\d+)?\s*(?:℃|°c|tpa|kt/a|m3|m³|kg|g/l|mg/l|%|wt%|ph|bar|mpa|kpa|rpm|h\b|m/s|l/s)",
        re.IGNORECASE,
    )
    _TAG_PATTERN = re.compile(r"\b[A-Z]{1,6}[-_]?\d{2,}[A-Z0-9_-]*\b", re.IGNORECASE)

    def evaluate(
        self,
        *,
        question: str,
        evidences: list[Evidence],
        judgement: dict[str, Any] | None = None,
        resolved_task_type: str | None = None,
        answer_shape: str | None = None,
        query_profile: dict[str, Any] | None = None,
    ) -> EvidenceEvaluation:
        """输出新证据状态和缺失项。"""

        judgement = judgement or {}
        reason = str(judgement.get("reason") or "")
        metadata_lookup = self._is_metadata_lookup(question, resolved_task_type, answer_shape, query_profile)
        drawing_context = self._is_drawing_question(resolved_task_type, answer_shape, query_profile)
        strong_count, weak_count = self._count_evidence_strength(
            evidences,
            metadata_lookup=metadata_lookup,
            drawing_context=drawing_context,
        )
        confidence_default = 0.72 if judgement.get("enough") is True and judgement.get("confidence") is None else 0.0
        confidence = self._confidence(judgement.get("confidence"), default=confidence_default)
        relevance = self._support_level(judgement.get("relevance"), default=self._legacy_relevance(judgement, evidences, strong_count))
        support_level = self._support_level(
            judgement.get("support_level"),
            default=self._legacy_support_level(judgement, evidences, strong_count, metadata_lookup),
        )
        conflict = bool(judgement.get("conflict") is True or str(judgement.get("risk") or "") == "conflict")
        conflict_evidence_ids = self._int_list(judgement.get("conflict_evidence_ids"))
        answerable_parts = self._string_list(judgement.get("answerable_parts"))
        judged_missing_aspects = self._string_list(judgement.get("missing_aspects"))
        generated_missing_aspects = self._missing_aspects(resolved_task_type, answer_shape)
        missing_aspects = judged_missing_aspects or generated_missing_aspects
        risk = self._risk(judgement.get("risk"))

        if conflict:
            return EvidenceEvaluation(
                evidence_status=EvidenceStatus.CONFLICTED.value,
                weak_evidence_count=weak_count,
                strong_evidence_count=strong_count,
                missing_aspects=missing_aspects,
                should_retry=False,
                allow_limited_answer=strong_count > 0,
                confidence=confidence,
                relevance=relevance,
                support_level=support_level,
                conflict=True,
                conflict_evidence_ids=conflict_evidence_ids,
                answerable_parts=answerable_parts,
                risk="conflict",
                content_strength=self._content_strength(strong_count, weak_count),
                query_support=support_level,
                reason=reason or "结构化证据判断标记 conflict=true",
            )

        if not evidences or relevance == "none" or support_level == "none":
            return EvidenceEvaluation(
                evidence_status=EvidenceStatus.EMPTY.value,
                weak_evidence_count=0,
                strong_evidence_count=0,
                missing_aspects=missing_aspects,
                should_retry=self._has_retry_suggestion(judgement),
                allow_limited_answer=False,
                confidence=confidence,
                relevance=relevance,
                support_level=support_level,
                conflict=False,
                conflict_evidence_ids=[],
                answerable_parts=answerable_parts,
                risk=risk if risk != "none" else "irrelevant" if evidences else "insufficient_coverage",
                content_strength=self._content_strength(strong_count, weak_count),
                query_support=support_level,
                reason=reason or "结构化证据判断显示无相关支撑",
            )

        if strong_count <= 0 and weak_count <= 0:
            status = EvidenceStatus.EMPTY
        elif strong_count <= 0:
            status = EvidenceStatus.WEAK_ONLY
        elif relevance == "full" and support_level == "full" and judgement.get("enough") is True:
            status = self._status_for_enough_with_confidence(
                confidence,
                strong_count=strong_count,
                weak_count=weak_count,
                missing_aspects=judged_missing_aspects,
                metadata_lookup=metadata_lookup,
            )
        else:
            status = EvidenceStatus.PARTIAL

        if status == EvidenceStatus.ENOUGH:
            missing_aspects = []
        return EvidenceEvaluation(
            evidence_status=status.value,
            weak_evidence_count=weak_count,
            strong_evidence_count=strong_count,
            missing_aspects=missing_aspects,
            should_retry=status in {EvidenceStatus.EMPTY, EvidenceStatus.WEAK_ONLY, EvidenceStatus.PARTIAL}
            and self._has_retry_suggestion(judgement),
            allow_limited_answer=status in {EvidenceStatus.WEAK_ONLY, EvidenceStatus.PARTIAL},
            confidence=confidence,
            relevance=relevance,
            support_level=support_level,
            conflict=False,
            conflict_evidence_ids=[],
            answerable_parts=answerable_parts,
            risk=risk if status == EvidenceStatus.ENOUGH else self._risk_for_status(status, risk),
            content_strength=self._content_strength(strong_count, weak_count),
            query_support=support_level,
            reason=self._evaluation_reason(status, strong_count, weak_count, reason),
        )

    def _count_evidence_strength(
        self,
        evidences: list[Evidence],
        *,
        metadata_lookup: bool = False,
        drawing_context: bool = False,
    ) -> tuple[int, int]:
        strong_count = 0
        weak_count = 0
        for evidence in evidences:
            if metadata_lookup and self._is_metadata_evidence(evidence):
                strong_count += 1
            elif drawing_context and self._is_drawing_evidence(evidence):
                strong_count += 1
            elif self._is_weak_evidence(evidence):
                weak_count += 1
            elif self._is_strong_evidence(evidence):
                strong_count += 1
            else:
                weak_count += 1
        return strong_count, weak_count

    def _is_weak_evidence(self, evidence: Evidence) -> bool:
        content = str(evidence.content or "").strip()
        if not content:
            return True
        normalized = normalize_query_text(content).lower()
        if evidence.metadata.get("metadata_only"):
            return True
        if boilerplate_multiplier(content) < 0.45:
            return True
        if self._looks_like_table_header_only(normalized):
            return True
        if self._looks_like_title_or_header_only(normalized):
            return True
        return False

    def _is_strong_evidence(self, evidence: Evidence) -> bool:
        content = str(evidence.content or "").strip()
        if not content:
            return False
        normalized = normalize_query_text(content).lower()
        metadata = evidence.metadata or {}
        if metadata.get("relation_id") or metadata.get("relation_type"):
            return True
        if any(metadata.get(key) for key in ("visual_summary", "parsed_visual_evidence", "material_connections")):
            return True
        if self._is_drawing_evidence(evidence) and any(hint in normalized for hint in self._PROCESS_HINTS):
            return True
        if self._PARAMETER_PATTERN.search(normalized):
            return True
        if self._TAG_PATTERN.search(content) and any(hint in normalized for hint in self._PROCESS_HINTS):
            return True
        if any(arrow in content for arrow in ("->", "→", "-->")):
            return True
        has_process = any(hint in normalized for hint in self._PROCESS_HINTS)
        has_equipment = any(hint in normalized for hint in self._EQUIPMENT_HINTS)
        if has_process and has_equipment and len(normalized) >= 30:
            return True
        if (has_process or has_equipment) and len(normalized) >= 80:
            return True
        if len(normalized) >= 180 and any(mark in content for mark in ("。", "；", ";", "\n")):
            return True
        return False

    def _looks_like_table_header_only(self, normalized: str) -> bool:
        if not any(hint in normalized for hint in self._TABLE_HEADER_HINTS):
            return False
        has_number = bool(re.search(r"\d", normalized))
        return not has_number and len(normalized) <= 160

    def _looks_like_title_or_header_only(self, normalized: str) -> bool:
        if len(normalized) > 220:
            return False
        title_or_header = any(hint in normalized for hint in self._TITLE_HINTS + self._HEADER_HINTS)
        if not title_or_header:
            return False
        has_flow_detail = any(hint in normalized for hint in self._PROCESS_HINTS) and (
            self._PARAMETER_PATTERN.search(normalized) or any(token in normalized for token in ("进入", "送至", "连接", "from", " to "))
        )
        return not has_flow_detail

    def _has_retry_suggestion(self, judgement: dict[str, Any]) -> bool:
        return bool(judgement.get("suggested_retrievers") or judgement.get("suggested_queries"))

    def _support_level(self, raw_value: Any, default: str) -> str:
        value = str(raw_value or "").strip().lower()
        if value in self._LEVELS:
            return value
        return default if default in self._LEVELS else "none"

    def _confidence(self, raw_value: Any, default: float) -> float:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return default
        return max(0.0, min(1.0, value))

    def _legacy_relevance(self, judgement: dict[str, Any], evidences: list[Evidence], strong_count: int) -> str:
        if not evidences:
            return "none"
        if judgement.get("enough") is True:
            return "full"
        return "partial" if strong_count > 0 else "weak"

    def _legacy_support_level(
        self,
        judgement: dict[str, Any],
        evidences: list[Evidence],
        strong_count: int,
        metadata_lookup: bool,
    ) -> str:
        if not evidences:
            return "none"
        if judgement.get("enough") is True and (strong_count > 0 or metadata_lookup):
            return "full"
        return "partial" if strong_count > 0 else "weak"

    def _status_for_enough_with_confidence(
        self,
        confidence: float,
        *,
        strong_count: int,
        weak_count: int,
        missing_aspects: list[str],
        metadata_lookup: bool,
    ) -> EvidenceStatus:
        if confidence < 0.5:
            return EvidenceStatus.PARTIAL
        if confidence >= 0.7:
            return EvidenceStatus.ENOUGH
        if missing_aspects:
            return EvidenceStatus.PARTIAL
        if metadata_lookup and strong_count >= 1:
            return EvidenceStatus.ENOUGH
        if strong_count >= 2:
            return EvidenceStatus.ENOUGH
        if strong_count >= 1 and weak_count >= 1:
            return EvidenceStatus.ENOUGH
        return EvidenceStatus.PARTIAL

    def _risk(self, raw_value: Any) -> str:
        allowed = {"none", "insufficient_coverage", "weak_evidence", "conflict", "irrelevant", "permission_limited"}
        value = str(raw_value or "none").strip().lower()
        return value if value in allowed else "none"

    def _risk_for_status(self, status: EvidenceStatus, risk: str) -> str:
        if risk != "none":
            return risk
        if status == EvidenceStatus.WEAK_ONLY:
            return "weak_evidence"
        if status == EvidenceStatus.PARTIAL:
            return "insufficient_coverage"
        if status == EvidenceStatus.EMPTY:
            return "irrelevant"
        return "none"

    def _content_strength(self, strong_count: int, weak_count: int) -> str:
        if strong_count > 0:
            return "strong"
        if weak_count > 0:
            return "weak"
        return "none"

    def _string_list(self, raw_value: Any) -> list[str]:
        if not isinstance(raw_value, list):
            return []
        result: list[str] = []
        for item in raw_value:
            text = str(item or "").strip()
            if text and text not in result:
                result.append(text[:180])
        return result[:8]

    def _int_list(self, raw_value: Any) -> list[int]:
        if not isinstance(raw_value, list):
            return []
        result: list[int] = []
        for item in raw_value:
            try:
                value = int(item)
            except (TypeError, ValueError):
                continue
            if value > 0 and value not in result:
                result.append(value)
        return result[:12]

    def _is_metadata_lookup(
        self,
        question: str,
        task_type: str | None,
        answer_shape: str | None,
        query_profile: dict[str, Any] | None,
    ) -> bool:
        profile = query_profile or {}
        query_type = str(profile.get("query_type") or "")
        shape = str(answer_shape or profile.get("answer_shape") or "")
        task = str(task_type or "")
        if task in {"document_location", "metadata_lookup"} or shape == "source_location":
            return True
        if query_type in {"metadata_lookup", "page_location", "document_location"}:
            return True
        question_text = normalize_query_text(question).lower()
        return any(
            token in question_text
            for token in (
                "文件名",
                "项目名",
                "项目名称",
                "图纸编号",
                "图号",
                "版本号",
                "版本",
                "资料是否存在",
                "是否存在",
                "哪张图",
                "第几页",
                "page",
                "drawing no",
                "revision",
            )
        )

    def _is_drawing_question(
        self,
        task_type: str | None,
        answer_shape: str | None,
        query_profile: dict[str, Any] | None,
    ) -> bool:
        profile = query_profile or {}
        query_type = str(profile.get("query_type") or task_type or "")
        shape = str(answer_shape or profile.get("answer_shape") or "")
        return query_type in {
            "process_flow",
            "graph_reasoning",
            "page_location",
            "exact_lookup",
            "metadata_lookup",
        } or shape in {
            "process_steps",
            "flow_description",
            "equipment_relation",
            "parameter_lookup",
            "parameter_table",
            "drawing_understanding",
            "material_flow",
            "source_location",
        }

    def _is_metadata_evidence(self, evidence: Evidence) -> bool:
        metadata = evidence.metadata or {}
        if metadata.get("metadata_only") or metadata.get("document_version") or metadata.get("version_no"):
            return True
        if evidence.file_name or evidence.drawing_no or evidence.page_number is not None:
            return True
        normalized = normalize_query_text(evidence.content or "").lower()
        return self._looks_like_title_or_header_only(normalized) or any(
            token in normalized for token in ("revision", "drawing no", "document no", "项目名称", "图纸名称", "图号")
        )

    def _is_drawing_evidence(self, evidence: Evidence) -> bool:
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
        return bool(evidence.assets) or any(
            token in source_text for token in ("drawing", "image", "pdf_visual", "mineru_layout", "pfd", "pid", "p&id")
        )

    def _missing_aspects(self, task_type: str | None, answer_shape: str | None) -> list[str]:
        task = str(task_type or "")
        shape = str(answer_shape or "")
        if task == "process_flow" or shape == "process_steps":
            return ["流程步骤", "上下游关系", "物料流向"]
        if task == "parameter_lookup" or shape == "parameter_table":
            return ["参数值", "单位", "适用对象或工况"]
        if task == "document_location" or shape == "source_location":
            return ["图号", "页码", "原文定位"]
        if task == "project_overview" or shape == "project_summary":
            return ["项目概况", "建设内容", "设计依据", "处理规模"]
        if task == "comparison" or shape == "comparison_table":
            return ["对比对象", "对比维度", "正文依据"]
        return ["可支撑回答的正文证据"]

    def _evaluation_reason(self, status: EvidenceStatus, strong_count: int, weak_count: int, judgement_reason: str) -> str:
        base = f"强证据 {strong_count} 条，弱证据 {weak_count} 条，状态 {status.value}"
        if judgement_reason:
            return f"{base}；原始证据判断：{judgement_reason}"
        return base
