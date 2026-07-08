"""
Retrieval query utilities.

Shared helpers for query normalization, keyword extraction, phrase expansion,
and lightweight relevance scoring across retrievers and rerankers.
"""

from __future__ import annotations

import re
from typing import Iterable


CHINESE_STOPWORDS = {
    "介绍",
    "说明",
    "项目",
    "一个",
    "请问",
    "请",
    "这个",
    "该项",
    "是什么",
    "多少",
    "哪些",
}

ENGLISH_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

PROJECT_OVERVIEW_HINTS = {"介绍", "概况", "简介", "overview", "introduce", "introduction", "project"}
BOILERPLATE_HINTS = (
    "property of",
    "shall not be reproduced",
    "transferred to a third party",
    "未经书面许可",
    "不准复制",
    "版权所有",
)
TOC_HINTS = ("table of contents", "目录", "contents")
VALUE_LOOKUP_HINTS = (
    "最大",
    "最小",
    "最大值",
    "最小值",
    "上限",
    "下限",
    "范围",
    "数值",
    "设计值",
    "计算值",
    "max",
    "min",
    "maximum",
    "minimum",
)
TABLE_LOOKUP_HINTS = ("表格", "元素", "成分", "含量", "percentage", "element", "calculation", "calculation in design", "wt%")
LIST_LOOKUP_HINTS = ("哪些", "列表", "清单", "明细", "名称", "一览", "list", "listing", "items", "names")
LIST_TARGET_HINTS = (
    "产品",
    "最终产品",
    "product",
    "final product",
    "equipment",
    "设备",
    "material",
    "物料",
    "raw material",
    "原料",
    "component",
    "部件",
    "subproject",
    "分项",
)
PRODUCT_LIST_PHRASES = ("Product List", "Product Name", "Products", "Final Product")
EQUIPMENT_LIST_PHRASES = ("Equipment List", "Equipment Name", "Equipment")
MATERIAL_LIST_PHRASES = ("Material List", "Material Name", "Materials", "Raw Material")
ELEMENT_SYMBOL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:Li|Ni|Co|Mn|Al|Cu|Fe|Ca|Mg|PVDF|PAA|C|O|P|F)(?![A-Za-z0-9])"
)
TABLE_ROW_PATTERN = re.compile(r"\|\s*\d+\s*\|")


def normalize_query_text(text: str) -> str:
    """
    Normalize query/content text for retrieval.
    """

    normalized = (
        text.replace("脳", "x")
        .replace("×", "x")
        .replace("＊", "*")
        .replace("／", "/")
    )
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"(\d)\s*[xX*]\s*(\d)", r"\1x\2", normalized)
    return normalized.strip()


def extract_query_terms(query: str, include_chinese_chars: bool = False) -> list[str]:
    """
    Extract de-duplicated query terms.
    """

    normalized = normalize_query_text(query).lower()
    terms = re.findall(r"[a-z0-9]+(?:[._\-/][a-z0-9]+)*|[\u4e00-\u9fff]{2,}", normalized)
    if include_chinese_chars:
        terms.extend(char for char in normalized if "\u4e00" <= char <= "\u9fff")
    return _dedupe(item for item in terms if _is_meaningful_term(item))


