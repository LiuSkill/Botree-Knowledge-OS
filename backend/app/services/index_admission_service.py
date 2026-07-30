"""页面和图片块的索引准入判定。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import re
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
    MIN_INFERRED_TEXT_LENGTH = 24
    INFERRED_QUALITY_SOURCE = "mineru_original_pdf_heuristic"
    CODE_SYMBOLS = frozenset("=<>[]{}|_/\\~`@#$%^&*")
    TEXT_PUNCTUATION = frozenset(",.;:!?%()[]+-'\"&/，。；：！？（）《》【】、％")
    SENTENCE_ENDINGS = frozenset(".!?;:。！？；：")
    CODE_TOKEN_RE = re.compile(r"\b[A-Z]{1,4}(?:[-_/]?[0-9A-Z]{1,6})+\b")

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
            metadata = self._page_metadata(page, raw_by_page_no.get(int(page.page_no)))
            result, enriched_metadata = self._assess_record(
                self._preferred_text(page, "clean_content", "page_text"),
                page.id in visual_page_ids,
                bool(getattr(page, "source_hash", None)),
                metadata,
                parser_name,
                source_kind,
            )
            self._write_result(page, result)
            self._write_metadata(page, "cleaning_metadata_json", enriched_metadata)
            if result.status is IndexAdmissionStatus.TEXT_INDEXED:
                text_page_numbers.add(int(page.page_no))
        for block in blocks:
            metadata = self._json_dict(getattr(block, "metadata_json", None))
            result, enriched_metadata = self._assess_record(
                self._preferred_text(block, "clean_text", "text"),
                block.id in visual_block_ids,
                True,
                metadata,
                parser_name,
                source_kind,
            )
            self._write_result(block, result)
            self._write_metadata(block, "metadata_json", enriched_metadata)
        return text_page_numbers

    def _assess_record(
        self,
        text: str,
        has_visual_asset: bool,
        source_traceable: bool,
        metadata: dict[str, Any] | None,
        parser_name: str | None,
        source_kind: str | None,
    ) -> tuple[IndexAdmissionResult, dict[str, Any] | None]:
        quality = self._quality_values(metadata)
        enriched_metadata = dict(metadata) if metadata else None
        if quality is None:
            inferred_quality = self._infer_quality_values(text, metadata, parser_name, source_kind)
            if inferred_quality is not None:
                quality = inferred_quality
                enriched_metadata = self._merge_quality_metadata(metadata, inferred_quality, inferred=True)
        trusted_text_source = parser_name in self.TRUSTED_NATIVE_PARSERS or (
            parser_name == "mineru" and source_kind in self.TRUSTED_MINERU_SOURCE_KINDS
        )
        missing_quality = bool(text.strip()) and not trusted_text_source and quality is None
        scores = quality or ({name: 1.0 for name in self.QUALITY_FIELDS} if trusted_text_source and text.strip() else {})
        return (
            self.assess(
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
            ,
            enriched_metadata,
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
            values[field] = self._clamp_score(value)
        return values

    def _infer_quality_values(
        self,
        text: str,
        metadata: dict[str, Any] | None,
        parser_name: str | None,
        source_kind: str | None,
    ) -> dict[str, float] | None:
        if parser_name != "mineru" or source_kind != "original":
            return None
        return self._infer_original_pdf_quality(text, metadata)

    def _infer_original_pdf_quality(self, text: str, metadata: dict[str, Any] | None) -> dict[str, float] | None:
        if metadata and metadata.get("removed_as_toc") is True:
            return None
        lines = [line.strip() for line in text.splitlines() if line and line.strip()]
        compact_length = len("".join(lines))
        if compact_length < self.MIN_INFERRED_TEXT_LENGTH or not lines:
            return None

        total_chars = 0
        valid_chars = 0
        wordish_chars = 0
        sentence_like_lines = 0
        long_lines = 0
        dense_lines = 0
        code_like_lines = 0
        for line in lines:
            line_total = 0
            line_valid = 0
            line_wordish = 0
            for char in line:
                if char.isspace():
                    continue
                line_total += 1
                if self._is_valid_text_char(char):
                    line_valid += 1
                if self._is_wordish_char(char):
                    line_wordish += 1
            total_chars += line_total
            valid_chars += line_valid
            wordish_chars += line_wordish
            if len(line) >= 18:
                long_lines += 1
            if line_wordish >= 8:
                dense_lines += 1
            if self._looks_sentence_like(line):
                sentence_like_lines += 1
            if self._is_code_like_line(line):
                code_like_lines += 1

        if total_chars == 0:
            return None

        line_count = len(lines)
        valid_ratio = valid_chars / total_chars
        wordish_ratio = wordish_chars / total_chars
        long_line_ratio = long_lines / line_count
        dense_line_ratio = dense_lines / line_count
        sentence_ratio = sentence_like_lines / line_count
        code_like_ratio = code_like_lines / line_count

        removed_line_count = self._int_metadata(metadata, "removed_line_count")
        removed_block_count = self._int_metadata(metadata, "removed_block_count")
        retained_line_ratio = line_count / max(1, line_count + removed_line_count)
        retained_block_ratio = line_count / max(1, line_count + removed_block_count)
        repeated_edge_penalty = 0.05 if metadata and metadata.get("repeated_edge_noise_applied") else 0.0

        return {
            "ocr_confidence": self._clamp_score(
                0.50
                + valid_ratio * 0.30
                + dense_line_ratio * 0.10
                + long_line_ratio * 0.08
                - code_like_ratio * 0.25
                - repeated_edge_penalty
            ),
            "valid_character_ratio": self._clamp_score(valid_ratio),
            "reading_order_score": self._clamp_score(
                0.42
                + retained_line_ratio * 0.20
                + retained_block_ratio * 0.10
                + long_line_ratio * 0.14
                + sentence_ratio * 0.10
                - code_like_ratio * 0.30
                - repeated_edge_penalty
            ),
            "terminology_score": self._clamp_score(
                0.38
                + wordish_ratio * 0.24
                + dense_line_ratio * 0.18
                + sentence_ratio * 0.12
                - code_like_ratio * 0.22
            ),
        }

    def _merge_quality_metadata(
        self,
        metadata: dict[str, Any] | None,
        quality: dict[str, float],
        *,
        inferred: bool,
    ) -> dict[str, Any]:
        enriched = dict(metadata or {})
        enriched["quality"] = {field: self._clamp_score(quality[field]) for field in self.QUALITY_FIELDS}
        if inferred:
            enriched["quality_inference"] = {
                "inferred": True,
                "source": self.INFERRED_QUALITY_SOURCE,
            }
        return enriched

    def _page_metadata(self, page: Any, raw_page: dict[str, Any] | None) -> dict[str, Any] | None:
        metadata = dict(self._json_dict(getattr(page, "cleaning_metadata_json", None)) or {})
        if isinstance(raw_page, dict):
            cleaning_metadata = raw_page.get("cleaning_metadata")
            if isinstance(cleaning_metadata, dict):
                metadata.update(cleaning_metadata)
            quality = raw_page.get("quality")
            if isinstance(quality, dict):
                metadata["quality"] = quality
        return metadata or None

    def _write_metadata(self, record: Any, attr_name: str, metadata: dict[str, Any] | None) -> None:
        if metadata is None:
            return
        setattr(record, attr_name, json.dumps(metadata, ensure_ascii=False))

    @classmethod
    def _int_metadata(cls, metadata: dict[str, Any] | None, key: str) -> int:
        if not metadata:
            return 0
        try:
            return max(0, int(metadata.get(key, 0)))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _looks_sentence_like(cls, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if stripped[-1] in cls.SENTENCE_ENDINGS:
            return True
        return len(stripped) >= 24 and any(char in cls.TEXT_PUNCTUATION for char in stripped)

    @classmethod
    def _is_code_like_line(cls, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        non_space_length = sum(1 for char in stripped if not char.isspace())
        wordish_count = sum(1 for char in stripped if cls._is_wordish_char(char))
        symbol_count = sum(1 for char in stripped if char in cls.CODE_SYMBOLS)
        if wordish_count == 0 and symbol_count >= 2:
            return True
        if non_space_length <= 40 and symbol_count >= 4 and symbol_count / max(1, non_space_length) >= 0.14:
            return True
        if cls.CODE_TOKEN_RE.search(stripped) and len(stripped) <= 28 and not cls._looks_sentence_like(stripped):
            return True
        if stripped.count("|") >= 2 and len(stripped) <= 40:
            return True
        return False

    @classmethod
    def _is_valid_text_char(cls, char: str) -> bool:
        return cls._is_wordish_char(char) or char in cls.TEXT_PUNCTUATION

    @staticmethod
    def _is_wordish_char(char: str) -> bool:
        return char.isalnum() or "\u4e00" <= char <= "\u9fff"

    @staticmethod
    def _clamp_score(value: float) -> float:
        return min(1.0, max(0.0, float(value)))

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
