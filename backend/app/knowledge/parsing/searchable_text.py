"""
Searchable text helpers for parsed pages.

职责：
1. 将 MinerU 页级解析结果整理为用于 Chunk 和 PageIndex 的统一检索文本。
2. 将表格块中的 HTML/结构化内容转换为可向量化、可关键词检索的纯文本。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import re
from typing import Any


TEXT_KEYS = ("clean_content", "clean_text", "content", "text", "markdown", "md")
BLOCK_KEYS = ("clean_blocks", "blocks", "page_blocks")
TABLE_BODY_KEYS = ("table_body", "table_html", "html")
TABLE_CAPTION_KEYS = ("table_caption", "caption", "table_title", "title")
TABLE_TYPE_HINT = "table"
WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(slots=True)
class _TableCell:
    text: str
    rowspan: int = 1
    colspan: int = 1


class _TableHTMLParser(HTMLParser):
    """把简单 HTML table 解析成行列文本，供检索索引使用。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[_TableCell]] = []
        self._current_row: list[_TableCell] | None = None
        self._current_cell: list[str] | None = None
        self._current_rowspan = 1
        self._current_colspan = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "tr":
            self._current_row = []
        elif normalized_tag in {"td", "th"}:
            if self._current_row is None:
                self._current_row = []
            self._current_cell = []
            attr_map = dict(attrs)
            self._current_rowspan = _parse_span(attr_map.get("rowspan"))
            self._current_colspan = _parse_span(attr_map.get("colspan"))
        elif normalized_tag == "br" and self._current_cell is not None:
            self._current_cell.append("\n")

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in {"td", "th"} and self._current_cell is not None:
            cell_text = _clean_inline_text("".join(self._current_cell))
            if self._current_row is None:
                self._current_row = []
            self._current_row.append(
                _TableCell(
                    text=cell_text,
                    rowspan=self._current_rowspan,
                    colspan=self._current_colspan,
                )
            )
            self._current_cell = None
            self._current_rowspan = 1
            self._current_colspan = 1
        elif normalized_tag == "tr" and self._current_row is not None:
            if any(cell.text for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None


def build_page_searchable_text(page: Mapping[str, Any]) -> str:
    """
    构建页级可检索文本。

    MinerU 的表格正文经常只存在于 block.metadata.table_body，原始 page content
    不包含单元格内容。这里把表格内容追加到正文后，确保 Chunk、PageIndex 和向量索引一致。
    """

    content = (
        normalize_searchable_text(page.get("clean_content"))
        if "clean_content" in page
        else normalize_searchable_text(_first_text(page))
    )
    searchable_parts = [content] if content else []

    for block in _iter_blocks(page):
        table_text = render_table_block_text(block)
        if table_text and not _contains_text("\n".join(searchable_parts), table_text):
            searchable_parts.append(table_text)

    return normalize_searchable_text("\n\n".join(searchable_parts))


def render_table_block_text(block: Mapping[str, Any]) -> str:
    """将 table block 转换成适合检索的文本。"""

    if not _is_table_block(block):
        return ""

    metadata = block.get("metadata") if isinstance(block.get("metadata"), Mapping) else {}
    parts: list[str] = []

    for key in TABLE_CAPTION_KEYS:
        caption = _metadata_value(block, metadata, key)
        parts.extend(_value_to_lines(caption))

    explicit_text = normalize_searchable_text(_first_text(block))
    if explicit_text:
        parts.append(explicit_text)

    for key in TABLE_BODY_KEYS:
        body = _metadata_value(block, metadata, key)
        body_text = _render_table_body(body)
        if body_text:
            parts.append(body_text)
            break

    deduped_parts: list[str] = []
    for part in parts:
        normalized_part = normalize_searchable_text(part)
        if normalized_part and not _contains_text("\n".join(deduped_parts), normalized_part):
            deduped_parts.append(normalized_part)
    return normalize_searchable_text("\n".join(deduped_parts))


def normalize_searchable_text(text: Any) -> str:
    """清理检索文本的换行和首尾空白。"""

    lines = [line.strip() for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line)


def _iter_blocks(page: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in BLOCK_KEYS:
        blocks = page.get(key)
        if isinstance(blocks, list):
            return [
                block
                for block in blocks
                if isinstance(block, Mapping) and str(block.get("filter_status") or "").lower() != "filtered"
            ]
    return []


def _first_text(payload: Mapping[str, Any]) -> str:
    for key in TEXT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_table_block(block: Mapping[str, Any]) -> bool:
    raw_type = str(block.get("block_type") or block.get("type") or block.get("category") or "").lower()
    if TABLE_TYPE_HINT in raw_type:
        return True
    metadata = block.get("metadata") if isinstance(block.get("metadata"), Mapping) else {}
    return any(_metadata_value(block, metadata, key) for key in TABLE_BODY_KEYS)


def _metadata_value(block: Mapping[str, Any], metadata: Mapping[str, Any], key: str) -> Any:
    if key in metadata:
        return metadata[key]
    return block.get(key)


def _render_table_body(value: Any) -> str:
    if isinstance(value, str):
        if not value.strip():
            return ""
        if _looks_like_html_table(value):
            return _html_table_to_text(value)
        return normalize_searchable_text(unescape(value))

    if isinstance(value, list):
        if all(isinstance(row, list | tuple) for row in value):
            return _rows_to_text([[str(cell) for cell in row] for row in value])
        return normalize_searchable_text("\n".join(_value_to_lines(value)))

    return ""


def _html_table_to_text(html: str) -> str:
    parser = _TableHTMLParser()
    parser.feed(html)
    parser.close()
    if parser.rows:
        return _rows_to_text(_expand_table_spans(parser.rows))
    return normalize_searchable_text(re.sub(r"<[^>]+>", " ", unescape(html)))


def _expand_table_spans(raw_rows: list[list[_TableCell]]) -> list[list[str]]:
    """
    展开 HTML 表格的 rowspan/colspan。

    合并单元格在原始 HTML 中只出现在第一行，若不展开会导致后续行列错位，
    进而让问答把设计计算值误判为 Min/Max。
    """

    expanded_rows: list[list[str]] = []
    active_spans: dict[int, tuple[int, str]] = {}

    for raw_row in raw_rows:
        row: list[str] = []
        next_spans: dict[int, tuple[int, str]] = {}
        column_index = 0

        def fill_active_spans() -> None:
            nonlocal column_index
            while column_index in active_spans:
                remaining_rows, text = active_spans[column_index]
                row.append(text)
                if remaining_rows > 1:
                    next_spans[column_index] = (remaining_rows - 1, text)
                column_index += 1

        for cell in raw_row:
            fill_active_spans()
            for _ in range(cell.colspan):
                row.append(cell.text)
                if cell.rowspan > 1:
                    next_spans[column_index] = (cell.rowspan - 1, cell.text)
                column_index += 1

        while any(span_column >= column_index for span_column in active_spans):
            if column_index in active_spans:
                fill_active_spans()
                continue
            next_span_column = min(span_column for span_column in active_spans if span_column >= column_index)
            while column_index < next_span_column:
                row.append("")
                column_index += 1

        expanded_rows.append(row)
        active_spans = next_spans

    max_width = max((len(row) for row in expanded_rows), default=0)
    return [row + [""] * (max_width - len(row)) for row in expanded_rows]


def _rows_to_text(rows: list[list[str]]) -> str:
    lines: list[str] = []
    for row in rows:
        cells = [_clean_inline_text(cell) for cell in row]
        if any(cells):
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _value_to_lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list | tuple | set):
        lines: list[str] = []
        for item in value:
            lines.extend(_value_to_lines(item))
        return lines
    return [str(value).strip()] if str(value).strip() else []


def _looks_like_html_table(value: str) -> bool:
    normalized = value.lower()
    return "<table" in normalized or "<tr" in normalized or "<td" in normalized or "<th" in normalized


def _contains_text(haystack: str, needle: str) -> bool:
    normalized_haystack = _squash_text(haystack)
    normalized_needle = _squash_text(needle)
    return bool(normalized_needle and normalized_needle in normalized_haystack)


def _squash_text(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", value or "").strip().lower()


def _clean_inline_text(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", unescape(str(value or ""))).strip()


def _parse_span(value: str | None) -> int:
    try:
        span = int(value or 1)
    except (TypeError, ValueError):
        return 1
    return max(span, 1)