def expand_search_phrases(query: str) -> list[str]:
    """
    Expand query into retrieval-friendly phrases.
    """

    normalized = normalize_query_text(query)
    normalized_lower = normalized.lower()
    phrases: list[str] = [normalized]
    domain_phrases: list[str] = []

    english_spans = re.findall(r"[A-Za-z0-9][A-Za-z0-9&.,()/#\- xX*]{2,}", normalized)
    phrases.extend(span.strip(" ,.;:") for span in english_spans)

    if "black mass" in normalized_lower:
        domain_phrases.extend(["Black Mass", "Battery Black Mass", "Battery Black Mass Recycling Project"])
    if re.search(r"\b\d+\s*tpa\b", normalized_lower):
        domain_phrases.extend(re.findall(r"\b\d+\s*tpa\b", normalized, flags=re.IGNORECASE))
    if re.search(r"\b\d+x\d+\s*tpa\b", normalized_lower):
        domain_phrases.extend(re.findall(r"\b\d+x\d+\s*tpa\b", normalized, flags=re.IGNORECASE))
    if any(hint in normalized_lower for hint in ("最大", "max", "maximum")):
        domain_phrases.extend(["Max", "Maximum"])
    if any(hint in normalized_lower for hint in ("最小", "min", "minimum")):
        domain_phrases.extend(["Min", "Minimum"])
    if any(hint in normalized_lower for hint in ("计算", "calculation")):
        domain_phrases.append("Calculation in design")
    if is_project_overview_query(query):
        domain_phrases.extend(["Project overview", "Design Basis", "Plant Capacity", "Production Capacity", "Products", "Client"])
    if is_structured_list_lookup_query(query):
        domain_phrases.extend(structured_lookup_phrases(query))

    phrases.extend(domain_phrases)
    phrases.extend(extract_query_terms(normalized))

    return _dedupe(item for item in phrases if len(item.strip()) >= 3)[:16]


def score_text_relevance(content: str, query: str, terms: list[str] | None = None) -> float:
    """
    Lightweight lexical relevance scoring with a few domain-specific boosts.
    """

    normalized_content = normalize_query_text(content).lower()
    normalized_query = normalize_query_text(query).lower()
    query_terms = terms if terms is not None else extract_query_terms(query)
    phrases = [phrase.lower() for phrase in expand_search_phrases(query)]

    score = 0.0
    if normalized_query and normalized_query in normalized_content:
        score += 8.0
    for phrase in phrases:
        if phrase and contains_search_token(normalized_content, phrase):
            score += 2.5 if " " in phrase else 1.2
    for term in query_terms:
        count = count_search_token(normalized_content, term.lower())
        if count:
            score += 1.0 + min(count, 5) * 0.25

    if is_table_value_lookup_query(query):
        element_symbols = extract_element_symbols(query)
        matched_symbols = [symbol for symbol in element_symbols if contains_search_token(normalized_content, symbol.lower())]
        if element_symbols and not matched_symbols:
            score *= 0.25
        elif matched_symbols:
            score += 6.0 + len(matched_symbols) * 2.0
            if "min" in normalized_content and "max" in normalized_content:
                score += 2.0
            if "percentage" in normalized_content or "wt%" in normalized_content:
                score += 2.0
            if any(re.search(rf"\|\s*{re.escape(symbol.lower())}\s*\|", normalized_content) for symbol in matched_symbols):
                score += 4.0

    if is_project_overview_query(query):
        if "plant capacity" in normalized_content or "production capacity" in normalized_content:
            score += 3.0
        if "design basis" in normalized_content:
            score += 2.0
        if "client" in normalized_content:
            score += 1.5

    if is_structured_list_lookup_query(query):
        if TABLE_ROW_PATTERN.search(normalized_content):
            score += 3.0
        if normalized_content.count("|") >= 6:
            score += 1.5

    return max(0.0, score * boilerplate_multiplier(content))


def contains_search_token(normalized_content: str, token: str) -> bool:
    """
    Whether the normalized content contains the token.
    """

    return count_search_token(normalized_content, token) > 0


def count_search_token(normalized_content: str, token: str) -> int:
    """
    Count token hits using boundaries for short Latin tokens.
    """

    normalized_token = normalize_query_text(token).lower().strip()
    if not normalized_content or not normalized_token:
        return 0
    if _requires_word_boundary(normalized_token):
        right_boundary = r"(?![a-z0-9_])"
        if normalized_token == "co":
            # Avoid matching company suffixes like "CO., LTD" for cobalt queries.
            right_boundary = r"(?![a-z0-9_\.])"
        pattern = re.compile(rf"(?<![a-z0-9_]){re.escape(normalized_token)}{right_boundary}", re.IGNORECASE)
        return len(pattern.findall(normalized_content))
    return normalized_content.count(normalized_token)


