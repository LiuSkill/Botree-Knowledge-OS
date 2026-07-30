"""页面和图片块的索引准入判定。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any


class IndexAdmissionStatus(StrEnum):
    TEXT_INDEXED = "text_indexed"
    VISUAL_INDEXED = "visual_indexed"
    METADATA_ONLY = "metadata_only"
    WAITING_CORRECTION = "waiting_correction"


@dataclass(frozen=True)
class AdmissionAssessment:
    has_visual_asset: bool
    candidate_text: str
    ocr_confidence: float = 0.0
    valid_character_ratio: float = 0.0
    reading_order_score: float = 0.0
    terminology_score: float = 0.0
    source_traceable: bool = False
    critical_failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndexAdmissionResult:
    status: IndexAdmissionStatus
    required_indexes: tuple[str, ...]
    quality_score: float
    reasons: tuple[str, ...]


class IndexAdmissionService:
    """综合评分决定文本准入，关键结构失真始终拥有否决权。"""

    TEXT_QUALITY_THRESHOLD = 0.72
    MIN_TEXT_LENGTH = 8

    QUALITY_FIELDS = ("ocr_confidence", "valid_character_ratio", "reading_order_score", "terminology_score")
    TRUSTED_NATIVE_PARSERS = frozenset({"simple_text"})
    TRUSTED_MINERU_SOURCE_KINDS = frozenset({"converted_pdf"})

    def apply_records(
        self,
        pages: list[Any],
        blocks: list[Any],
        assets: list[Any],
        *,
        parsed_pages: list[dict[str, Any]] | None = None,
        parser_name: str | None = None,
        source_kind: str | None = None,
    ) -> set[int]:
        """写回页/区域准入结论，并返回允许生成文本分块的页码。"""

        visual_page_ids = {asset.page_id for asset in assets if getattr(asset, "status", None) == "ready"}
        visual_block_ids = {
            asset.block_id
            for asset in assets
            if getattr(asset, "status", None) == "ready" and getattr(asset, "block_id", None) is not None
        }
        raw_by_page_no = {
            int(item.get("page_number") or item.get("page_no") or 0): item for item in (parsed_pages or [])
        }
        text_page_numbers: set[int] = set()
        for page in pages:
            result = self._assess_record(
                self._preferred_text(page, "clean_content", "page_text"),
                page.id in visual_page_ids,
                bool(getattr(page, "source_hash", None)),
                raw_by_page_no.get(int(page.page_no)),
                parser_name,
                source_kind,
            )
            self._write_result(page, result)
            if result.status is IndexAdmissionStatus.TEXT_INDEXED:
                text_page_numbers.add(int(page.page_no))
        for block in blocks:
            result = self._assess_record(
                self._preferred_text(block, "clean_text", "text"),
                block.id in visual_block_ids,
                True,
                self._json_dict(getattr(block, "metadata_json", None)),
                parser_name,
                source_kind,
            )
            self._write_result(block, result)
        return text_page_numbers

    def _assess_record(
        self,
        text: str,
        has_visual_asset: bool,
        source_traceable: bool,
        metadata: dict[str, Any] | None,
        parser_name: str | None,
        source_kind: str | None,
    ) -> IndexAdmissionResult:
        quality = self._quality_values(metadata)
        trusted_text_source = parser_name in self.TRUSTED_NATIVE_PARSERS or (
            parser_name == "mineru" and source_kind in self.TRUSTED_MINERU_SOURCE_KINDS
        )
        missing_quality = bool(text.strip()) and not trusted_text_source and quality is None
        scores = quality or ({name: 1.0 for name in self.QUALITY_FIELDS} if trusted_text_source and text.strip() else {})
        return self.assess(
            AdmissionAssessment(
                has_visual_asset=has_visual_asset,
                candidate_text=text,
                ocr_confidence=scores.get("ocr_confidence", 0.0),
                valid_character_ratio=scores.get("valid_character_ratio", 0.0),
                reading_order_score=scores.get("reading_order_score", 0.0),
                terminology_score=scores.get("terminology_score", 0.0),
                source_traceable=source_traceable,
                critical_failures=("quality_metrics_missing",) if missing_quality else (),
            )
        )

    def _quality_values(self, metadata: dict[str, Any] | None) -> dict[str, float] | None:
        if not metadata:
            return None
        candidate = metadata.get("quality") if isinstance(metadata.get("quality"), dict) else metadata
        values: dict[str, float] = {}
        for field in self.QUALITY_FIELDS:
            try:
                value = float(candidate[field])
            except (KeyError, TypeError, ValueError):
                return None
            values[field] = min(1.0, max(0.0, value))
        return values

    @staticmethod
    def _json_dict(value: object) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _preferred_text(record: Any, clean_attr: str, raw_attr: str) -> str:
        clean_value = getattr(record, clean_attr, None)
        if clean_value is not None:
            return str(clean_value)
        raw_value = getattr(record, raw_attr, None)
        return str(raw_value or "")

    def _write_result(self, record: Any, result: IndexAdmissionResult) -> None:
        record.index_admission_status = result.status.value
        record.index_admission_reason_json = json.dumps(list(result.reasons), ensure_ascii=False)
        record.text_quality_score = int(round(result.quality_score * 100))

    def assess(self, assessment: AdmissionAssessment) -> IndexAdmissionResult:
        quality_score = round(
            assessment.ocr_confidence * 0.35
            + assessment.valid_character_ratio * 0.25
            + assessment.reading_order_score * 0.20
            + assessment.terminology_score * 0.20,
            4,
        )
        reasons = list(assessment.critical_failures)
        text_eligible = bool(
            len(assessment.candidate_text.strip()) >= self.MIN_TEXT_LENGTH
            and assessment.source_traceable
            and quality_score >= self.TEXT_QUALITY_THRESHOLD
            and not assessment.critical_failures
        )
        if text_eligible:
            required = ("text", "visual") if assessment.has_visual_asset else ("text",)
            return IndexAdmissionResult(IndexAdmissionStatus.TEXT_INDEXED, required, quality_score, tuple(reasons))
        if assessment.has_visual_asset:
            if not assessment.candidate_text.strip():
                reasons.append("no_reliable_text")
            elif quality_score < self.TEXT_QUALITY_THRESHOLD:
                reasons.append("text_quality_below_threshold")
            return IndexAdmissionResult(IndexAdmissionStatus.VISUAL_INDEXED, ("visual",), quality_score, tuple(reasons))
        if not assessment.candidate_text.strip():
            reasons.append("no_indexable_content")
            return IndexAdmissionResult(IndexAdmissionStatus.METADATA_ONLY, ("metadata",), quality_score, tuple(reasons))
        if not assessment.source_traceable:
            reasons.append("source_untraceable")
            return IndexAdmissionResult(IndexAdmissionStatus.WAITING_CORRECTION, (), quality_score, tuple(reasons))
        reasons.append("text_quality_below_threshold")
        return IndexAdmissionResult(IndexAdmissionStatus.METADATA_ONLY, ("metadata",), quality_score, tuple(reasons))
