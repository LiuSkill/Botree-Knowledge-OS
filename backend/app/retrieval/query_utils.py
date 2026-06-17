"""
Retrieval Query Utilities

负责：
1. 统一在线问答中的查询归一化、关键词抽取和短语扩展
2. 为 PageIndex、ripgrep、Keyword、Reranker 提供一致的评分输入
3. 识别版权页、目录页等低价值证据并提供降权依据
"""

from __future__ import annotations

import re
from typing import Iterable


CHINESE_STOPWORDS = {
    "介绍",
    "说明",
    "项目",
    "一下",
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
ELEMENT_SYMBOL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:Li|Ni|Co|Mn|Al|Cu|Fe|Ca|Mg|PVDF|PAA|C|O|P|F)(?![A-Za-z0-9])"
)


def normalize_query_text(text: str) -> str:
    """
    归一化查询文本。

    参数:
        text: 原始查询或文档文本。

    返回:
        便于检索和匹配的归一化文本。
    """

    normalized = text.replace("×", "x").replace("＊", "*").replace("／", "/")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"(\d)\s*[xX*]\s*(\d)", r"\1x\2", normalized)
    return normalized.strip()


def extract_query_terms(query: str, include_chinese_chars: bool = False) -> list[str]:
    """
    抽取检索关键词。

    参数:
        query: 用户问题或子查询。
        include_chinese_chars: 是否保留单字中文，默认关闭以减少噪声。

    返回:
        去重后的关键词列表。
    """

    normalized = normalize_query_text(query).lower()
    terms = re.findall(r"[a-z0-9]+(?:[._\-/][a-z0-9]+)*|[\u4e00-\u9fff]{2,}", normalized)
    if include_chinese_chars:
        terms.extend(char for char in normalized if "\u4e00" <= char <= "\u9fff")
    return _dedupe(item for item in terms if _is_meaningful_term(item))


def expand_search_phrases(query: str) -> list[str]:
    """
    扩展检索短语。

    参数:
        query: 用户问题。

    返回:
        适合 PageIndex、ripgrep 和向量检索的短语列表。
    """

    normalized = normalize_query_text(query)
    normalized_lower = normalized.lower()
    phrases: list[str] = [normalized]
    domain_phrases: list[str] = []

    # 抽取连续英文/数字片段，避免中文提示词污染英文项目名匹配。
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

    # 领域短语比普通分词更接近文档中的标题和参数，必须先进入检索器模式列表。
    phrases.extend(domain_phrases)
    terms = extract_query_terms(normalized)
    phrases.extend(terms)

    return _dedupe(item for item in phrases if len(item.strip()) >= 3)[:16]


def score_text_relevance(content: str, query: str, terms: list[str] | None = None) -> float:
    """
    计算文本与查询的相关性分数。

    参数:
        content: 候选文本。
        query: 用户问题。
        terms: 可选的预抽取关键词。

    返回:
        相关性分数，已包含版权页和目录页降权。
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

    return max(0.0, score * boilerplate_multiplier(content))


def contains_search_token(normalized_content: str, token: str) -> bool:
    """
    判断 token 是否命中文本。

    英文元素符号等短 token 必须按词边界匹配，避免 Co 误命中 corrosion。
    """

    return count_search_token(normalized_content, token) > 0


def count_search_token(normalized_content: str, token: str) -> int:
    """统计 token 命中次数，英文/数字 token 使用词边界。"""

    normalized_token = normalize_query_text(token).lower().strip()
    if not normalized_content or not normalized_token:
        return 0
    if _requires_word_boundary(normalized_token):
        right_boundary = r"(?![a-z0-9_])"
        if normalized_token == "co":
            # Co 元素查询不能命中页眉中的公司缩写 CO., LTD 或化学式 CO_{3}。
            right_boundary = r"(?![a-z0-9_\.])"
        pattern = re.compile(rf"(?<![a-z0-9_]){re.escape(normalized_token)}{right_boundary}", re.IGNORECASE)
        return len(pattern.findall(normalized_content))
    return normalized_content.count(normalized_token)


def boilerplate_multiplier(content: str) -> float:
    """
    计算低价值页面降权倍数。

    参数:
        content: 候选文本。

    返回:
        0 到 1 之间的分数倍数。
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
    判断是否为项目介绍类问题。

    参数:
        query: 用户问题。

    返回:
        True 表示需要覆盖项目概况字段。
    """

    lowered = normalize_query_text(query).lower()
    return any(hint in lowered for hint in PROJECT_OVERVIEW_HINTS)


def is_table_value_lookup_query(query: str) -> bool:
    """
    判断是否为表格参数值查询。

    这类问题通常由元素符号/表格字段 + 最大最小值等值域词组成，需要避免项目页眉词干扰排序。
    """

    normalized = normalize_query_text(query)
    lowered = normalized.lower()
    has_value_hint = any(hint in lowered for hint in VALUE_LOOKUP_HINTS)
    has_table_hint = any(hint in lowered for hint in TABLE_LOOKUP_HINTS)
    return has_value_hint and (has_table_hint or bool(extract_element_symbols(normalized)))


def extract_element_symbols(query: str) -> list[str]:
    """
    从查询中抽取常见物料表元素符号。

    返回保持原大小写的去重结果，调用方可按需要转换为小写。
    """

    return _dedupe(match.group(0) for match in ELEMENT_SYMBOL_PATTERN.finditer(query))


def _is_meaningful_term(term: str) -> bool:
    """判断关键词是否有检索价值。"""

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
    """英文/数字 token 不允许按普通子串匹配。"""

    return bool(re.fullmatch(r"[a-z0-9]+(?:[._\-/][a-z0-9]+)*", token))


def _dedupe(items: Iterable[str]) -> list[str]:
    """保持顺序去重并清理空白。"""

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
