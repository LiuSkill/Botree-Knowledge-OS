"""结构感知的文档分块构建器。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from app.knowledge.parsing.searchable_text import (
    build_page_searchable_text,
    normalize_searchable_text,
    render_table_block_text,
)


ATOMIC_BLOCK_TYPES = {"formula", "table"}
HEADING_BLOCK_TYPES = {"title", "heading"}
TEXT_KEYS = ("clean_text", "text", "content", "markdown", "md", "caption")
SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[。！？；!?;])|(?<=[.!?;])\s+|\n+")
CLAUSE_BOUNDARY_PATTERN = re.compile(r"(?<=[，、：,:])")
TABLE_ROW_PATTERN = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEPARATOR_PATTERN = re.compile(r"^\s*\|(?:\s*:?-+:?\s*\|)+\s*$")
TABLE_CAPTION_PATTERN = re.compile(r"^表\s*\d+\s*.+")
FORMULA_ROW_BOUNDARY_PATTERN = re.compile(r"\\\\\s*")
MEASUREMENT_PATTERN = re.compile(
    r"^[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)\s*"
    r"(?:%|kw|w|mw|v|a|ma|pa|kpa|mpa|bar|m|mm|cm|m2|m3|m²|m³|l|kg|g|t|rpm)"
    r"(?:\s*[.x×]\s*\d.*)?$",
    re.IGNORECASE,
)
HEADING_PATTERN = re.compile(
    r"^(?:#{1,6}\s+|第[一二三四五六七八九十百千0-9]+[章节篇部分]\b|"
    r"[一二三四五六七八九十]+[、.]|\d+(?:\.\d+)*[、.\s]|（\d+）|\(\d+\))"
)


@dataclass(frozen=True, slots=True)
class _StructuralBlock:
    """解析器结构块在分块模块内的统一表示。"""

    block_type: str
    text: str
    page_number: int | None
    block_index: int
    legacy_boundary: bool = False


@dataclass(slots=True)
class _ChunkDraft:
    parts: list[str]
    page_numbers: list[int]
    block_types: list[str]
    section_title: str | None = None
    heading_path: list[str] | None = None

    @property
    def content(self) -> str:
        return normalize_searchable_text("\n".join(self.parts))


class ChunkBuilder:
    """按解析结构装箱，仅对超长结构执行语义边界切分。"""

    def __init__(
        self,
        chunk_size: int = 800,
        overlap: int = 120,
        rule_version: str = "structure-v2",
        index_generation: str = "default",
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if overlap < 0:
            raise ValueError("overlap must be non-negative")
        self.chunk_size = chunk_size
        self.overlap = min(overlap, chunk_size - 1)
        self.rule_version = rule_version
        self.index_generation = index_generation
        self._content_limit = chunk_size
        self._document_metadata: dict[str, Any] = {}
        self._metadata_prefix = ""

    def build(
        self,
        pages: list[dict],
        document_metadata: Mapping[str, Any] | None = None,
    ) -> list[dict]:
        self._document_metadata = {
            str(key): value
            for key, value in (document_metadata or {}).items()
            if value is not None and str(value).strip()
        }
        self._metadata_prefix = self._build_metadata_prefix(self._document_metadata)
        self._content_limit = self.chunk_size - len(self._metadata_prefix) - (1 if self._metadata_prefix else 0)
        if self._content_limit <= 0:
            raise ValueError("document metadata exceeds chunk_size")
        drafts = self._assemble(self._collect_blocks(pages))
        chunks = [self._to_payload(index, draft) for index, draft in enumerate(drafts, start=1)]
        for index, chunk in enumerate(chunks):
            chunk["metadata"]["previous_chunk_index"] = chunks[index - 1]["chunk_index"] if index > 0 else None
            chunk["metadata"]["next_chunk_index"] = (
                chunks[index + 1]["chunk_index"] if index + 1 < len(chunks) else None
            )
        return chunks

    def _collect_blocks(self, pages: list[dict]) -> list[_StructuralBlock]:
        blocks: list[_StructuralBlock] = []
        for page in pages:
            page_number = self._page_number(page)
            structured_blocks = self._page_blocks(page)
            if structured_blocks is not None:
                for fallback_index, raw_block in enumerate(structured_blocks, start=1):
                    block = self._normalize_block(raw_block, page_number, fallback_index)
                    if block is not None:
                        if not blocks and block.block_type == "text" and self._looks_like_document_title(block.text):
                            block = _StructuralBlock(
                                block_type="title",
                                text=block.text,
                                page_number=block.page_number,
                                block_index=block.block_index,
                            )
                        blocks.append(block)
                continue

            raw_content = page.get("clean_content")
            content = (
                str(raw_content)
                if isinstance(raw_content, str) and raw_content.strip()
                else build_page_searchable_text(page)
            )
            for index, part in enumerate(re.split(r"\n\s*\n+", content), start=1):
                text = normalize_searchable_text(part)
                if text:
                    blocks.append(
                        _StructuralBlock(
                            block_type=self._infer_text_block_type(text),
                            text=text,
                            page_number=page_number,
                            block_index=index,
                            legacy_boundary=True,
                        )
                    )
        return blocks

    def _assemble(self, blocks: list[_StructuralBlock]) -> list[_ChunkDraft]:
        drafts: list[_ChunkDraft] = []
        current = _ChunkDraft(parts=[], page_numbers=[], block_types=[])
        heading_path: list[str] = []
        pending_table_captions: list[_StructuralBlock] = []

        def flush() -> None:
            nonlocal current
            if current.content:
                drafts.append(current)
            current = _ChunkDraft(parts=[], page_numbers=[], block_types=[])

        for block in blocks:
            if block.block_type == "table_caption":
                pending_table_captions.append(block)
                continue

            if block.block_type == "table":
                block, displaced_caption, caption_page = self._bind_table_caption(block, pending_table_captions)
                pending_table_captions = [displaced_caption] if displaced_caption is not None else []
            else:
                caption_page = None

            if block.legacy_boundary and len(block.text) > self._content_limit:
                flush()
                for part in self._semantic_parts(block.text, self._content_limit):
                    draft = self._draft_for_text(part, block, heading_path=heading_path)
                    drafts.append(draft)
                continue

            if block.block_type in HEADING_BLOCK_TYPES or self._looks_like_heading(block.text):
                heading_level = self._heading_level(block.text, block.block_type)
                heading_path = heading_path[: max(0, heading_level - 1)]
                heading_path.append(block.text.split("\n", 1)[0])
                if current.parts and any(item not in HEADING_BLOCK_TYPES for item in current.block_types):
                    flush()
                if current.parts and not self._fits(current.content, block.text):
                    flush()
                if current.parts:
                    self._append_block(current, block)
                    current.section_title = heading_path[-1]
                    current.heading_path = list(heading_path)
                else:
                    current = self._draft_for_text(
                        block.text,
                        block,
                        section_title=heading_path[-1],
                        heading_path=heading_path,
                    )
                continue

            if block.block_type == "table":
                if self._fits(current.content, block.text):
                    self._seed_heading_context(current, heading_path)
                    self._append_block(current, block)
                    if caption_page is not None and caption_page not in current.page_numbers:
                        current.page_numbers.append(caption_page)
                    continue
                flush()
                table_drafts = self._split_table(block)
                self._attach_heading_context(table_drafts, heading_path)
                self._attach_caption_context(table_drafts, caption_page)
                drafts.extend(table_drafts[:-1])
                if table_drafts:
                    current = table_drafts[-1]
                continue

            if block.block_type == "formula":
                if self._fits(current.content, block.text):
                    self._seed_heading_context(current, heading_path)
                    self._append_block(current, block)
                    continue
                flush()
                formula_drafts = self._split_formula(block)
                self._attach_heading_context(formula_drafts, heading_path)
                drafts.extend(formula_drafts[:-1])
                if formula_drafts:
                    current = formula_drafts[-1]
                continue

            if self._fits(current.content, block.text):
                self._seed_heading_context(current, heading_path)
                self._append_block(current, block)
                continue

            flush()
            parts = self._semantic_parts(block.text, self._content_limit)
            for part in parts[:-1]:
                draft = self._draft_for_text(part, block, heading_path=heading_path)
                drafts.append(draft)
            if parts:
                current = self._draft_for_text(parts[-1], block, heading_path=heading_path)

        for caption in pending_table_captions:
            if not self._fits(current.content, caption.text):
                flush()
            self._append_block(current, caption)
        flush()
        return drafts

    def _split_table(self, block: _StructuralBlock) -> list[_ChunkDraft]:
        lines = [line.strip() for line in block.text.splitlines() if line.strip()]
        first_row = next((index for index, line in enumerate(lines) if TABLE_ROW_PATTERN.match(line)), None)
        if first_row is None:
            return [self._draft_for_text(part, block) for part in self._semantic_parts(block.text, self._content_limit)]

        caption_lines = lines[:first_row]
        table_lines = lines[first_row:]
        header_lines = table_lines[:1]
        body_start = 1
        if len(table_lines) > 1 and TABLE_SEPARATOR_PATTERN.match(table_lines[1]):
            header_lines.append(table_lines[1])
            body_start = 2
        prefix_lines = caption_lines + header_lines
        prefix = "\n".join(prefix_lines)
        rows = table_lines[body_start:]

        if len(block.text) <= self._content_limit:
            return [self._draft_for_text(block.text, block)]
        if not rows:
            return [self._draft_for_text(part, block) for part in self._semantic_parts(block.text, self._content_limit)]

        drafts: list[_ChunkDraft] = []
        current_rows: list[str] = []
        for row in rows:
            candidate = "\n".join([prefix, *current_rows, row])
            if len(candidate) <= self._content_limit:
                current_rows.append(row)
                continue
            if current_rows:
                drafts.append(self._draft_for_text("\n".join([prefix, *current_rows]), block))
                current_rows = []
            if len("\n".join([prefix, row])) <= self._content_limit:
                current_rows.append(row)
                continue
            drafts.extend(self._split_oversized_table_row(prefix, row, block))
        if current_rows:
            drafts.append(self._draft_for_text("\n".join([prefix, *current_rows]), block))
        return drafts

    def _split_oversized_table_row(
        self,
        prefix: str,
        row: str,
        block: _StructuralBlock,
    ) -> list[_ChunkDraft]:
        available = self._content_limit - len(prefix) - 1
        if available <= 0:
            return [self._draft_for_text(part, block) for part in self._semantic_parts(f"{prefix}\n{row}", self._content_limit)]
        return [
            self._draft_for_text(f"{prefix}\n{part}", block)
            for part in self._semantic_parts(row, available)
        ]

    def _split_formula(self, block: _StructuralBlock) -> list[_ChunkDraft]:
        if len(block.text) <= self._content_limit:
            return [self._draft_for_text(block.text, block)]

        lines = [line for line in block.text.splitlines() if line.strip()]
        opening = lines[0] if lines and lines[0].strip() in {"$$", "\\["} else "$$"
        closing = lines[-1] if lines and lines[-1].strip() in {"$$", "\\]"} else opening
        body_lines = lines[1:-1] if len(lines) >= 2 and lines[0].strip() == opening else lines
        begin_line = body_lines[0] if body_lines and "\\begin{" in body_lines[0] else None
        end_line = body_lines[-1] if body_lines and "\\end{" in body_lines[-1] else None
        if begin_line and end_line:
            body_lines = body_lines[1:-1]
        wrapper = [opening, *([begin_line] if begin_line else [])]
        suffix = [*([end_line] if end_line else []), closing]
        wrapper_size = len("\n".join(wrapper + suffix)) + 1
        available = max(1, self._content_limit - wrapper_size)
        formula_body = "\n".join(body_lines)
        units = [unit.strip() for unit in FORMULA_ROW_BOUNDARY_PATTERN.split(formula_body) if unit.strip()]
        if len(units) <= 1:
            units = self._semantic_parts(formula_body, available)

        drafts: list[_ChunkDraft] = []
        current_units: list[str] = []
        for unit in units:
            candidate_units = [*current_units, unit]
            candidate_body = " \\\\\n".join(candidate_units)
            candidate = "\n".join([*wrapper, candidate_body, *suffix])
            if len(candidate) <= self._content_limit:
                current_units = candidate_units
                continue
            if current_units:
                body = " \\\\\n".join(current_units)
                drafts.append(self._draft_for_text("\n".join([*wrapper, body, *suffix]), block))
                current_units = []
            for part in self._semantic_parts(unit, available):
                current_units.append(part)
        if current_units:
            body = " \\\\\n".join(current_units)
            drafts.append(self._draft_for_text("\n".join([*wrapper, body, *suffix]), block))
        return drafts

    def _semantic_parts(self, text: str, limit: int) -> list[str]:
        normalized = normalize_searchable_text(text)
        if len(normalized) <= limit:
            return [normalized]
        sentence_units = [unit.strip() for unit in SENTENCE_BOUNDARY_PATTERN.split(normalized) if unit.strip()]
        units: list[str] = []
        for sentence in sentence_units:
            if len(sentence) <= limit:
                units.append(sentence)
                continue
            clause_units = [unit.strip() for unit in CLAUSE_BOUNDARY_PATTERN.split(sentence) if unit.strip()]
            if len(clause_units) > 1:
                units.extend(clause_units)
                continue
            units.extend(self._split_on_whitespace_or_width(sentence, limit))

        parts: list[str] = []
        current = ""
        for unit in units:
            if len(unit) > limit:
                if current:
                    parts.append(current)
                    current = ""
                parts.extend(self._bounded_without_overlap(unit, limit))
                continue
            candidate = f"{current}\n{unit}" if current else unit
            if len(candidate) <= limit:
                current = candidate
            else:
                parts.append(current)
                current = unit
        if current:
            parts.append(current)
        return parts

    def _split_on_whitespace_or_width(self, text: str, limit: int) -> list[str]:
        words = text.split()
        if len(words) <= 1:
            return self._bounded_without_overlap(text, limit)
        parts: list[str] = []
        current = ""
        for word in words:
            if len(word) > limit:
                if current:
                    parts.append(current)
                    current = ""
                parts.extend(self._bounded_without_overlap(word, limit))
                continue
            candidate = f"{current} {word}" if current else word
            if len(candidate) <= limit:
                current = candidate
            else:
                parts.append(current)
                current = word
        if current:
            parts.append(current)
        return parts

    def _bounded_parts(self, block: str) -> list[str]:
        if len(block) <= self._content_limit:
            return [block]
        parts: list[str] = []
        start = 0
        while start < len(block):
            end = min(start + self._content_limit, len(block))
            part = block[start:end].strip()
            if part:
                parts.append(part)
            if end >= len(block):
                break
            start = max(end - self.overlap, start + 1)
        return parts

    @staticmethod
    def _bounded_without_overlap(text: str, limit: int) -> list[str]:
        return [text[index : index + limit].strip() for index in range(0, len(text), limit) if text[index : index + limit].strip()]

    def _normalize_block(
        self,
        raw_block: Mapping[str, Any],
        page_number: int | None,
        fallback_index: int,
    ) -> _StructuralBlock | None:
        block_type = str(raw_block.get("block_type") or raw_block.get("type") or raw_block.get("category") or "text").lower()
        if block_type == "table" or "table" in block_type:
            text = render_table_block_text(raw_block)
            block_type = "table"
        else:
            text = self._first_text(raw_block)
        text = normalize_searchable_text(text)
        if not text:
            return None
        if block_type not in ATOMIC_BLOCK_TYPES | HEADING_BLOCK_TYPES:
            block_type = self._infer_text_block_type(text)
        return _StructuralBlock(
            block_type=block_type,
            text=text,
            page_number=page_number,
            block_index=int(raw_block.get("block_index") or fallback_index),
        )

    @staticmethod
    def _page_blocks(page: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
        for key in ("clean_blocks", "blocks", "page_blocks"):
            if key not in page:
                continue
            value = page.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
        return None

    @staticmethod
    def _first_text(block: Mapping[str, Any]) -> str:
        for key in TEXT_KEYS:
            value = block.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _page_number(page: Mapping[str, Any]) -> int | None:
        value = page.get("page_number") or page.get("page_no")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _infer_text_block_type(self, text: str) -> str:
        first_line = text.split("\n", 1)[0].strip()
        if text.startswith("$$") or text.startswith("\\["):
            return "formula"
        if TABLE_ROW_PATTERN.match(first_line):
            return "table"
        if TABLE_CAPTION_PATTERN.match(first_line):
            return "table_caption"
        if self._looks_like_heading(text):
            return "heading"
        return "text"

    @staticmethod
    def _looks_like_heading(text: str) -> bool:
        first_line = text.split("\n", 1)[0].strip()
        if MEASUREMENT_PATTERN.fullmatch(first_line):
            return False
        return bool(first_line and len(first_line) <= 120 and HEADING_PATTERN.match(first_line))

    def _fits(self, current: str, text: str) -> bool:
        return len(text) <= self._content_limit and len(current) + (1 if current else 0) + len(text) <= self._content_limit

    def _append_block(self, draft: _ChunkDraft, block: _StructuralBlock) -> None:
        draft.parts.append(block.text)
        if block.page_number is not None and block.page_number not in draft.page_numbers:
            draft.page_numbers.append(block.page_number)
        if block.block_type not in draft.block_types:
            draft.block_types.append(block.block_type)

    def _draft_for_text(
        self,
        text: str,
        block: _StructuralBlock,
        section_title: str | None = None,
        heading_path: list[str] | None = None,
    ) -> _ChunkDraft:
        return _ChunkDraft(
            parts=[text],
            page_numbers=[block.page_number] if block.page_number is not None else [],
            block_types=[block.block_type],
            section_title=section_title,
            heading_path=list(heading_path or []),
        )

    def _to_payload(self, chunk_index: int, draft: _ChunkDraft) -> dict:
        body = draft.content
        content = normalize_searchable_text("\n".join(part for part in (self._metadata_prefix, body) if part))
        section_title = draft.section_title or self._guess_section_title(body)
        return {
            "chunk_index": chunk_index,
            "content": content,
            "page_number": draft.page_numbers[0] if draft.page_numbers else None,
            "section_title": section_title,
            "metadata": {
                "chunk_rule_version": self.rule_version,
                "index_generation": self.index_generation,
                "page_numbers": draft.page_numbers,
                "block_types": draft.block_types,
                "heading_path": draft.heading_path or [],
                "document_metadata": dict(self._document_metadata),
            },
        }

    @staticmethod
    def _build_metadata_prefix(metadata: Mapping[str, Any]) -> str:
        document_title = metadata.get("document_title")
        return str(document_title) if document_title is not None else ""

    @staticmethod
    def _bind_table_caption(
        block: _StructuralBlock,
        pending_captions: list[_StructuralBlock],
    ) -> tuple[_StructuralBlock, _StructuralBlock | None, int | None]:
        if not pending_captions:
            return block, None, None
        caption = pending_captions[0]
        lines = [line.strip() for line in block.text.splitlines() if line.strip()]
        first_row = next((index for index, line in enumerate(lines) if TABLE_ROW_PATTERN.match(line)), None)
        if first_row is None:
            return block, None, caption.page_number
        embedded_caption = "\n".join(lines[:first_row])
        displaced = None
        if embedded_caption and embedded_caption != caption.text:
            displaced = _StructuralBlock(
                block_type="table_caption",
                text=embedded_caption,
                page_number=block.page_number,
                block_index=block.block_index,
            )
        rebound = _StructuralBlock(
            block_type="table",
            text="\n".join([caption.text, *lines[first_row:]]),
            page_number=block.page_number,
            block_index=block.block_index,
            legacy_boundary=block.legacy_boundary,
        )
        return rebound, displaced, caption.page_number

    @staticmethod
    def _attach_caption_context(drafts: list[_ChunkDraft], page_number: int | None) -> None:
        if page_number is None:
            return
        for draft in drafts:
            if page_number not in draft.page_numbers:
                draft.page_numbers.append(page_number)

    @staticmethod
    def _attach_heading_context(drafts: list[_ChunkDraft], heading_path: list[str]) -> None:
        for draft in drafts:
            draft.heading_path = list(heading_path)
            if heading_path:
                draft.section_title = heading_path[-1]

    @staticmethod
    def _seed_heading_context(draft: _ChunkDraft, heading_path: list[str]) -> None:
        if draft.heading_path is None:
            draft.heading_path = list(heading_path)
        if draft.section_title is None and heading_path:
            draft.section_title = heading_path[-1]

    @staticmethod
    def _heading_level(text: str, block_type: str) -> int:
        first_line = text.split("\n", 1)[0].strip()
        markdown_match = re.match(r"^(#{1,6})\s+", first_line)
        if markdown_match:
            return len(markdown_match.group(1))
        if re.match(r"^[一二三四五六七八九十]+[、.]", first_line) or re.match(r"^第.+[章节篇部分]", first_line):
            return 1
        if re.match(r"^\d+(?:\.\d+)+", first_line):
            return min(first_line.split()[0].count(".") + 1, 6)
        if re.match(r"^(?:（\d+）|\(\d+\))", first_line):
            return 3
        return 1 if block_type == "title" else 2

    @staticmethod
    def _looks_like_document_title(text: str) -> bool:
        first_line = text.split("\n", 1)[0].strip()
        return bool(first_line and len(first_line) <= 80 and not re.search(r"[。！？.!?;；]$", first_line))

    @staticmethod
    def _guess_section_title(text: str) -> str | None:
        first_line = text.split("\n", 1)[0].strip()
        return first_line if 0 < len(first_line) <= 80 else None
