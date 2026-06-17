"""
Parsed Content Cleaner

职责：
1. 在 MinerU 解析完成后生成 clean_content / clean_blocks，供后续分块和索引使用。
2. 保留原始 content / blocks / raw_payload，方便前端对照查看 MinerU 原始结果。
3. 记录 filtered_content / filtered_blocks，便于排查页眉、页脚、目录和版权声明等噪声。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
import math
import re
from typing import Any

from app.knowledge.parsing.parsed_document import ParsedDocumentResult


FILTER_STATUS_FILTERED = "filtered"
FILTER_STATUS_KEPT = "kept"
FILTER_REASON_EMPTY = "empty_after_cleaning"
FILTER_REASON_MINERU_DISCARDED = "mineru_discarded"
FILTER_REASON_MINERU_NON_BODY = "mineru_non_body"
FILTER_REASON_TEXT_RULE = "text_rule"
FILTER_REASON_TOC_PAGE = "toc_page"


@dataclass(slots=True)
class ParsedContentCleanSummary:
    """解析清洗摘要，用于日志、前端展示和问题排查。"""

    removed_line_count: int = 0
    removed_block_count: int = 0
    removed_toc_page_numbers: list[int] = field(default_factory=list)
    repeated_noise_line_count: int = 0
    mineru_discarded_block_count: int = 0
    filtered_block_count: int = 0
    cleaned_markdown: bool = False

    def to_dict(self) -> dict[str, object]:
        """转换为可 JSON 序列化的摘要。"""

        return {
            "removed_line_count": self.removed_line_count,
            "removed_block_count": self.removed_block_count,
            "removed_toc_page_numbers": self.removed_toc_page_numbers,
            "repeated_noise_line_count": self.repeated_noise_line_count,
            "mineru_discarded_block_count": self.mineru_discarded_block_count,
            "filtered_block_count": self.filtered_block_count,
            "cleaned_markdown": self.cleaned_markdown,
        }


class ParsedContentCleaner:
    """
    MinerU 解析结果清洗器。

    清洗只写入 clean_* / filtered_* 字段，不覆盖原始解析字段。这样前端可以展示
    MinerU 原始内容，而 Chunk、PageIndex、ripgrep 与 Milvus 统一读取 clean_content。
    """

    EDGE_LINE_WINDOW = 8
    MIN_REPEATED_LINE_LENGTH = 3
    MAX_REPEATED_LINE_LENGTH = 140

    PAGE_TEXT_KEYS = ("content", "text", "markdown", "md")
    BLOCK_TEXT_KEYS = ("text", "content", "markdown", "md")
    PAGE_BLOCK_KEYS = ("blocks", "page_blocks")
    DISCARDED_BLOCK_KEYS = ("discarded_blocks", "discarded", "discard_blocks")

    PAGE_NUMBER_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"^\s*(?:page|p\.)\s*\d+\s*(?:of|/)\s*\d+\s*$", re.IGNORECASE),
        re.compile(r"^\s*(?:page|p\.)\s*\d+\s*$", re.IGNORECASE),
        re.compile(r"^\s*第\s*\d+\s*页\s*(?:共\s*\d+\s*页)?\s*$"),
        re.compile(r"^\s*[-–—]?\s*\d+\s*[-–—]?\s*$"),
        re.compile(r"^\s*\d+\s*/\s*\d+\s*$"),
    )
    BOILERPLATE_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"\bconfidential\b", re.IGNORECASE),
        re.compile(r"\bproprietary\b", re.IGNORECASE),
        re.compile(r"\bproperty\s+of\b", re.IGNORECASE),
        re.compile(r"\bshall\s+not\s+be\s+reproduced\b", re.IGNORECASE),
        re.compile(r"\btransferred\s+to\s+any\b", re.IGNORECASE),
        re.compile(r"\bpermission\s+in\s+written\s+form\b", re.IGNORECASE),
        re.compile(r"\bcopyright\b|©", re.IGNORECASE),
        re.compile(r"保密|机密|内部资料|版权所有|未经.*许可|不准复制|转让第三方"),
    )
    TOC_TITLE_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"^\s*(目录|目\s*录)\s*$"),
        re.compile(r"^\s*(table\s+of\s+contents|contents|content)\s*$", re.IGNORECASE),
    )
    MARKDOWN_ARTIFACT_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"^\s*#{1,6}\s*$"),
    )
    TOC_ENTRY_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"^.{2,140}\.{2,}\s*\d{1,4}\s*$"),
        re.compile(r"^\s*\d+(?:\.\d+){0,5}\s+.{2,140}\s+\d{1,4}\s*$"),
        re.compile(r"^.{2,140}\s{2,}\d{1,4}\s*$"),
    )
    INLINE_TOC_TITLE_PATTERN = re.compile(
        r"^\s*#{0,6}\s*(?:content|contents|table\s+of\s+contents|目录)\s*#{0,6}\b",
        re.IGNORECASE,
    )
    INLINE_TOC_DOT_ENTRY_PATTERN = re.compile(r"\.{2,}\s*\d{1,4}\b")
    INLINE_TOC_NUMBERED_TITLE_PATTERN = re.compile(
        r"(?:^|\s)\d+(?:\.\d+){0,5}\s+[A-Z][A-Z0-9/&(),.\-\s]{2,}",
        re.IGNORECASE,
    )
    MINERU_NON_BODY_TYPES = {
        "discarded",
        "footer",
        "header",
        "page_footer",
        "page_header",
        "page_number",
        "page-num",
        "watermark",
    }

    def clean_result(self, parsed_result: ParsedDocumentResult) -> ParsedDocumentResult:
        """
        清洗解析结果并返回新的 ParsedDocumentResult。

        原始 content / blocks / raw_payload 不被覆盖，清洗结果写入 clean_* 字段。
        """

        repeated_lines = self._infer_repeated_edge_lines(parsed_result.pages)
        summary = ParsedContentCleanSummary(repeated_noise_line_count=len(repeated_lines))
        cleaned_pages = [self._clean_page(page, repeated_lines, summary) for page in parsed_result.pages]
        metadata = dict(parsed_result.metadata or {})
        metadata["content_cleaning"] = summary.to_dict()

        return ParsedDocumentResult(
            pages=cleaned_pages,
            parser_name=parsed_result.parser_name,
            parse_source=parsed_result.parse_source,
            raw_payload=deepcopy(parsed_result.raw_payload),
            task_id=parsed_result.task_id,
            metadata=metadata,
        )

    def clean_markdown_text(self, markdown_content: str) -> str:
        """清洗单段 Markdown 文本，供兼容旧数据时使用。"""

        cleaned_markdown, _, _ = self._clean_text(markdown_content, repeated_lines=set(), edge_only=False)
        return cleaned_markdown

    def _clean_page(
        self,
        page: dict[str, Any],
        repeated_lines: set[str],
        summary: ParsedContentCleanSummary,
    ) -> dict[str, Any]:
        page_no = int(page.get("page_number") or page.get("page_no") or 0)
        cleaned_page = deepcopy(page)
        raw_blocks = self._extract_blocks(page)
        discarded_blocks = self._extract_discarded_blocks(page)
        discarded_refs = self._build_discarded_refs(discarded_blocks)
        content = self._first_text(page, self.PAGE_TEXT_KEYS)
        content_lines = self._split_lines(content)

        if self._is_toc_page(content_lines, page):
            annotated_blocks = [self._mark_block_filtered(block, FILTER_REASON_TOC_PAGE) for block in raw_blocks]
            extra_filtered = [
                self._mark_block_filtered(block, FILTER_REASON_MINERU_DISCARDED)
                for block in discarded_blocks
                if not self._block_matches_any(block, annotated_blocks)
            ]
            filtered_blocks = annotated_blocks + extra_filtered
            filtered_content = self._join_filtered_texts([content], filtered_blocks)

            summary.removed_toc_page_numbers.append(page_no)
            summary.removed_line_count += len([line for line in content_lines if line.strip()])
            summary.removed_block_count += len(raw_blocks)
            summary.filtered_block_count += len(filtered_blocks)
            summary.mineru_discarded_block_count += len(extra_filtered)

            cleaned_page["blocks"] = annotated_blocks
            cleaned_page["clean_content"] = ""
            cleaned_page["clean_blocks"] = []
            cleaned_page["filtered_content"] = filtered_content
            cleaned_page["filtered_blocks"] = filtered_blocks
            cleaned_page["cleaning_metadata"] = {
                "removed_as_toc": True,
                "removed_line_count": len([line for line in content_lines if line.strip()]),
                "removed_block_count": len(raw_blocks),
            }
            return cleaned_page

        clean_content, removed_lines, removed_line_values = self._clean_text(content, repeated_lines, edge_only=True)
        summary.removed_line_count += removed_lines
        annotated_blocks, clean_blocks, filtered_blocks = self._clean_blocks(
            raw_blocks,
            discarded_blocks,
            discarded_refs,
            repeated_lines,
            summary,
        )

        if not clean_content and clean_blocks:
            clean_content = "\n".join(
                self._first_text(block, ("clean_text", *self.BLOCK_TEXT_KEYS)).strip()
                for block in clean_blocks
                if self._first_text(block, ("clean_text", *self.BLOCK_TEXT_KEYS)).strip()
            ).strip()

        filtered_content = self._join_filtered_texts(removed_line_values, filtered_blocks)
        cleaned_page["blocks"] = annotated_blocks
        cleaned_page["clean_content"] = clean_content
        cleaned_page["clean_blocks"] = clean_blocks
        cleaned_page["filtered_content"] = filtered_content
        cleaned_page["filtered_blocks"] = filtered_blocks
        cleaned_page["cleaning_metadata"] = {
            "removed_as_toc": False,
            "removed_line_count": removed_lines,
            "removed_block_count": len(filtered_blocks),
            "repeated_edge_noise_applied": bool(repeated_lines),
        }
        return cleaned_page

    def _clean_blocks(
        self,
        blocks: list[dict[str, Any]],
        discarded_blocks: list[dict[str, Any]],
        discarded_refs: dict[str, set[str]],
        repeated_lines: set[str],
        summary: ParsedContentCleanSummary,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        annotated_blocks: list[dict[str, Any]] = []
        clean_blocks: list[dict[str, Any]] = []
        filtered_blocks: list[dict[str, Any]] = []
        matched_discarded_texts: set[str] = set()
        total_blocks = len(blocks)

        for index, block in enumerate(blocks):
            raw_text = self._first_text(block, self.BLOCK_TEXT_KEYS)
            normalized_text = self._normalize_line(raw_text)
            block_type = self._block_type(block)

            if self._is_mineru_discarded_block(block, raw_text, discarded_refs):
                reason = FILTER_REASON_MINERU_DISCARDED
                if self._is_mineru_non_body_type(block):
                    reason = FILTER_REASON_MINERU_NON_BODY
                filtered = self._mark_block_filtered(block, reason)
                annotated_blocks.append(filtered)
                filtered_blocks.append(filtered)
                matched_discarded_texts.add(normalized_text)
                removed_lines = self._count_non_empty_lines(raw_text)
                summary.removed_line_count += removed_lines
                summary.removed_block_count += 1
                summary.filtered_block_count += 1
                summary.mineru_discarded_block_count += 1
                continue

            if block_type == "table":
                kept = self._mark_block_kept(block, raw_text)
                annotated_blocks.append(kept)
                clean_blocks.append(kept)
                continue

            is_edge_block = index < self.EDGE_LINE_WINDOW or index >= max(total_blocks - self.EDGE_LINE_WINDOW, 0)
            clean_text, removed_lines, _ = self._clean_text(raw_text, repeated_lines, edge_only=is_edge_block)
            summary.removed_line_count += removed_lines

            if clean_text or self._has_non_text_payload(block):
                kept = self._mark_block_kept(block, clean_text)
                annotated_blocks.append(kept)
                clean_blocks.append(kept)
                continue

            reason = FILTER_REASON_TEXT_RULE if raw_text.strip() else FILTER_REASON_EMPTY
            filtered = self._mark_block_filtered(block, reason)
            annotated_blocks.append(filtered)
            filtered_blocks.append(filtered)
            summary.removed_block_count += 1
            summary.filtered_block_count += 1

        for block in discarded_blocks:
            raw_text = self._first_text(block, self.BLOCK_TEXT_KEYS)
            normalized_text = self._normalize_line(raw_text)
            if normalized_text and normalized_text in matched_discarded_texts:
                continue
            if self._block_matches_any(block, filtered_blocks):
                continue
            filtered = self._mark_block_filtered(block, FILTER_REASON_MINERU_DISCARDED)
            filtered_blocks.append(filtered)
            matched_discarded_texts.add(normalized_text)
            summary.removed_line_count += self._count_non_empty_lines(raw_text)
            summary.removed_block_count += 1
            summary.filtered_block_count += 1
            summary.mineru_discarded_block_count += 1

        return annotated_blocks, clean_blocks, filtered_blocks

    def _clean_text(self, text: str, repeated_lines: set[str], edge_only: bool) -> tuple[str, int, list[str]]:
        lines = self._split_lines(text)
        if not lines:
            return "", 0, []

        cleaned_lines: list[str] = []
        removed_lines: list[str] = []
        non_empty_indexes = [index for index, line in enumerate(lines) if line.strip()]
        edge_indexes = set(non_empty_indexes[: self.EDGE_LINE_WINDOW] + non_empty_indexes[-self.EDGE_LINE_WINDOW :])

        for index, line in enumerate(lines):
            normalized = self._normalize_line(line)
            is_edge_line = index in edge_indexes
            stripped_line, removed_inline_toc = self._strip_inline_toc_noise(line)
            if removed_inline_toc:
                removed_lines.append(line.strip())
                if stripped_line:
                    cleaned_lines.append(stripped_line.strip())
                continue
            if self._should_remove_line(line, normalized, repeated_lines, is_edge_line if edge_only else True):
                removed_lines.append(line.strip())
                continue
            cleaned_lines.append(line.strip())

        return "\n".join(line for line in cleaned_lines if line).strip(), len(removed_lines), removed_lines

    def _should_remove_line(
        self,
        line: str,
        normalized: str,
        repeated_lines: set[str],
        is_edge_line: bool,
    ) -> bool:
        if not normalized:
            return False
        if self._is_table_like_line(line):
            return False
        if self._is_inline_toc_noise_line(line):
            return True
        if self._is_markdown_artifact_line(line):
            return True
        if normalized in repeated_lines:
            return True
        if is_edge_line and self._is_page_number_line(normalized):
            return True
        if is_edge_line and self._is_boilerplate_line(normalized):
            return True
        return False

    def _infer_repeated_edge_lines(self, pages: list[dict[str, Any]]) -> set[str]:
        if len(pages) < 2:
            return set()

        line_counter: Counter[str] = Counter()
        for page in pages:
            content = self._first_text(page, self.PAGE_TEXT_KEYS)
            non_empty_lines = [line for line in self._split_lines(content) if line.strip()]
            edge_lines = non_empty_lines[: self.EDGE_LINE_WINDOW] + non_empty_lines[-self.EDGE_LINE_WINDOW :]
            page_candidates = {
                self._normalize_line(line)
                for line in edge_lines
                if self._is_repeated_noise_candidate(line)
            }
            line_counter.update(page_candidates)

        threshold = max(2, math.ceil(len(pages) * 0.2))
        return {line for line, count in line_counter.items() if count >= threshold}

    def _is_repeated_noise_candidate(self, line: str) -> bool:
        normalized = self._normalize_line(line)
        if not (self.MIN_REPEATED_LINE_LENGTH <= len(normalized) <= self.MAX_REPEATED_LINE_LENGTH):
            return False
        if self._is_table_like_line(line):
            return False
        return True

    def _is_toc_page(self, lines: list[str], page: Mapping[str, Any]) -> bool:
        non_empty = [line.strip() for line in lines if line.strip()]
        if len(non_empty) < 3:
            return False

        title_candidates = [
            str(page.get("page_title") or page.get("title") or "").strip(),
            *non_empty[:8],
        ]
        has_toc_title = any(
            pattern.search(line)
            for line in title_candidates
            if line
            for pattern in self.TOC_TITLE_PATTERNS
        )
        toc_entry_count = sum(1 for line in non_empty if self._is_toc_entry_line(line))
        dot_entry_count = sum(1 for line in non_empty if self.INLINE_TOC_DOT_ENTRY_PATTERN.search(line))
        entry_ratio = toc_entry_count / max(len(non_empty), 1)

        if has_toc_title and (toc_entry_count >= 2 or dot_entry_count >= 2):
            return True
        if toc_entry_count >= 6 and entry_ratio >= 0.45:
            return True
        return dot_entry_count >= 6 and dot_entry_count / max(len(non_empty), 1) >= 0.45

    def _is_toc_entry_line(self, line: str) -> bool:
        return any(pattern.search(line.strip()) for pattern in self.TOC_ENTRY_PATTERNS)

    def _strip_inline_toc_noise(self, line: str) -> tuple[str, bool]:
        """
        移除 MinerU 偶发的单行目录噪声。

        部分 PDF 目录会被解析成一整行，并与正文首句粘连。此时只删除目录前缀，
        保留最后一个页码标记之后的正文尾部。
        """

        if not self._is_inline_toc_noise_line(line):
            return line, False

        matches = list(self.INLINE_TOC_DOT_ENTRY_PATTERN.finditer(line))
        if not matches:
            return "", True

        remainder = line[matches[-1].end() :].strip()
        remainder = re.sub(r"^\s*#{1,6}\s+(#{1,6}\s+)", r"\1", remainder)
        return remainder, True

    def _is_inline_toc_noise_line(self, line: str) -> bool:
        text = str(line or "").strip()
        if len(text) < 80 or self._is_table_like_line(text):
            return False

        dot_entry_count = len(self.INLINE_TOC_DOT_ENTRY_PATTERN.findall(text))
        numbered_title_count = len(self.INLINE_TOC_NUMBERED_TITLE_PATTERN.findall(text))
        has_toc_title = bool(self.INLINE_TOC_TITLE_PATTERN.search(text))

        return (has_toc_title and (dot_entry_count >= 3 or numbered_title_count >= 5)) or dot_entry_count >= 8

    def _is_page_number_line(self, normalized: str) -> bool:
        return any(pattern.search(normalized) for pattern in self.PAGE_NUMBER_PATTERNS)

    def _is_boilerplate_line(self, normalized: str) -> bool:
        return any(pattern.search(normalized) for pattern in self.BOILERPLATE_PATTERNS)

    def _is_markdown_artifact_line(self, line: str) -> bool:
        return any(pattern.search(line) for pattern in self.MARKDOWN_ARTIFACT_PATTERNS)

    def _is_table_like_line(self, line: str) -> bool:
        normalized = line.strip().lower()
        if not normalized:
            return False
        return (
            "|" in normalized
            or "<td" in normalized
            or "<th" in normalized
            or "<tr" in normalized
            or "</table" in normalized
        )

    def _extract_blocks(self, page: Mapping[str, Any]) -> list[dict[str, Any]]:
        for key in self.PAGE_BLOCK_KEYS:
            blocks = page.get(key)
            if isinstance(blocks, list):
                return [deepcopy(block) for block in blocks if isinstance(block, dict)]
        return []

    def _extract_discarded_blocks(self, page: Mapping[str, Any]) -> list[dict[str, Any]]:
        discarded: list[dict[str, Any]] = []
        for key in self.DISCARDED_BLOCK_KEYS:
            value = page.get(key)
            if isinstance(value, list):
                discarded.extend(deepcopy(block) for block in value if isinstance(block, dict))
            elif isinstance(value, dict):
                discarded.append(deepcopy(value))
        return discarded

    def _build_discarded_refs(self, discarded_blocks: list[dict[str, Any]]) -> dict[str, set[str]]:
        text_refs: set[str] = set()
        id_refs: set[str] = set()
        for block in discarded_blocks:
            raw_text = self._first_text(block, self.BLOCK_TEXT_KEYS)
            normalized_text = self._normalize_line(raw_text)
            if normalized_text:
                text_refs.add(normalized_text)
            for key in ("id", "block_id", "index", "block_index"):
                value = block.get(key)
                if value is not None:
                    id_refs.add(str(value))
        return {"text": text_refs, "id": id_refs}

    def _is_mineru_discarded_block(
        self,
        block: Mapping[str, Any],
        raw_text: str,
        discarded_refs: dict[str, set[str]],
    ) -> bool:
        if self._is_mineru_non_body_type(block):
            return True
        for key in ("discarded", "is_discarded", "ignore", "ignored"):
            if bool(block.get(key)):
                return True
        normalized_text = self._normalize_line(raw_text)
        if normalized_text and normalized_text in discarded_refs["text"]:
            return True
        for key in ("id", "block_id", "index", "block_index"):
            value = block.get(key)
            if value is not None and str(value) in discarded_refs["id"]:
                return True
        return False

    def _is_mineru_non_body_type(self, block: Mapping[str, Any]) -> bool:
        type_values = {
            str(block.get("block_type") or "").strip().lower(),
            str(block.get("type") or "").strip().lower(),
            str(block.get("category") or "").strip().lower(),
            str(block.get("role") or "").strip().lower(),
        }
        return bool(type_values & self.MINERU_NON_BODY_TYPES)

    def _block_type(self, block: Mapping[str, Any]) -> str:
        return str(block.get("block_type") or block.get("type") or "text").strip().lower()

    def _has_non_text_payload(self, block: Mapping[str, Any]) -> bool:
        return bool(block.get("image_candidates")) or self._block_type(block) in {"image", "formula"}

    def _mark_block_kept(self, block: Mapping[str, Any], clean_text: str) -> dict[str, Any]:
        marked = deepcopy(dict(block))
        marked["clean_text"] = clean_text
        marked["filter_status"] = FILTER_STATUS_KEPT
        marked["filter_reason"] = None
        return marked

    def _mark_block_filtered(self, block: Mapping[str, Any], reason: str) -> dict[str, Any]:
        marked = deepcopy(dict(block))
        marked["clean_text"] = ""
        marked["filter_status"] = FILTER_STATUS_FILTERED
        marked["filter_reason"] = reason
        return marked

    def _block_matches_any(self, block: Mapping[str, Any], candidates: list[dict[str, Any]]) -> bool:
        raw_text = self._normalize_line(self._first_text(block, self.BLOCK_TEXT_KEYS))
        raw_id = str(block.get("id") or block.get("block_id") or "")
        for candidate in candidates:
            candidate_text = self._normalize_line(self._first_text(candidate, self.BLOCK_TEXT_KEYS))
            candidate_id = str(candidate.get("id") or candidate.get("block_id") or "")
            if raw_text and raw_text == candidate_text:
                return True
            if raw_id and raw_id == candidate_id:
                return True
        return False

    def _join_filtered_texts(self, texts: list[str], filtered_blocks: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        seen: set[str] = set()
        for value in texts:
            for line in self._split_lines(value):
                line = line.strip()
                normalized = self._normalize_line(line)
                if normalized and normalized not in seen:
                    parts.append(line)
                    seen.add(normalized)
        for block in filtered_blocks:
            raw_text = self._first_text(block, self.BLOCK_TEXT_KEYS)
            normalized = self._normalize_line(raw_text)
            if normalized and normalized not in seen:
                parts.append(raw_text.strip())
                seen.add(normalized)
        return "\n".join(part for part in parts if part).strip()

    def _count_non_empty_lines(self, text: str) -> int:
        return len([line for line in self._split_lines(text) if line.strip()])

    def _first_text(self, payload: Mapping[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _split_lines(self, text: str) -> list[str]:
        return str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")

    def _normalize_line(self, line: str) -> str:
        normalized = re.sub(r"\s+", " ", str(line or "").strip()).strip("-–—·• \t")
        if re.fullmatch(r"\d+\s+[A-Z]{2,10}", normalized):
            return normalized.replace(" ", "")
        return normalized
