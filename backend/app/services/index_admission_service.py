"""页面与视觉资产的索引准入判定。"""

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


@dataclass(frozen=True)
class VisualAdmissionDecision:
    accepted: bool
    category: str
    priority_score: int
    reasons: tuple[str, ...]
    source_file_name: str | None
    asset_file_name: str | None
    page_title: str | None
    figure_title: str | None
    adjacent_texts: tuple[str, ...]
    context_text: str


class IndexAdmissionService:
    """综合评估文本与视觉资产是否允许进入索引。"""

    TEXT_QUALITY_THRESHOLD = 0.72
    MIN_TEXT_LENGTH = 8
    MIN_INFERRED_TEXT_LENGTH = 24
    INFERRED_QUALITY_SOURCE = "mineru_original_pdf_heuristic"
    CODE_SYMBOLS = frozenset("=<>[]{}|_/\\~`@#$%^&*")
    TEXT_PUNCTUATION = frozenset(",.;:!?%()[]+-'\"&/，。；：！？（）《》【】、？")
    SENTENCE_ENDINGS = frozenset(".!?;:。！？；：")
    CODE_TOKEN_RE = re.compile(r"\b[A-Z]{1,4}(?:[-_/]?[0-9A-Z]{1,6})+\b")

    QUALITY_FIELDS = ("ocr_confidence", "valid_character_ratio", "reading_order_score", "terminology_score")
    TRUSTED_NATIVE_PARSERS = frozenset({"simple_text"})
    TRUSTED_MINERU_SOURCE_KINDS = frozenset({"converted_pdf"})

    VISUAL_ASSET_TYPES = frozenset({"page_preview", "block_image"})
    VISUAL_TITLE_KEYS = (
        "figure_title",
        "table_caption",
        "table_title",
        "caption",
        "title",
        "name",
        "image_name",
        "img_name",
        "label",
    )
    VISUAL_EXCLUDED_FILTER_REASONS = frozenset(
        {
            "document_control_table",
            "signature_control_block",
            "revision_history_table",
            "header",
            "footer",
            "page_header",
            "page_footer",
        }
    )
    VISUAL_EXCLUDED_HINTS = (
        "logo",
        "页眉",
        "页脚",
        "header",
        "footer",
        "印章",
        "stamp",
        "seal",
        "签章",
        "签字",
        "盖章",
    )
    VISUAL_FLOW_HINTS = (
        "p&id",
        "pid",
        "pfd",
        "process flow",
        "flow diagram",
        "flowsheet",
        "schematic",
        "流程图",
        "工艺流程",
        "实验流程",
        "浸出流程",
        "工序流程",
        "工作流程",
        "流程框图",
        "流程简图",
        "流程示意",
        "流程说明",
        "管道仪表",
        "系统图",
    )
    VISUAL_EQUIPMENT_HINTS = (
        "equipment",
        "layout",
        "arrangement",
        "reactor",
        "pump",
        "tank",
        "vessel",
        "filter",
        "tower",
        "dryer",
        "设备图",
        "设备布置",
        "布置图",
        "装配图",
        "结构图",
        "泵",
        "槽",
        "罐",
        "反应釜",
        "过滤机",
        "塔",
    )
    VISUAL_CURVE_HINTS = (
        "curve",
        "chart",
        "graph",
        "plot",
        "trend",
        "曲线",
        "趋势图",
        "折线图",
        "散点图",
        "柱状图",
    )
    VISUAL_TABLE_HINTS = (
        "table ",
        "table-",
        "table_",
        "表",
        "数据表",
        "结果表",
        "table caption",
    )
    VISUAL_GENERIC_HINTS = (
        "diagram",
        "drawing",
        "illustration",
        "photo",
        "image",
        "picture",
        "附图",
        "照片",
        "图片",
        "参考图片",
        "现场照片",
        "现场图",
        "外形图",
        "外观图",
        "配管图",
        "基础图",
        "安装图",
        "程序图",
        "工作程序图",
        "结构图",
        "布置图",
        "原理图",
        "简图",
        "框图",
        "示意图",
        "图纸",
        "总图",
    )
    VISUAL_CATEGORY_PRIORITY = {
        "flow_diagram": 420,
        "equipment_diagram": 360,
        "curve_chart": 320,
        "table_snapshot": 280,
        "generic_visual": 140,
        "excluded": 0,
        "rejected": 0,
    }
    VISUAL_MAX_CONTEXT_CHARS = 180
    VISUAL_TITLE_MAX_CHARS = 64
    VISUAL_NAMED_TITLE_HINTS = (
        "流程图",
        "工艺流程",
        "实验流程",
        "浸出流程",
        "工序流程",
        "工作流程",
        "流程框图",
        "流程简图",
        "附图",
        "照片",
        "图片",
        "参考图片",
        "现场照片",
        "现场图",
        "外形图",
        "外观图",
        "配管图",
        "基础图",
        "安装图",
        "程序图",
        "工作程序图",
        "结构图",
        "布置图",
        "原理图",
        "示意图",
        "简图",
        "框图",
        "总图",
        "photo",
        "image",
        "picture",
    )

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
        """写回页/块/视觉资产的准入结论，并返回允许生成文本 chunk 的页码。"""

        page_by_id = {int(page.id): page for page in pages if getattr(page, "id", None) is not None}
        block_by_id: dict[int, Any] = {}
        blocks_by_page: dict[int, list[Any]] = {}
        for block in blocks:
            block_id = getattr(block, "id", None)
            page_id = getattr(block, "page_id", None)
            if block_id is None or page_id is None:
                continue
            block_by_id[int(block_id)] = block
            blocks_by_page.setdefault(int(page_id), []).append(block)
        neighbor_by_block_id: dict[int, tuple[int | None, int | None]] = {}
        for page_blocks in blocks_by_page.values():
            ordered_blocks = sorted(page_blocks, key=lambda item: int(getattr(item, "block_index", 0) or 0))
            for index, block in enumerate(ordered_blocks):
                previous = ordered_blocks[index - 1] if index > 0 else None
                following = ordered_blocks[index + 1] if index + 1 < len(ordered_blocks) else None
                neighbor_by_block_id[int(block.id)] = (
                    int(previous.id) if previous is not None else None,
                    int(following.id) if following is not None else None,
                )

        visual_asset_decisions = self.apply_visual_admission(
            assets,
            page_by_id=page_by_id,
            block_by_id=block_by_id,
            neighbor_by_block_id=neighbor_by_block_id,
        )
        visual_page_ids = {
            getattr(asset, "page_id", None)
            for asset, decision in visual_asset_decisions.values()
            if decision.accepted and getattr(asset, "page_id", None) is not None
        }
        visual_block_ids = {
            getattr(asset, "block_id", None)
            for asset, decision in visual_asset_decisions.values()
            if decision.accepted and getattr(asset, "block_id", None) is not None
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

    def apply_visual_admission(
        self,
        assets: list[Any],
        *,
        page_by_id: dict[int, Any],
        block_by_id: dict[int, Any],
        neighbor_by_block_id: dict[int, tuple[int | None, int | None]],
    ) -> dict[int, tuple[Any, VisualAdmissionDecision]]:
        decisions = self.assess_visual_admission(
            assets,
            page_by_id=page_by_id,
            block_by_id=block_by_id,
            neighbor_by_block_id=neighbor_by_block_id,
        )
        for asset, decision in decisions.values():
            metadata = dict(self._json_dict(getattr(asset, "metadata_json", None)) or {})
            metadata["visual_admission"] = self._visual_admission_payload(decision)
            self._write_metadata(asset, "metadata_json", metadata)
        return decisions

    def assess_visual_admission(
        self,
        assets: list[Any],
        *,
        page_by_id: dict[int, Any],
        block_by_id: dict[int, Any],
        neighbor_by_block_id: dict[int, tuple[int | None, int | None]],
    ) -> dict[int, tuple[Any, VisualAdmissionDecision]]:
        return self._assess_visual_assets(
            assets,
            page_by_id=page_by_id,
            block_by_id=block_by_id,
            neighbor_by_block_id=neighbor_by_block_id,
        )

    def _assess_visual_assets(
        self,
        assets: list[Any],
        *,
        page_by_id: dict[int, Any],
        block_by_id: dict[int, Any],
        neighbor_by_block_id: dict[int, tuple[int | None, int | None]],
    ) -> dict[int, tuple[Any, VisualAdmissionDecision]]:
        decisions: dict[int, tuple[Any, VisualAdmissionDecision]] = {}
        admitted_visual_block_pages: set[int] = set()

        ready_visual_assets = [
            asset
            for asset in assets
            if getattr(asset, "status", None) == "ready"
            and str(getattr(asset, "asset_type", "") or "") in self.VISUAL_ASSET_TYPES
        ]
        block_assets = [asset for asset in ready_visual_assets if getattr(asset, "block_id", None) is not None]
        page_assets = [asset for asset in ready_visual_assets if getattr(asset, "block_id", None) is None]

        for asset in block_assets:
            decision = self._assess_visual_asset(
                asset,
                page_by_id=page_by_id,
                block_by_id=block_by_id,
                neighbor_by_block_id=neighbor_by_block_id,
                page_has_admitted_visual_block=False,
            )
            decisions[id(asset)] = (asset, decision)
            if decision.accepted and getattr(asset, "page_id", None) is not None:
                admitted_visual_block_pages.add(int(asset.page_id))

        for asset in page_assets:
            decision = self._assess_visual_asset(
                asset,
                page_by_id=page_by_id,
                block_by_id=block_by_id,
                neighbor_by_block_id=neighbor_by_block_id,
                page_has_admitted_visual_block=int(getattr(asset, "page_id", 0) or 0) in admitted_visual_block_pages,
            )
            decisions[id(asset)] = (asset, decision)

        return decisions

    def _assess_visual_asset(
        self,
        asset: Any,
        *,
        page_by_id: dict[int, Any],
        block_by_id: dict[int, Any],
        neighbor_by_block_id: dict[int, tuple[int | None, int | None]],
        page_has_admitted_visual_block: bool,
    ) -> VisualAdmissionDecision:
        metadata = dict(self._json_dict(getattr(asset, "metadata_json", None)) or {})
        page = page_by_id.get(int(getattr(asset, "page_id", 0) or 0))
        block = block_by_id.get(int(getattr(asset, "block_id", 0) or 0)) if getattr(asset, "block_id", None) else None

        block_type = self._normalize_inline_text(getattr(block, "block_type", None) or metadata.get("block_type")) or ""
        filter_reason = self._normalize_inline_text(getattr(block, "filter_reason", None))
        source_file_name = self._normalize_inline_text(metadata.get("source_file_name"))
        asset_file_name = self._normalize_inline_text(getattr(asset, "file_name", None) or metadata.get("file_name"))
        page_title = self._normalize_inline_text(metadata.get("page_title") or getattr(page, "page_title", None))
        block_text = self._trim_context(self._preferred_text(block, "clean_text", "text")) if block is not None else ""
        adjacent_texts = self._adjacent_texts(block, block_by_id, neighbor_by_block_id)
        figure_title = self._extract_visual_title(metadata, block_text, adjacent_texts)
        page_excerpt = self._page_excerpt(page)
        context_text = self._build_visual_context_text(
            source_file_name,
            page_title,
            figure_title,
            block_text,
            adjacent_texts,
            page_excerpt,
        )

        if filter_reason in self.VISUAL_EXCLUDED_FILTER_REASONS:
            return self._reject_visual_asset(
                category="excluded",
                reason=f"excluded_filter_reason:{filter_reason}",
                source_file_name=source_file_name,
                asset_file_name=asset_file_name,
                page_title=page_title,
                figure_title=figure_title,
                adjacent_texts=adjacent_texts,
                context_text=context_text,
            )

        exclusion_probe = " ".join(
            filter(
                None,
                [
                    filter_reason,
                    source_file_name,
                    page_title,
                    figure_title,
                    block_text,
                    *adjacent_texts,
                ],
            )
        ).lower()
        if self._contains_any(exclusion_probe, self.VISUAL_EXCLUDED_HINTS):
            return self._reject_visual_asset(
                category="excluded",
                reason="excluded_noise_marker",
                source_file_name=source_file_name,
                asset_file_name=asset_file_name,
                page_title=page_title,
                figure_title=figure_title,
                adjacent_texts=adjacent_texts,
                context_text=context_text,
            )

        visual_probe = " ".join(
            filter(None, [source_file_name, page_title, figure_title, block_text, *adjacent_texts, page_excerpt])
        ).lower()
        category = self._detect_visual_category(block_type, visual_probe, block_text, figure_title)
        reasons: list[str] = []

        if category is None and page_has_admitted_visual_block and getattr(asset, "asset_type", None) == "page_preview":
            category = "generic_visual"
            reasons.append("page_has_admitted_visual_block")

        if category is None and self._has_visual_filename_hint(source_file_name, page_title):
            category = "generic_visual"
            reasons.append("document_visual_hint")

        if category is None:
            return self._reject_visual_asset(
                category="rejected",
                reason="weak_visual_signal",
                source_file_name=source_file_name,
                asset_file_name=asset_file_name,
                page_title=page_title,
                figure_title=figure_title,
                adjacent_texts=adjacent_texts,
                context_text=context_text,
            )

        if category == "generic_visual" and not self._has_context_anchor(
            source_file_name,
            page_title,
            figure_title,
            adjacent_texts,
            page_has_admitted_visual_block=page_has_admitted_visual_block,
        ):
            return self._reject_visual_asset(
                category="rejected",
                reason="missing_visual_context_anchor",
                source_file_name=source_file_name,
                asset_file_name=asset_file_name,
                page_title=page_title,
                figure_title=figure_title,
                adjacent_texts=adjacent_texts,
                context_text=context_text,
            )

        priority_score = self.VISUAL_CATEGORY_PRIORITY.get(category, 0)
        if getattr(asset, "block_id", None) is not None:
            priority_score += 10
        if figure_title:
            priority_score += 8
        if adjacent_texts:
            priority_score += 4
        reasons.append(f"accepted_category:{category}")
        return VisualAdmissionDecision(
            accepted=True,
            category=category,
            priority_score=priority_score,
            reasons=tuple(reasons),
            source_file_name=source_file_name or asset_file_name,
            asset_file_name=asset_file_name,
            page_title=page_title,
            figure_title=figure_title,
            adjacent_texts=adjacent_texts,
            context_text=context_text,
        )

    def _reject_visual_asset(
        self,
        *,
        category: str,
        reason: str,
        source_file_name: str | None,
        asset_file_name: str | None,
        page_title: str | None,
        figure_title: str | None,
        adjacent_texts: tuple[str, ...],
        context_text: str,
    ) -> VisualAdmissionDecision:
        return VisualAdmissionDecision(
            accepted=False,
            category=category,
            priority_score=0,
            reasons=(reason,),
            source_file_name=source_file_name or asset_file_name,
            asset_file_name=asset_file_name,
            page_title=page_title,
            figure_title=figure_title,
            adjacent_texts=adjacent_texts,
            context_text=context_text,
        )

    def _visual_admission_payload(self, decision: VisualAdmissionDecision) -> dict[str, Any]:
        return {
            "status": "accepted" if decision.accepted else "rejected",
            "category": decision.category,
            "priority_score": decision.priority_score,
            "reasons": list(decision.reasons),
            "source_file_name": decision.source_file_name,
            "asset_file_name": decision.asset_file_name,
            "page_title": decision.page_title,
            "figure_title": decision.figure_title,
            "adjacent_texts": list(decision.adjacent_texts),
            "context_text": decision.context_text,
        }

    def _detect_visual_category(
        self,
        block_type: str,
        visual_probe: str,
        block_text: str,
        figure_title: str | None,
    ) -> str | None:
        if block_type == "table" or self._looks_like_table_snapshot(block_text, figure_title, visual_probe):
            return "table_snapshot"
        if self._contains_any(visual_probe, self.VISUAL_FLOW_HINTS):
            return "flow_diagram"
        if self._contains_any(visual_probe, self.VISUAL_EQUIPMENT_HINTS):
            return "equipment_diagram"
        if self._contains_any(visual_probe, self.VISUAL_CURVE_HINTS):
            return "curve_chart"
        if self._contains_any(visual_probe, self.VISUAL_GENERIC_HINTS):
            return "generic_visual"
        return None

    def _adjacent_texts(
        self,
        block: Any | None,
        block_by_id: dict[int, Any],
        neighbor_by_block_id: dict[int, tuple[int | None, int | None]],
    ) -> tuple[str, ...]:
        if block is None or getattr(block, "id", None) is None:
            return ()
        previous_id, next_id = neighbor_by_block_id.get(int(block.id), (None, None))
        texts: list[str] = []
        for neighbor_id in (previous_id, next_id):
            if neighbor_id is None:
                continue
            neighbor = block_by_id.get(int(neighbor_id))
            if neighbor is None or getattr(neighbor, "filter_status", "kept") == "filtered":
                continue
            text = self._trim_context(self._preferred_text(neighbor, "clean_text", "text"))
            if text:
                texts.append(text)
        return tuple(texts)

    def _extract_visual_title(
        self,
        metadata: dict[str, Any],
        block_text: str,
        adjacent_texts: tuple[str, ...],
    ) -> str | None:
        for key in self.VISUAL_TITLE_KEYS:
            title = self._normalize_inline_text(self._metadata_value(metadata, key))
            if title:
                return self._trim_context(title, max_chars=120)
        first_line = next((line.strip() for line in block_text.splitlines() if line.strip()), "")
        if self._looks_like_visual_title(first_line):
            return self._trim_context(first_line, max_chars=120)
        for text in adjacent_texts:
            first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
            if self._looks_like_visual_title(first_line):
                return self._trim_context(first_line, max_chars=120)
        return None

    def _page_excerpt(self, page: Any | None) -> str:
        if page is None:
            return ""
        text = self._preferred_text(page, "clean_content", "page_text")
        title = self._normalize_inline_text(getattr(page, "page_title", None))
        lines = [line.strip() for line in text.splitlines() if line and line.strip()]
        if title and lines and lines[0] == title:
            lines = lines[1:]
        return self._trim_context("\n".join(lines))

    def _build_visual_context_text(
        self,
        source_file_name: str | None,
        page_title: str | None,
        figure_title: str | None,
        block_text: str,
        adjacent_texts: tuple[str, ...],
        page_excerpt: str,
    ) -> str:
        parts: list[str] = []
        for value in (source_file_name, page_title, figure_title):
            cleaned = self._normalize_inline_text(value)
            if cleaned and cleaned not in parts:
                parts.append(cleaned)
        if block_text and block_text not in parts and block_text != figure_title:
            parts.append(self._trim_context(block_text))
        for text in adjacent_texts:
            if text and text not in parts:
                parts.append(text)
        if page_excerpt and page_excerpt not in parts:
            parts.append(page_excerpt)
        return " | ".join(parts)

    def _has_context_anchor(
        self,
        source_file_name: str | None,
        page_title: str | None,
        figure_title: str | None,
        adjacent_texts: tuple[str, ...],
        *,
        page_has_admitted_visual_block: bool,
    ) -> bool:
        return bool(
            figure_title
            or page_title
            or adjacent_texts
            or page_has_admitted_visual_block
            or self._has_visual_filename_hint(source_file_name, page_title)
        )

    def _has_visual_filename_hint(self, source_file_name: str | None, page_title: str | None) -> bool:
        probe = " ".join(filter(None, [source_file_name, page_title])).lower()
        return self._contains_any(
            probe,
            (*self.VISUAL_FLOW_HINTS, *self.VISUAL_EQUIPMENT_HINTS, *self.VISUAL_CURVE_HINTS, *self.VISUAL_GENERIC_HINTS),
        )

    def _looks_like_table_snapshot(self, block_text: str, figure_title: str | None, visual_probe: str) -> bool:
        if figure_title and self._looks_like_visual_title(figure_title):
            lowered = figure_title.lower()
            if "table" in lowered or "表" in figure_title:
                return True
        if self._contains_any(visual_probe, self.VISUAL_TABLE_HINTS):
            return True
        stripped = block_text.strip()
        return stripped.count("|") >= 2 or stripped.count("\t") >= 2

    @staticmethod
    def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
        return any(hint in text for hint in hints if hint)

    @staticmethod
    def _metadata_value(metadata: dict[str, Any], key: str) -> str | None:
        value = metadata.get(key)
        if isinstance(value, list):
            joined = " ".join(str(item).strip() for item in value if str(item).strip())
            return joined or None
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _looks_like_visual_caption(text: str) -> bool:
        normalized = text.strip()
        if not normalized:
            return False
        if re.match(r"^(图|表)\s*\d+", normalized):
            return True
        return bool(re.match(r"^(figure|table)\s*\d+", normalized, re.IGNORECASE))

    def _looks_like_visual_title(self, text: str) -> bool:
        return self._looks_like_visual_caption(text) or self._looks_like_named_visual_title(text)

    def _looks_like_named_visual_title(self, text: str) -> bool:
        normalized = self._normalize_inline_text(text)
        if not normalized:
            return False
        normalized = normalized.rstrip("：:;；,.，。 ")
        if not normalized or len(normalized) > self.VISUAL_TITLE_MAX_CHARS:
            return False
        if "|" in normalized or "\t" in normalized:
            return False
        if normalized.count("，") + normalized.count(",") + normalized.count("。") + normalized.count(".") > 2:
            return False
        lowered = normalized.lower()
        return self._contains_any(lowered, self.VISUAL_NAMED_TITLE_HINTS)

    @classmethod
    def _trim_context(cls, text: str, *, max_chars: int | None = None) -> str:
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if not normalized:
            return ""
        limit = max_chars or cls.VISUAL_MAX_CONTEXT_CHARS
        return normalized[:limit]

    @staticmethod
    def _normalize_inline_text(value: object) -> str | None:
        if value is None:
            return None
        normalized = re.sub(r"\s+", " ", str(value)).strip()
        return normalized or None

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
            ),
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