def boilerplate_multiplier(content: str) -> float:
    """
    Down-rank boilerplate and TOC-like content.
    """

    text = normalize_query_text(content).lower()
    multiplier = 1.0
    if any(hint in text for hint in BOILERPLATE_HINTS):
        multiplier *= 0.25
    if any(hint in text for hint in TOC_HINTS) or re.search(r"\.{8,}\s*\d+", text):
        multiplier *= 0.45
    return multiplier


def is_project_overview_query(query: str) -> bool:
    """
    Whether the query asks for project overview-style information.
    """

    lowered = normalize_query_text(query).lower()
    return any(hint in lowered for hint in PROJECT_OVERVIEW_HINTS)


def is_table_value_lookup_query(query: str) -> bool:
    """
    Whether the query looks like a table value lookup.
    """

    normalized = normalize_query_text(query)
    lowered = normalized.lower()
    has_value_hint = any(hint in lowered for hint in VALUE_LOOKUP_HINTS)
    has_table_hint = any(hint in lowered for hint in TABLE_LOOKUP_HINTS)
    return has_value_hint and (has_table_hint or bool(extract_element_symbols(normalized)))


def is_structured_list_lookup_query(query: str) -> bool:
    """
    Detect list-like lookup questions that usually map to table/list pages.
    """

    lowered = normalize_query_text(query).lower()
    has_list_intent = any(hint in lowered for hint in LIST_LOOKUP_HINTS)
    has_list_target = any(hint in lowered for hint in LIST_TARGET_HINTS)
    return has_list_intent and has_list_target


def structured_lookup_phrases(query: str) -> list[str]:
    """
    English aliases commonly used by product/equipment/material list documents.
    """

    lowered = normalize_query_text(query).lower()
    phrases: list[str] = []
    if any(hint in lowered for hint in ("产品", "最终产品", "product", "final product")):
        phrases.extend(PRODUCT_LIST_PHRASES)
    if any(hint in lowered for hint in ("equipment", "设备")):
        phrases.extend(EQUIPMENT_LIST_PHRASES)
    if any(hint in lowered for hint in ("material", "raw material", "物料", "原料")):
        phrases.extend(MATERIAL_LIST_PHRASES)
    return _dedupe(phrases)


def augment_query_terms(query: str, base_terms: list[str] | None = None) -> list[str]:
    """
    Add narrow structured-list aliases without broadening normal queries too much.
    """

    candidates = list(base_terms or extract_query_terms(query))
    candidates.extend(structured_lookup_phrases(query))
    return _dedupe(candidates)


def extract_element_symbols(query: str) -> list[str]:
    """
    Extract common material-table element symbols from the query.
    """

    return _dedupe(match.group(0) for match in ELEMENT_SYMBOL_PATTERN.finditer(query))


def _is_meaningful_term(term: str) -> bool:
    """
    Whether the extracted term is useful for retrieval.
    """

    normalized = term.lower().strip()
    if not normalized:
        return False
    if normalized in ENGLISH_STOPWORDS or normalized in CHINESE_STOPWORDS:
        return False
    if any(stopword in normalized for stopword in CHINESE_STOPWORDS) and len(normalized) <= 4:
        return False
    if len(normalized) == 1 and not normalized.isdigit():
        return False
    return True


def _requires_word_boundary(token: str) -> bool:
    """
    Latin/number tokens should use word boundaries instead of raw substring match.
    """

    return bool(re.fullmatch(r"[a-z0-9]+(?:[._\-/][a-z0-9]+)*", token))


def _dedupe(items: Iterable[str]) -> list[str]:
    """
    Preserve order while de-duplicating normalized strings.
    """

    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = normalize_query_text(str(item))
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        result.append(normalized)
        seen.add(key)
    return result
