"""Query profile service.

负责在查询拆解后生成轻量查询画像，为检索规划、证据判断和最终回答提供稳定的规则信号。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.retrieval.query_utils import extract_element_symbols, extract_query_terms, normalize_query_text
from app.services.industry_domain_rules import detect_industry_domains

logger = logging.getLogger(__name__)

QUERY_TYPES = {
    "pure_general_qa",
    "industry_knowledge_qa",
    "project_qa",
    "exact_lookup",
    "page_location",
    "graph_reasoning",
    "project_overview",
    "comparison",
    "process_flow",
    "unknown",
}
ANSWER_SHAPES = {
    "direct_answer",
    "direct_value",
    "process_steps",
    "project_summary",
    "comparison_table",
    "source_location",
    "general",
}

EXACT_LOOKUP_HINTS = (
    "多少",
    "最小值",
    "最大值",
    "重量",
    "温度",
    "流量",
    "参数",
    "指标",
    "编号",
    "位号",
    "型号",
    "数值",
    "单位",
    "设计值",
    "max",
    "min",
    "maximum",
    "minimum",
    "temperature",
    "weight",
    "flow",
)
PAGE_LOCATION_HINTS = (
    "在哪页",
    "哪页",
    "哪一页",
    "哪张图",
    "来源",
    "出处",
    "图号",
    "页码",
    "图纸",
    "drawing",
    "page",
)
PROCESS_FLOW_HINTS = (
    "流程",
    "全流程",
    "从哪里到哪里",
    "上下游",
    "物料流向",
    "设备连接",
    "工艺路线",
    "流向",
    "flow",
    "upstream",
    "downstream",
    "connection",
)
GRAPH_REASONING_HINTS = (
    "上下游",
    "物料流向",
    "设备连接",
    "关系",
    "关联",
    "影响",
    "依赖",
    "导致",
    "因果",
    "跨文件",
    "relation",
    "impact",
    "dependency",
    "cause",
)
PROJECT_OVERVIEW_HINTS = (
    "介绍项目",
    "项目概况",
    "项目简介",
    "建设内容",
    "处理规模",
    "项目定位",
    "overview",
    "project overview",
    "introduce",
)
COMPARISON_HINTS = (
    "对比",
    "比较",
    "区别",
    "差异",
    "哪个更好",
    "方案",
    "compare",
    "comparison",
    "difference",
    "versus",
)

DOC_CODE_PATTERN = re.compile(r"\b[A-Z]{1,10}[A-Z0-9]*[-_/][A-Z0-9]{2,}(?:[-_/][A-Z0-9]{2,})*\b", re.IGNORECASE)
TAG_PATTERN = re.compile(r"\b[A-Z]{1,6}[-_/]?\d{2,}[A-Z0-9_-]*\b", re.IGNORECASE)
ENGLISH_PHRASE_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9&./#()_-]*(?:\s+[A-Za-z0-9&./#()_-]+){1,5}\b")


class QueryProfileService:
    """规则型查询画像服务。"""

    def build_profile(
        self,
        question: str,
        intent: str | None = None,
        sub_queries: list[str] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """生成查询画像，不调用 LLM。"""

        normalized = normalize_query_text(question)
        lowered = normalized.lower()
        reasons: list[str] = []
        industry_domains = detect_industry_domains(question)
        is_industry_domain = bool(industry_domains) or intent == "industry_knowledge_qa"
        knowledge_scope = self._knowledge_scope(intent, is_industry_domain)

        has_doc_code = bool(DOC_CODE_PATTERN.search(normalized))
        has_tag = bool(TAG_PATTERN.search(normalized))
        project_name_candidates = self._english_phrases(normalized)
        has_project_name = bool(project_name_candidates)
        need_page_location = self._contains_any(lowered, PAGE_LOCATION_HINTS)
        need_exact_term = self._contains_any(lowered, EXACT_LOOKUP_HINTS) or has_doc_code or has_tag
        explicit_visual_hint = need_page_location or any(
            token in lowered for token in ("图纸", "drawing", "diagram", "pid", "p&id", "pfd")
        )
        need_graph_reasoning = self._contains_any(lowered, GRAPH_REASONING_HINTS)

        if intent in {"greeting", "pure_general_qa", "general_qa"}:
            query_type = "pure_general_qa" if intent != "greeting" else "unknown"
            answer_shape = "direct_answer"
            reasons.append("直答问题不进入知识库检索")
        elif need_page_location:
            query_type = "page_location"
            answer_shape = "source_location"
            reasons.append("命中页码/图纸定位信号")
        elif self._contains_any(lowered, COMPARISON_HINTS):
            query_type = "comparison"
            answer_shape = "comparison_table"
            reasons.append("命中对比类信号")
        elif self._contains_any(lowered, PROJECT_OVERVIEW_HINTS):
            query_type = "project_overview"
            answer_shape = "project_summary"
            reasons.append("命中项目概况类信号")
        elif self._contains_any(lowered, PROCESS_FLOW_HINTS):
            query_type = "graph_reasoning" if need_graph_reasoning else "process_flow"
            answer_shape = "process_steps"
            reasons.append("命中流程/物料流向信号")
        elif need_graph_reasoning:
            query_type = "graph_reasoning"
            answer_shape = "process_steps"
            reasons.append("命中关系推理信号")
        elif need_exact_term:
            query_type = "exact_lookup"
            answer_shape = "direct_value"
            reasons.append("命中参数/编号/精确词项信号")
        elif intent == "industry_knowledge_qa":
            query_type = "industry_knowledge_qa"
            answer_shape = "general"
            reasons.append("命中行业基础知识意图")
        elif intent in {"project_qa", "project_overview", "exact_lookup", "page_location", "graph_reasoning"}:
            query_type = "project_qa" if intent == "project_qa" else str(intent)
            answer_shape = {
                "project_overview": "project_summary",
                "exact_lookup": "direct_value",
                "page_location": "source_location",
                "graph_reasoning": "process_steps",
            }.get(query_type, "general")
            reasons.append("沿用上游意图作为画像类型")
        else:
            query_type = "unknown"
            answer_shape = "general"
            reasons.append("未命中强规则信号")

        need_visual_asset = explicit_visual_hint or query_type in {"process_flow", "graph_reasoning", "page_location"}
        entities = self._extract_entities(normalized)
        keywords = self._extract_keywords(normalized, sub_queries or [])

        profile = {
            "query_type": self._safe_value(query_type, QUERY_TYPES, "unknown"),
            "answer_shape": self._safe_value(answer_shape, ANSWER_SHAPES, "general"),
            "need_page_location": need_page_location,
            "need_exact_term": need_exact_term,
            "has_project_name": has_project_name,
            "need_visual_asset": need_visual_asset,
            "need_graph_reasoning": need_graph_reasoning,
            "knowledge_scope": knowledge_scope,
            "is_industry_domain": is_industry_domain,
            "industry_domains": industry_domains,
            "entities": entities,
            "keywords": keywords,
            "project_name_candidates": project_name_candidates[:4],
            "reason": "；".join(reasons),
        }
        logger.info(
            "Query Profile生成完成: run_id=%s query_type=%s answer_shape=%s flags=%s entity_count=%s keyword_count=%s",
            run_id,
            profile["query_type"],
            profile["answer_shape"],
            {
                "need_page_location": profile["need_page_location"],
                "need_exact_term": profile["need_exact_term"],
                "need_visual_asset": profile["need_visual_asset"],
                "need_graph_reasoning": profile["need_graph_reasoning"],
                "knowledge_scope": profile["knowledge_scope"],
            },
            len(entities),
            len(keywords),
        )
        return profile

    def _extract_entities(self, query: str) -> list[str]:
        candidates: list[str] = []
        candidates.extend(match.group(0) for match in DOC_CODE_PATTERN.finditer(query))
        candidates.extend(match.group(0) for match in TAG_PATTERN.finditer(query))
        candidates.extend(extract_element_symbols(query))
        candidates.extend(self._english_phrases(query))
        return self._dedupe(candidates)[:16]

    def _extract_keywords(self, query: str, sub_queries: list[str]) -> list[str]:
        candidates: list[str] = []
        candidates.extend(extract_query_terms(query))
        for sub_query in sub_queries:
            candidates.extend(extract_query_terms(sub_query))
        candidates.extend(self._extract_entities(query))
        return self._dedupe(candidates)[:20]

    def _english_phrases(self, query: str) -> list[str]:
        phrases: list[str] = []
        for match in ENGLISH_PHRASE_PATTERN.finditer(query):
            phrase = match.group(0).strip(" ,.;:，。；：")
            if len(phrase) < 3:
                continue
            if phrase.lower() in {"what is", "how to", "please show"}:
                continue
            phrases.append(phrase)
        return phrases

    def _contains_any(self, text: str, hints: tuple[str, ...]) -> bool:
        return any(hint.lower() in text for hint in hints)

    def _knowledge_scope(self, intent: str | None, is_industry_domain: bool) -> str:
        if intent in {"greeting", "pure_general_qa", "general_qa"}:
            return "none"
        if intent in {"project_qa", "project_overview", "exact_lookup", "page_location", "graph_reasoning"}:
            return "project"
        if intent == "industry_knowledge_qa" or is_industry_domain:
            return "industry"
        return "industry"

    def _safe_value(self, value: str, allowed: set[str], default: str) -> str:
        return value if value in allowed else default

    def _dedupe(self, values: list[Any]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = normalize_query_text(str(value)).strip()
            key = text.lower()
            if not text or key in seen:
                continue
            result.append(text)
            seen.add(key)
        return result
