"""当前问答上下文中的表格感知敏感内容过滤。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
import io
import re
from typing import Protocol

TABLE_MASK = "[该表格包含受限商务敏感信息，当前权限下不展示明细]"
MAX_TABLE_CHARS = 50_000
MAX_TABLE_ROWS = 500
HIGH_RISK_TITLES = re.compile(r"报价表|成本表|合同清单|供应商报价单|财务测算表|投资收益表|付款计划表")
HIGH_RISK_TITLE_TYPES = (
    (re.compile(r"供应商报价单"), ("supplier_price",)),
    (re.compile(r"报价表"), ("price",)),
    (re.compile(r"成本表"), ("cost",)),
    (re.compile(r"合同清单"), ("contract_amount",)),
    (re.compile(r"付款计划表"), ("payment_terms",)),
    (re.compile(r"财务测算表|投资收益表"), ("financial_metric", "gross_margin")),
)
TABLE_MATCH_TYPES = {"table_column", "table_row", "table_cell"}


class TableRule(Protocol):
    code: str
    sensitive_type_code: str
    match_type: str
    regex: re.Pattern[str]
    mask_text: str
    priority: int


@dataclass(frozen=True)
class TableFilterResult:
    safe_content: str
    redaction_types: tuple[str, ...] = ()
    redaction_count: int = 0
    matched_rule_codes: tuple[str, ...] = ()


@dataclass
class ParsedTable:
    rows: list[list[str]]
    format: str
    delimiter: str = ""
    header_tags: list[list[bool]] | None = None

    def render(self) -> str:
        if self.format == "html":
            parts = ["<table>"]
            for row_index, row in enumerate(self.rows):
                parts.append("<tr>")
                tags = self.header_tags[row_index] if self.header_tags and row_index < len(self.header_tags) else []
                for cell_index, cell in enumerate(row):
                    tag = "th" if cell_index < len(tags) and tags[cell_index] else "td"
                    parts.append(f"<{tag}>{escape(cell)}</{tag}>")
                parts.append("</tr>")
            parts.append("</table>")
            return "".join(parts)
        if self.format == "markdown":
            return "\n".join("| " + " | ".join(row) + " |" for row in self.rows)
        if self.format in {"csv", "tsv"}:
            output = io.StringIO(newline="")
            writer = csv.writer(output, delimiter=self.delimiter, lineterminator="\n")
            writer.writerows(self.rows)
            return output.getvalue().rstrip("\n")
        return "\n".join("    ".join(row) for row in self.rows)


class _HTMLTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.header_tags: list[list[bool]] = []
        self._row: list[str] | None = None
        self._row_tags: list[bool] | None = None
        self._cell: list[str] | None = None
        self._cell_is_header = False

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001, ARG002
        name = tag.lower()
        if name == "tr":
            self._row, self._row_tags = [], []
        elif name in {"th", "td"} and self._row is not None:
            self._cell = []
            self._cell_is_header = name == "th"

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in {"th", "td"} and self._cell is not None and self._row is not None and self._row_tags is not None:
            self._row.append("".join(self._cell).strip())
            self._row_tags.append(self._cell_is_header)
            self._cell = None
        elif name == "tr" and self._row is not None and self._row_tags is not None:
            if self._row:
                self.rows.append(self._row)
                self.header_tags.append(self._row_tags)
            self._row, self._row_tags = None, None


class TableSensitiveFilter:
    """识别局部表格，并按列、行或单元格语义执行保守脱敏。"""

    def filter(self, content: str, allowed_types: set[str], rules: tuple[TableRule, ...]) -> TableFilterResult:
        table_rules = tuple(sorted((rule for rule in rules if rule.match_type in TABLE_MATCH_TYPES), key=lambda rule: rule.priority))
        if not content or not table_rules:
            return TableFilterResult(content)
        segments = self._find_segments(content)
        if not segments:
            return TableFilterResult(content)
        safe_content = content
        redaction_types: set[str] = set()
        matched_codes: set[str] = set()
        redaction_count = 0
        for start, end, raw, format_name in reversed(segments):
            nearby = content[max(0, start - 160):start]
            parsed = self._parse(raw, format_name)
            relevant_rules = self._relevant_rules(raw + "\n" + nearby, table_rules, allowed_types)
            high_risk_types = self._high_risk_types(raw + "\n" + nearby, allowed_types)
            if parsed is None:
                if high_risk_types or self._looks_high_risk(raw, nearby, relevant_rules):
                    replacement = TABLE_MASK
                    types = high_risk_types or {rule.sensitive_type_code for rule in relevant_rules}
                    codes = {rule.code for rule in relevant_rules}
                    redaction_types.update(types)
                    matched_codes.update(codes)
                    redaction_count += 1
                    safe_content = safe_content[:start] + replacement + safe_content[end:]
                continue
            if len(raw) > MAX_TABLE_CHARS or len(parsed.rows) > MAX_TABLE_ROWS:
                if relevant_rules or high_risk_types:
                    redaction_types.update(high_risk_types or {rule.sensitive_type_code for rule in relevant_rules})
                    matched_codes.update(rule.code for rule in relevant_rules)
                    redaction_count += 1
                    safe_content = safe_content[:start] + TABLE_MASK + safe_content[end:]
                continue
            replacement, types, count, codes = self._filter_parsed(parsed, nearby, allowed_types, table_rules)
            if count:
                redaction_types.update(types)
                matched_codes.update(codes)
                redaction_count += count
                safe_content = safe_content[:start] + replacement + safe_content[end:]
        return TableFilterResult(safe_content, tuple(sorted(redaction_types)), redaction_count, tuple(sorted(matched_codes)))

    def _filter_parsed(
        self,
        table: ParsedTable,
        nearby: str,
        allowed_types: set[str],
        rules: tuple[TableRule, ...],
    ) -> tuple[str, set[str], int, set[str]]:
        if not table.rows:
            return table.render(), set(), 0, set()
        unauthorized = tuple(rule for rule in rules if rule.sensitive_type_code not in allowed_types)
        column_rules = tuple(rule for rule in unauthorized if rule.match_type == "table_column")
        row_rules = tuple(rule for rule in unauthorized if rule.match_type in {"table_column", "table_row"})
        cell_rules = tuple(rule for rule in unauthorized if rule.match_type == "table_cell")
        header_index = self._header_index(table)
        header = table.rows[header_index]
        column_matches = {index: self._first_match(cell, column_rules) for index, cell in enumerate(header)}
        column_matches = {index: rule for index, rule in column_matches.items() if rule is not None}
        relevant = self._relevant_rules(" ".join(header) + " " + nearby, rules, allowed_types)
        high_risk_types = self._high_risk_types(nearby, allowed_types)
        if high_risk_types or len(column_matches) >= 3:
            return TABLE_MASK, high_risk_types or {rule.sensitive_type_code for rule in relevant or column_matches.values()}, 1, {
                rule.code for rule in relevant or column_matches.values()
            }
        types: set[str] = set()
        codes: set[str] = set()
        count = 0
        for row_index, row in enumerate(table.rows):
            if row_index == header_index or self._is_markdown_separator(row):
                continue
            row_rule = self._first_match(row[0] if row else "", row_rules)
            if row_rule is not None:
                for cell_index in range(1, len(row)):
                    if row[cell_index] != row_rule.mask_text:
                        row[cell_index] = row_rule.mask_text
                        count += 1
                types.add(row_rule.sensitive_type_code)
                codes.add(row_rule.code)
                continue
            for cell_index, cell in enumerate(row):
                rule = column_matches.get(cell_index) or self._first_match(cell, cell_rules)
                if rule is None:
                    continue
                row[cell_index] = rule.mask_text
                types.add(rule.sensitive_type_code)
                codes.add(rule.code)
                count += 1
        return table.render(), types, count, codes

    @staticmethod
    def _first_match(value: str, rules: tuple[TableRule, ...]) -> TableRule | None:
        return next((rule for rule in rules if rule.regex.search(value.strip())), None)

    @staticmethod
    def _header_index(table: ParsedTable) -> int:
        if table.header_tags:
            for index, tags in enumerate(table.header_tags):
                if any(tags):
                    return index
        return 0

    @staticmethod
    def _is_markdown_separator(row: list[str]) -> bool:
        return bool(row) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in row)

    @staticmethod
    def _relevant_rules(text: str, rules: tuple[TableRule, ...], allowed_types: set[str]) -> tuple[TableRule, ...]:
        return tuple(rule for rule in rules if rule.sensitive_type_code not in allowed_types and rule.regex.search(text))

    @staticmethod
    def _looks_high_risk(raw: str, nearby: str, relevant_rules: tuple[TableRule, ...]) -> bool:
        return bool(HIGH_RISK_TITLES.search(nearby + raw) or len({rule.sensitive_type_code for rule in relevant_rules}) >= 2)

    @staticmethod
    def _high_risk_types(text: str, allowed_types: set[str]) -> set[str]:
        return {
            type_code
            for title_pattern, type_codes in HIGH_RISK_TITLE_TYPES
            if title_pattern.search(text)
            for type_code in type_codes
            if type_code not in allowed_types
        }

    def _find_segments(self, content: str) -> list[tuple[int, int, str, str]]:
        segments = [(match.start(), match.end(), match.group(0), "html") for match in re.finditer(r"<table\b[^>]*>.*?</table\s*>", content, re.I | re.S)]
        occupied = [(start, end) for start, end, _, _ in segments]
        offset = 0
        current: list[tuple[int, str]] = []
        for line in content.splitlines(keepends=True):
            line_start = offset
            offset += len(line)
            if any(start <= line_start < end for start, end in occupied):
                current = []
                continue
            stripped = line.rstrip("\r\n")
            if self._line_is_table_like(stripped):
                current.append((line_start, line))
                continue
            self._append_line_segment(segments, current)
            current = []
        self._append_line_segment(segments, current)
        return sorted(segments, key=lambda item: item[0])

    def _append_line_segment(self, segments: list[tuple[int, int, str, str]], lines: list[tuple[int, str]]) -> None:
        if len(lines) < 2:
            return
        raw = "".join(line for _, line in lines).rstrip("\r\n")
        format_name = self._detect_line_format(raw)
        if format_name:
            segments.append((lines[0][0], lines[0][0] + len(raw), raw, format_name))

    @staticmethod
    def _line_is_table_like(line: str) -> bool:
        return line.count("|") >= 2 or "\t" in line or line.count(",") >= 1 or bool(re.search(r"\S\s{2,}\S", line))

    @staticmethod
    def _detect_line_format(raw: str) -> str | None:
        lines = raw.splitlines()
        if all(line.count("|") >= 2 for line in lines):
            return "markdown"
        if all("\t" in line for line in lines):
            return "tsv"
        if all("," in line for line in lines):
            return "csv"
        if all(re.search(r"\S\s{2,}\S", line) for line in lines):
            return "spaces"
        return None

    def _parse(self, raw: str, format_name: str) -> ParsedTable | None:
        try:
            if format_name == "html":
                parser = _HTMLTableParser()
                parser.feed(raw)
                return self._validated(ParsedTable(parser.rows, "html", header_tags=parser.header_tags))
            if format_name == "markdown":
                rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in raw.splitlines()]
                return self._validated(ParsedTable(rows, "markdown"))
            if format_name in {"csv", "tsv"}:
                delimiter = "," if format_name == "csv" else "\t"
                rows = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(raw), delimiter=delimiter)]
                return self._validated(ParsedTable(rows, format_name, delimiter))
            rows = [[cell.strip() for cell in re.split(r"\s{2,}", line.strip())] for line in raw.splitlines()]
            return self._validated(ParsedTable(rows, "spaces"))
        except (csv.Error, ValueError):
            return None

    @staticmethod
    def _validated(table: ParsedTable) -> ParsedTable | None:
        widths = {len(row) for row in table.rows if row}
        if len(table.rows) < 2 or len(widths) != 1 or next(iter(widths), 0) < 2:
            return None
        return table
