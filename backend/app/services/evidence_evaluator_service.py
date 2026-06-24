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
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvidenceEvaluatorService:
    """基于确定性规则评估证据强弱。"""

    _CONFLICT_HINTS = ("conflict", "contradict", "冲突", "矛盾", "不一致")
    _IRRELEVANT_HINTS = ("irrelevant", "无关", "不相关")
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
    ) -> EvidenceEvaluation:
        """输出新证据状态和缺失项。"""

        judgement = judgement or {}
        reason = str(judgement.get("reason") or "")
        lowered_reason = reason.lower()
        if any(hint in lowered_reason or hint in reason for hint in self._CONFLICT_HINTS):
            strong_count, weak_count = self._count_evidence_strength(evidences)
            return EvidenceEvaluation(
                evidence_status=EvidenceStatus.CONFLICTED.value,
                weak_evidence_count=weak_count,
                strong_evidence_count=strong_count,
                missing_aspects=self._missing_aspects(resolved_task_type, answer_shape),
                should_retry=False,
                allow_limited_answer=strong_count > 0,
                reason=reason or "证据之间存在冲突",
            )

        if not evidences or any(hint in lowered_reason or hint in reason for hint in self._IRRELEVANT_HINTS):
            return EvidenceEvaluation(
                evidence_status=EvidenceStatus.EMPTY.value,
                weak_evidence_count=0,
                strong_evidence_count=0,
                missing_aspects=self._missing_aspects(resolved_task_type, answer_shape),
                should_retry=self._has_retry_suggestion(judgement),
                allow_limited_answer=False,
                reason=reason or "未检索到有效证据",
            )

        strong_count, weak_count = self._count_evidence_strength(evidences)
        if strong_count <= 0 and weak_count <= 0:
            status = EvidenceStatus.EMPTY
        elif strong_count <= 0:
            status = EvidenceStatus.WEAK_ONLY
        elif judgement.get("enough") is True:
            status = EvidenceStatus.ENOUGH
        else:
            status = EvidenceStatus.PARTIAL

        missing_aspects = [] if status == EvidenceStatus.ENOUGH else self._missing_aspects(resolved_task_type, answer_shape)
        return EvidenceEvaluation(
            evidence_status=status.value,
            weak_evidence_count=weak_count,
            strong_evidence_count=strong_count,
            missing_aspects=missing_aspects,
            should_retry=status in {EvidenceStatus.EMPTY, EvidenceStatus.WEAK_ONLY, EvidenceStatus.PARTIAL}
            and self._has_retry_suggestion(judgement),
            allow_limited_answer=status in {EvidenceStatus.WEAK_ONLY, EvidenceStatus.PARTIAL},
            reason=self._evaluation_reason(status, strong_count, weak_count, reason),
        )

    def _count_evidence_strength(self, evidences: list[Evidence]) -> tuple[int, int]:
        strong_count = 0
        weak_count = 0
        for evidence in evidences:
            if self._is_weak_evidence(evidence):
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
