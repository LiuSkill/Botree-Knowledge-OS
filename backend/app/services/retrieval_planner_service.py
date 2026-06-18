"""
Retrieval Planner Service

负责：
1. 根据问题意图、查询特征和会话上下文生成检索计划
2. 统一管理规则 Planner、Qwen Planner 和失败回退策略
3. 输出可审计的 Retriever 选择、fallback 梯子和 skip reason
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.retrieval.query_utils import extract_query_terms, normalize_query_text
from app.services.llm_service import LLMService
from app.services.rag_prompt_templates import PLANNER_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

RETRIEVER_PAGE_INDEX = "page_index"
RETRIEVER_MILVUS = "milvus"
RETRIEVER_RIPGREP = "ripgrep"
RETRIEVER_KEYWORD = "keyword"
RETRIEVER_GRAPHRAG = "graphrag"

ALL_RETRIEVERS = [
    RETRIEVER_PAGE_INDEX,
    RETRIEVER_MILVUS,
    RETRIEVER_RIPGREP,
    RETRIEVER_KEYWORD,
    RETRIEVER_GRAPHRAG,
]

PAGE_HINT_PATTERNS = (
    "页",
    "page",
    "图纸",
    "drawing",
    "附录",
    "chapter",
    "章节",
)
SECTION_HINT_PATTERNS = (
    "条款",
    "章节",
    "section",
    "chapter",
    "clause",
    "步骤",
    "step",
)
GRAPH_HINT_PATTERNS = (
    "关系",
    "关联",
    "影响",
    "依赖",
    "原因",
    "导致",
    "上游",
    "下游",
    "relation",
    "impact",
    "dependency",
    "cause",
)
SUMMARY_HINT_PATTERNS = (
    "介绍",
    "概况",
    "概述",
    "总结",
    "总体",
    "整体",
    "overview",
    "summary",
    "introduce",
)
COMPLEX_HINT_PATTERNS = (
    "区别",
    "对比",
    "比较",
    "优缺点",
    "difference",
    "compare",
    "versus",
)
VALUE_LOOKUP_HINT_PATTERNS = (
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
TABLE_LOOKUP_HINT_PATTERNS = (
    "表格",
    "元素",
    "成分",
    "含量",
    "percentage",
    "element",
    "calculation",
    "calculation in design",
    "wt%",
)
ELEMENT_SYMBOL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:Li|Ni|Co|Mn|Al|Cu|Fe|Ca|Mg|PVDF|PAA|C|O|P|F)(?![A-Za-z0-9])"
)
DOC_CODE_PATTERN = re.compile(r"\b[A-Z]{1,8}[A-Z0-9]*[-_/][A-Z0-9]{2,}(?:[-_/][A-Z0-9]{2,})*\b", re.IGNORECASE)
EXACT_TOKEN_PATTERN = re.compile(
    r"\b[A-Z]{1,8}[A-Z0-9]*[-_/][A-Z0-9]{2,}(?:[-_/][A-Z0-9]{2,})*\b|"
    r"\b\d+(?:\.\d+){1,3}\b|"
    r"['\"“”][^'\"“”]{2,}['\"“”]"
)


@dataclass(frozen=True)
class RetrievalPlan:
    """
    检索计划

    职责：
    - 描述本次问答应执行的 Retriever
    - 描述按阶段 fallback 的执行顺序
    - 为前端 trace 和日志提供稳定结构
    """

    selected_retrievers: list[str]
    fallback_retrievers: list[str]
    fallback_ladder: list[list[str]]
    skipped_retrievers: list[str]
    skip_reasons: dict[str, str]
    query_features: dict[str, Any]
    reason: str
    confidence: float
    qwen_used: bool
    strategy: str
    rule_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    retriever_reasons: dict[str, str] = field(default_factory=dict)
    priority: list[str] = field(default_factory=list)
    query_rewrite: list[str] = field(default_factory=list)
    query_profile: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """
        序列化检索计划。

        返回：
            可直接写入 trace/raw 的字典结构。
        """

        return {
            "selected_retrievers": self.selected_retrievers,
            "fallback_retrievers": self.fallback_retrievers,
            "fallback_ladder": self.fallback_ladder,
            "skipped_retrievers": self.skipped_retrievers,
            "skip_reasons": self.skip_reasons,
            "query_features": self.query_features,
            "reason": self.reason,
            "confidence": self.confidence,
            "retriever_reasons": self.retriever_reasons,
            "priority": self.priority or self.selected_retrievers,
            "query_rewrite": self.query_rewrite,
            "query_profile": self.query_profile,
            "qwen_used": self.qwen_used,
            "strategy": self.strategy,
            "rule_id": self.rule_id,
            "metadata": self.metadata,
        }


class RetrievalPlannerService:
    """
    检索规划服务

    职责：
    - 先走稳定规则规划
    - 在复杂或低置信度场景下尝试 Qwen 细化规划
    - Qwen 失败时回退到规则计划，保证问答链路稳定
    """

    def __init__(self, db: Session | None) -> None:
        self.db = db

    def plan(
        self,
        query: str,
        sub_queries: list[str],
        intent: str,
        chat_type: str,
        mode: str,
        project_id: int | None,
        available_retrievers: list[str],
        query_profile: dict[str, Any] | None = None,
    ) -> RetrievalPlan:
        """
        生成检索计划。

        参数:
            query: 用户原始问题
            sub_queries: 查询拆解后的子查询
            intent: 当前识别出的意图
            chat_type: 对话类型
            mode: 检索模式
            project_id: 项目ID
            available_retrievers: 当前环境可用 Retriever 名称
            query_profile: 查询画像，可为空以保持旧调用兼容

        返回:
            结构化检索计划
        """

        available = self._dedupe_retrievers(available_retrievers)
        query_features = self._build_query_features(query, chat_type, project_id)
        profile = dict(query_profile or {})
        if profile:
            query_features["query_profile"] = profile
        knowledge_scope = str(profile.get("knowledge_scope") or "").strip()
        if not knowledge_scope and intent in {"project_qa", "project_overview", "exact_lookup", "page_location", "graph_reasoning"}:
            knowledge_scope = "project"
        if not knowledge_scope and intent == "industry_knowledge_qa":
            knowledge_scope = "industry"
        if knowledge_scope:
            query_features["knowledge_scope"] = knowledge_scope
        rule_plan = self._build_rule_plan(
            query=query,
            sub_queries=sub_queries,
            intent=intent,
            available_retrievers=available,
            query_features=query_features,
            query_profile=profile,
        )

        if not self._should_use_qwen_planner(rule_plan, intent, query_features):
            logger.info(
                "Retrieval Planner规则命中: intent=%s rule_id=%s selected_retrievers=%s skipped_retrievers=%s confidence=%.2f",
                intent,
                rule_plan.rule_id,
                rule_plan.selected_retrievers,
                rule_plan.skipped_retrievers,
                rule_plan.confidence,
            )
            return rule_plan

        qwen_result = self._plan_with_qwen(
            query=query,
            sub_queries=sub_queries,
            intent=intent,
            chat_type=chat_type,
            mode=mode,
            project_id=project_id,
            available_retrievers=available,
            base_plan=rule_plan,
            query_profile=profile,
        )
        if qwen_result is None:
            fallback_plan = RetrievalPlan(
                selected_retrievers=rule_plan.selected_retrievers,
                fallback_retrievers=rule_plan.fallback_retrievers,
                fallback_ladder=rule_plan.fallback_ladder,
                skipped_retrievers=rule_plan.skipped_retrievers,
                skip_reasons=rule_plan.skip_reasons,
                query_features=rule_plan.query_features,
                reason=rule_plan.reason,
                confidence=rule_plan.confidence,
                qwen_used=True,
                strategy="hybrid_fallback",
                rule_id=rule_plan.rule_id,
                retriever_reasons=rule_plan.retriever_reasons,
                priority=rule_plan.priority,
                query_rewrite=rule_plan.query_rewrite,
                query_profile=rule_plan.query_profile,
                metadata={
                    **rule_plan.metadata,
                    "qwen_result": "invalid_or_failed",
                    "model_route": {
                        "task": "planner",
                        "model_type": "planner",
                        "source": "rules_fallback",
                        "reason": "planner 模型结果无效或调用失败，回退规则计划",
                    },
                },
            )
            logger.info(
                "Retrieval Planner回退规则计划: intent=%s rule_id=%s selected_retrievers=%s confidence=%.2f",
                intent,
                fallback_plan.rule_id,
                fallback_plan.selected_retrievers,
                fallback_plan.confidence,
            )
            return fallback_plan

        logger.info(
            "Retrieval Planner使用Qwen计划: intent=%s rule_id=%s selected_retrievers=%s skipped_retrievers=%s confidence=%.2f",
            intent,
            qwen_result.rule_id,
            qwen_result.selected_retrievers,
            qwen_result.skipped_retrievers,
            qwen_result.confidence,
        )
        return qwen_result

    def _build_query_features(self, query: str, chat_type: str, project_id: int | None) -> dict[str, Any]:
        """
        提取用于 Planner 决策的查询特征。

        参数:
            query: 用户原始问题
            chat_type: 对话类型
            project_id: 项目ID

        返回:
            查询特征字典
        """

        normalized = normalize_query_text(query)
        lowered = normalized.lower()
        terms = extract_query_terms(query, include_chinese_chars=False)
        chinese_count = sum(1 for char in normalized if "\u4e00" <= char <= "\u9fff")
        english_count = sum(1 for char in normalized if "a" <= char.lower() <= "z")

        has_doc_code = bool(DOC_CODE_PATTERN.search(normalized))
        has_exact_token = has_doc_code or bool(EXACT_TOKEN_PATTERN.search(normalized))
        has_page_hint = any(token in lowered for token in PAGE_HINT_PATTERNS) or bool(re.search(r"第\s*\d+\s*页", normalized))
        has_section_hint = any(token in lowered for token in SECTION_HINT_PATTERNS) or bool(re.search(r"\b\d+(?:\.\d+){1,3}\b", normalized))
        has_graph_relation = any(token in lowered for token in GRAPH_HINT_PATTERNS)
        has_summary_intent = any(token in lowered for token in SUMMARY_HINT_PATTERNS)
        has_comparison = any(token in lowered for token in COMPLEX_HINT_PATTERNS)
        has_value_hint = any(token in lowered for token in VALUE_LOOKUP_HINT_PATTERNS)
        has_table_hint = any(token in lowered for token in TABLE_LOOKUP_HINT_PATTERNS)
        has_element_symbol = bool(ELEMENT_SYMBOL_PATTERN.search(normalized))
        # 表格中的 Min/Max、元素符号和合并单元格信息更依赖 pageIndex 的页级文本。
        has_table_value_lookup = has_value_hint and (has_table_hint or has_element_symbol)

        if chinese_count and english_count:
            query_language = "mixed"
        elif chinese_count:
            query_language = "zh"
        elif english_count:
            query_language = "en"
        else:
            query_language = "unknown"

        return {
            "has_page_hint": has_page_hint,
            "has_exact_token": has_exact_token,
            "has_doc_code": has_doc_code,
            "has_section_hint": has_section_hint,
            "has_graph_relation": has_graph_relation,
            "has_summary_intent": has_summary_intent,
            "has_comparison": has_comparison,
            "has_value_hint": has_value_hint,
            "has_table_hint": has_table_hint,
            "has_element_symbol": has_element_symbol,
            "has_table_value_lookup": has_table_value_lookup,
            "query_language": query_language,
            "query_length": len(normalized),
            "chat_type": chat_type,
            "project_scope": "project" if project_id is not None else "base",
            "terms": terms[:12],
        }

    def _build_rule_plan(
        self,
        query: str,
        sub_queries: list[str],
        intent: str,
        available_retrievers: list[str],
        query_features: dict[str, Any],
        query_profile: dict[str, Any],
    ) -> RetrievalPlan:
        """
        根据稳定规则生成第一版检索计划。

        参数:
            query: 用户问题
            sub_queries: 子查询列表
            intent: 意图
            available_retrievers: 当前可用 Retriever
            query_features: 查询特征
            query_profile: 查询画像

        返回:
            规则检索计划
        """

        available_set = set(available_retrievers)
        stages = self._rule_stages(intent, available_set, query_features, query_profile)
        selected_retrievers = self._flatten_non_fallback_retrievers(stages)
        fallback_retrievers = [name for name in [RETRIEVER_KEYWORD] if name in available_set]

        if not selected_retrievers:
            semantic_fallback = self._semantic_primary_fallback(available_set)
            if semantic_fallback:
                stages = [[semantic_fallback]] + ([fallback_retrievers] if fallback_retrievers else [])
                selected_retrievers = [semantic_fallback]

        skipped_retrievers, skip_reasons = self._build_skip_reasons(
            selected_retrievers=selected_retrievers,
            fallback_retrievers=fallback_retrievers,
            available_retrievers=available_retrievers,
            intent=intent,
            query_features=query_features,
        )
        confidence = self._rule_confidence(intent, query_features, selected_retrievers)
        reason = self._rule_reason(intent, query_features, selected_retrievers, sub_queries)
        retriever_reasons = self._rule_retriever_reasons(selected_retrievers, query_features, query_profile)

        return RetrievalPlan(
            selected_retrievers=selected_retrievers,
            fallback_retrievers=fallback_retrievers,
            fallback_ladder=stages,
            skipped_retrievers=skipped_retrievers,
            skip_reasons=skip_reasons,
            query_features=query_features,
            reason=reason,
            confidence=confidence,
            qwen_used=False,
            strategy="rules",
            rule_id=intent,
            retriever_reasons=retriever_reasons,
            priority=selected_retrievers,
            query_rewrite=self._rule_query_rewrite(query, sub_queries, query_profile),
            query_profile=query_profile,
            metadata={
                "query": query,
                "sub_query_count": len(sub_queries),
                "query_profile": query_profile,
                "knowledge_scope": query_profile.get("knowledge_scope") or query_features.get("knowledge_scope"),
                "model_route": {
                    "task": "planner",
                    "source": "rules",
                    "reason": "规则 Planner 置信度足够，未调用模型",
                },
            },
        )

    def _rule_stages(
        self,
        intent: str,
        available_retrievers: set[str],
        query_features: dict[str, Any],
        query_profile: dict[str, Any] | None = None,
    ) -> list[list[str]]:
        """
        构造按阶段执行的 fallback 梯子。

        参数:
            intent: 意图
            available_retrievers: 当前可用 Retriever 集合
            query_features: 查询特征
            query_profile: 查询画像

        返回:
            二维列表，每一层表示一个执行阶段
        """

        def keep(stage: list[str]) -> list[str]:
            return [name for name in stage if name in available_retrievers]

        has_location_signal = bool(
            query_features.get("has_page_hint")
            or query_features.get("has_section_hint")
            or query_features.get("has_doc_code")
        )
        has_table_value_lookup = bool(query_features.get("has_table_value_lookup"))
        has_exact_signal = bool(
            query_features.get("has_exact_token")
            or query_features.get("has_doc_code")
            or has_table_value_lookup
        )
        profile = query_profile or {}
        query_type = self._effective_query_type(intent, profile)
        knowledge_scope = str(profile.get("knowledge_scope") or query_features.get("knowledge_scope") or "")
        need_graph_reasoning = bool(profile.get("need_graph_reasoning") or query_features.get("has_graph_relation"))
        need_page_location = bool(
            profile.get("need_page_location")
            or query_features.get("has_page_hint")
            or query_features.get("has_section_hint")
        )

        stages: list[list[str]]
        if knowledge_scope == "industry":
            stages = [
                keep([RETRIEVER_MILVUS]),
                keep([RETRIEVER_KEYWORD]),
            ]
        elif query_type == "page_location":
            stages = [
                keep([RETRIEVER_PAGE_INDEX, RETRIEVER_RIPGREP]),
                keep([RETRIEVER_KEYWORD]),
            ]
        elif query_type == "exact_lookup":
            exact_stage = [RETRIEVER_RIPGREP, RETRIEVER_MILVUS]
            if need_page_location or profile.get("need_visual_asset"):
                exact_stage.insert(1, RETRIEVER_PAGE_INDEX)
            stages = [
                keep(exact_stage),
                keep([RETRIEVER_KEYWORD]),
            ]
        elif query_type == "process_flow":
            flow_stage = [RETRIEVER_PAGE_INDEX, RETRIEVER_RIPGREP, RETRIEVER_MILVUS]
            if need_graph_reasoning:
                flow_stage.append(RETRIEVER_GRAPHRAG)
            stages = [
                keep(flow_stage),
                keep([RETRIEVER_KEYWORD]),
            ]
        elif query_type == "graph_reasoning":
            stages = [
                keep([RETRIEVER_GRAPHRAG, RETRIEVER_MILVUS, RETRIEVER_RIPGREP]),
                keep([RETRIEVER_KEYWORD]),
            ]
        elif query_type == "project_overview":
            overview_stage = [RETRIEVER_MILVUS, RETRIEVER_PAGE_INDEX]
            if need_graph_reasoning:
                overview_stage.append(RETRIEVER_GRAPHRAG)
            stages = [
                keep(overview_stage),
                keep([RETRIEVER_KEYWORD]),
            ]
        elif query_type == "comparison":
            stages = [
                keep([RETRIEVER_MILVUS, RETRIEVER_RIPGREP, RETRIEVER_GRAPHRAG]),
                keep([RETRIEVER_KEYWORD]),
            ]
        elif has_table_value_lookup:
            stages = [
                keep([RETRIEVER_PAGE_INDEX, RETRIEVER_MILVUS]),
                keep([RETRIEVER_RIPGREP]),
                keep([RETRIEVER_KEYWORD]),
            ]
        elif intent == "project_qa":
            stages = [keep([RETRIEVER_MILVUS])]
            if has_exact_signal:
                stages.append(keep([RETRIEVER_RIPGREP]))
            if has_location_signal:
                stages.append(keep([RETRIEVER_PAGE_INDEX]))
            stages.append(keep([RETRIEVER_KEYWORD]))
        else:
            stages = [keep([RETRIEVER_MILVUS])]
            if has_exact_signal:
                stages.append(keep([RETRIEVER_RIPGREP]))
            stages.append(keep([RETRIEVER_KEYWORD]))

        normalized_stages = [stage for stage in stages if stage]
        if normalized_stages:
            first_stage = normalized_stages[0]
            if RETRIEVER_MILVUS not in first_stage and intent in {"project_qa", "knowledge_qa", "project_overview"}:
                semantic_fallback = self._semantic_primary_fallback(available_retrievers)
                if semantic_fallback and semantic_fallback not in first_stage:
                    normalized_stages.insert(0, [semantic_fallback])
        return self._dedupe_stage_order(normalized_stages)

    def _flatten_non_fallback_retrievers(self, stages: list[list[str]]) -> list[str]:
        """
        把阶段计划拍平成前端可展示的主计划 Retriever 列表。

        参数:
            stages: fallback 阶段列表

        返回:
            去重后的非 keyword 主计划 Retriever 列表
        """

        result: list[str] = []
        for stage in stages:
            for name in stage:
                if name == RETRIEVER_KEYWORD:
                    continue
                if name not in result:
                    result.append(name)
        return result

    def _build_skip_reasons(
        self,
        selected_retrievers: list[str],
        fallback_retrievers: list[str],
        available_retrievers: list[str],
        intent: str,
        query_features: dict[str, Any],
    ) -> tuple[list[str], dict[str, str]]:
        """
        为未进入计划的 Retriever 生成 skip reason。

        参数:
            selected_retrievers: 主计划 Retriever
            fallback_retrievers: fallback Retriever
            available_retrievers: 当前可用 Retriever
            intent: 当前意图
            query_features: 查询特征

        返回:
            skipped_retrievers 列表和 skip_reasons 字典
        """

        skipped_retrievers: list[str] = []
        skip_reasons: dict[str, str] = {}
        planned = set(selected_retrievers) | set(fallback_retrievers)

        for retriever_name in available_retrievers:
            if retriever_name in planned:
                continue
            skipped_retrievers.append(retriever_name)
            skip_reasons[retriever_name] = self._skip_reason_for_retriever(retriever_name, intent, query_features)

        return skipped_retrievers, skip_reasons

    def _skip_reason_for_retriever(
        self,
        retriever_name: str,
        intent: str,
        query_features: dict[str, Any],
    ) -> str:
        """
        生成指定 Retriever 的 skip reason。

        参数:
            retriever_name: Retriever 名称
            intent: 意图
            query_features: 查询特征

        返回:
            可展示的跳过原因
        """

        query_profile = query_features.get("query_profile") or {}
        query_type = self._effective_query_type(intent, query_profile)
        if retriever_name == RETRIEVER_PAGE_INDEX and not (
            query_features.get("has_page_hint")
            or query_features.get("has_section_hint")
            or query_features.get("has_table_value_lookup")
            or query_profile.get("need_page_location")
            or query_profile.get("need_visual_asset")
            or query_type in {"page_location", "exact_lookup", "process_flow", "project_overview"}
        ):
            return "当前问题缺少页码/章节/结构化定位信号，优先跳过page_index"
        if retriever_name == RETRIEVER_RIPGREP and not (
            query_features.get("has_exact_token")
            or query_features.get("has_doc_code")
            or query_features.get("has_table_value_lookup")
            or query_profile.get("need_exact_term")
            or query_type in {"page_location", "exact_lookup", "process_flow", "graph_reasoning", "comparison", "project_overview"}
        ):
            return "当前问题缺少精确词项或文号信号，优先跳过ripgrep"
        if retriever_name == RETRIEVER_GRAPHRAG and not (
            query_profile.get("need_graph_reasoning") or query_type in {"graph_reasoning", "comparison"}
        ):
            return "当前问题不是关系推理类问题，优先跳过graphrag"
        if retriever_name == RETRIEVER_KEYWORD:
            return "keyword仅作为fallback保底检索器"
        if retriever_name == RETRIEVER_MILVUS and intent in {"page_location", "exact_lookup"}:
            return "当前问题更偏精确定位，优先使用page_index/ripgrep"
        return f"根据意图 {intent} 的规则规划未选中该检索器"

    def _rule_confidence(
        self,
        intent: str,
        query_features: dict[str, Any],
        selected_retrievers: list[str],
    ) -> float:
        """
        计算规则 Planner 置信度。

        参数:
            intent: 当前意图
            query_features: 查询特征
            selected_retrievers: 已选 Retriever

        返回:
            0 到 1 之间的规则置信度
        """

        if not selected_retrievers:
            return 0.35
        if query_features.get("has_table_value_lookup"):
            return 0.82
        if intent in {"page_location", "exact_lookup"}:
            return 0.94
        if intent == "graph_reasoning":
            return 0.72
        if intent == "project_overview":
            return 0.74 if query_features.get("has_summary_intent") else 0.68
        if intent == "project_qa":
            if query_features.get("has_exact_token") or query_features.get("has_page_hint"):
                return 0.8
            return 0.7
        if intent == "industry_knowledge_qa":
            return 0.78
        if intent == "knowledge_qa":
            if query_features.get("has_exact_token"):
                return 0.72
            return 0.66
        return 0.65

    def _rule_reason(
        self,
        intent: str,
        query_features: dict[str, Any],
        selected_retrievers: list[str],
        sub_queries: list[str],
    ) -> str:
        """
        生成人类可读的规则命中说明。

        参数:
            intent: 当前意图
            query_features: 查询特征
            selected_retrievers: 主计划 Retriever
            sub_queries: 子查询列表

        返回:
            规则说明
        """

        signals: list[str] = []
        if query_features.get("has_page_hint"):
            signals.append("页码/页定位信号")
        if query_features.get("has_section_hint"):
            signals.append("章节/步骤信号")
        if query_features.get("has_doc_code"):
            signals.append("文号信号")
        if query_features.get("has_exact_token"):
            signals.append("精确词项信号")
        if query_features.get("has_table_value_lookup"):
            signals.append("表格数值查询信号")
        if query_features.get("has_graph_relation"):
            signals.append("关系推理信号")
        if query_features.get("has_summary_intent"):
            signals.append("总结概述信号")
        signal_text = "、".join(signals) if signals else "无强结构化信号"
        return (
            f"intent={intent}，命中信号={signal_text}，"
            f"selected={selected_retrievers}，sub_query_count={len(sub_queries)}"
        )

    def _effective_query_type(self, intent: str, query_profile: dict[str, Any] | None) -> str:
        """优先使用查询画像类型，画像缺失时回退到现有 intent。"""

        query_type = str((query_profile or {}).get("query_type") or "").strip()
        if query_type and query_type != "unknown":
            return query_type
        return intent

    def _rule_retriever_reasons(
        self,
        selected_retrievers: list[str],
        query_features: dict[str, Any],
        query_profile: dict[str, Any],
    ) -> dict[str, str]:
        """为规则选中的 retriever 生成可审计原因。"""

        query_type = self._effective_query_type("", query_profile)
        reason_map = {
            RETRIEVER_PAGE_INDEX: "命中页码、图纸、表格所在页或整页流程定位需求",
            RETRIEVER_RIPGREP: "命中精确词项、设备位号、图号、型号或参数名需求",
            RETRIEVER_MILVUS: "需要语义召回项目描述、同义表达或概念性资料",
            RETRIEVER_GRAPHRAG: "需要上下游关系、物料流向、设备连接或跨段落推理",
            RETRIEVER_KEYWORD: "作为低成本关键词保底检索",
        }
        return {
            name: f"{reason_map.get(name, '规则检索规划选中')}；query_type={query_type or 'unknown'}"
            for name in selected_retrievers
        }

    def _rule_query_rewrite(
        self,
        query: str,
        sub_queries: list[str],
        query_profile: dict[str, Any],
    ) -> list[str]:
        """生成轻量 query rewrite，供 trace 和后续补充检索复用。"""

        candidates: list[str] = [query]
        candidates.extend(sub_queries)
        keywords = query_profile.get("keywords") or []
        entities = query_profile.get("entities") or []
        if entities:
            candidates.append(" ".join(str(item) for item in entities[:6]))
        if keywords:
            candidates.append(" ".join(str(item) for item in keywords[:8]))
        return list(dict.fromkeys(item.strip() for item in candidates if str(item).strip()))[:6]

    def _should_use_qwen_planner(
        self,
        rule_plan: RetrievalPlan,
        intent: str,
        query_features: dict[str, Any],
    ) -> bool:
        """
        判断是否需要尝试 Qwen Planner。

        参数:
            rule_plan: 规则计划
            intent: 当前意图
            query_features: 查询特征

        返回:
            True 表示应尝试 Qwen 细化计划
        """

        if intent in {"graph_reasoning", "project_overview"}:
            return True
        if query_features.get("has_comparison"):
            return True
        if query_features.get("query_length", 0) >= 56:
            return True
        return rule_plan.confidence < 0.75

    def _plan_with_qwen(
        self,
        query: str,
        sub_queries: list[str],
        intent: str,
        chat_type: str,
        mode: str,
        project_id: int | None,
        available_retrievers: list[str],
        base_plan: RetrievalPlan,
        query_profile: dict[str, Any],
    ) -> RetrievalPlan | None:
        """
        使用 Qwen 尝试细化检索计划。

        参数:
            query: 用户问题
            sub_queries: 子查询列表
            intent: 当前意图
            chat_type: 对话类型
            mode: 检索模式
            project_id: 项目ID
            available_retrievers: 当前可用 Retriever
            base_plan: 规则计划
            query_profile: 查询画像

        返回:
            Qwen 规划结果；失败时返回 None
        """

        if self.db is None:
            return None

        prompt = self._build_qwen_planner_prompt(
            query=query,
            sub_queries=sub_queries,
            intent=intent,
            chat_type=chat_type,
            mode=mode,
            project_id=project_id,
            available_retrievers=available_retrievers,
            base_plan=base_plan,
            query_profile=query_profile,
        )
        try:
            llm = LLMService(self.db)
            raw_text = llm.chat(prompt, model_type="planner")
            payload = self._parse_qwen_plan_payload(raw_text)
            selected = self._sanitize_qwen_selected_retrievers(payload, available_retrievers)
            selected = self._ensure_required_retrievers(selected, base_plan.query_features, available_retrievers)
            if not selected:
                return None

            fallback_ladder = self._merge_qwen_selection_into_ladder(selected, base_plan.fallback_ladder)
            selected_retrievers = self._flatten_non_fallback_retrievers(fallback_ladder)
            priority = self._sanitize_retriever_list(payload.get("priority"), available_retrievers) or selected_retrievers
            retriever_reasons = self._sanitize_retriever_reasons(payload.get("retriever_reasons"), available_retrievers)
            query_rewrite = self._sanitize_query_rewrite(payload.get("query_rewrite"))
            skipped_retrievers, skip_reasons = self._build_skip_reasons(
                selected_retrievers=selected_retrievers,
                fallback_retrievers=base_plan.fallback_retrievers,
                available_retrievers=available_retrievers,
                intent=intent,
                query_features=base_plan.query_features,
            )
            return RetrievalPlan(
                selected_retrievers=selected_retrievers,
                fallback_retrievers=base_plan.fallback_retrievers,
                fallback_ladder=fallback_ladder,
                skipped_retrievers=skipped_retrievers,
                skip_reasons=skip_reasons,
                query_features=base_plan.query_features,
                reason=str(payload.get("reason") or base_plan.reason),
                confidence=self._clamp_confidence(payload.get("confidence"), default=base_plan.confidence),
                qwen_used=True,
                strategy="qwen",
                rule_id=base_plan.rule_id,
                retriever_reasons=retriever_reasons or base_plan.retriever_reasons,
                priority=priority,
                query_rewrite=query_rewrite or base_plan.query_rewrite,
                query_profile=query_profile,
                metadata={
                    **base_plan.metadata,
                    "qwen_payload": payload,
                    "model_route": llm.model_route("planner", "规则 Planner 需要模型细化，使用 planner 模型"),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Retrieval Planner Qwen规划失败，回退规则计划: intent=%s error=%s", intent, exc)
            return None

    def _build_qwen_planner_prompt(
        self,
        query: str,
        sub_queries: list[str],
        intent: str,
        chat_type: str,
        mode: str,
        project_id: int | None,
        available_retrievers: list[str],
        base_plan: RetrievalPlan,
        query_profile: dict[str, Any],
    ) -> list[dict[str, str]]:
        """
        构造 Qwen Planner 提示词。

        参数:
            query: 用户问题
            sub_queries: 子查询
            intent: 当前意图
            chat_type: 对话类型
            mode: 检索模式
            project_id: 项目ID
            available_retrievers: 当前可用 Retriever
            base_plan: 规则计划
            query_profile: 查询画像

        返回:
            可直接传给 LLMService.chat 的消息列表
        """

        user_prompt = json.dumps(
            {
                "query": query,
                "sub_queries": sub_queries,
                "intent": intent,
                "chat_type": chat_type,
                "mode": mode,
                "project_id": project_id,
                "available_retrievers": available_retrievers,
                "query_profile": query_profile,
                "knowledge_scope": query_profile.get("knowledge_scope"),
                "query_features": base_plan.query_features,
                "rule_plan": base_plan.to_dict(),
            },
            ensure_ascii=False,
        )
        return [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

    def _parse_qwen_plan_payload(self, raw_text: str) -> dict[str, Any]:
        """
        解析 Qwen Planner 输出的 JSON。

        参数:
            raw_text: 模型原始输出

        返回:
            JSON 字典
        """

        stripped = raw_text.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if "\n" in stripped:
                stripped = stripped.split("\n", 1)[1]
            stripped = stripped.rsplit("```", 1)[0].strip()
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError("qwen planner payload must be a json object")
        return payload

    def _sanitize_qwen_selected_retrievers(
        self,
        payload: dict[str, Any],
        available_retrievers: list[str],
    ) -> list[str]:
        """
        清洗 Qwen 返回的 Retriever 名称。

        参数:
            payload: Qwen JSON 结果
            available_retrievers: 当前可用 Retriever

        返回:
            去重后的合法 Retriever 列表
        """

        raw_selected = payload.get("selected_retrievers")
        if not isinstance(raw_selected, list):
            raw_selected = payload.get("priority")
        return self._sanitize_retriever_list(raw_selected, available_retrievers)

    def _sanitize_retriever_list(self, raw_value: Any, available_retrievers: list[str]) -> list[str]:
        """过滤未知、未启用和重复 retriever。"""

        if not isinstance(raw_value, list):
            return []

        available_set = set(available_retrievers)
        selected: list[str] = []
        for item in raw_value:
            name = str(item).strip().lower()
            if name not in available_set:
                continue
            if name not in ALL_RETRIEVERS:
                continue
            if name not in selected:
                selected.append(name)
        return selected

    def _sanitize_retriever_reasons(self, raw_value: Any, available_retrievers: list[str]) -> dict[str, str]:
        """清洗模型返回的 retriever_reasons。"""

        if not isinstance(raw_value, dict):
            return {}
        allowed = set(available_retrievers) & set(ALL_RETRIEVERS)
        reasons: dict[str, str] = {}
        for key, value in raw_value.items():
            name = str(key).strip().lower()
            if name not in allowed:
                continue
            reason = str(value or "").strip()
            if reason:
                reasons[name] = reason[:240]
        return reasons

    def _sanitize_query_rewrite(self, raw_value: Any) -> list[str]:
        """清洗模型返回的 query_rewrite。"""

        if not isinstance(raw_value, list):
            return []
        rewrites: list[str] = []
        for item in raw_value:
            text = str(item or "").strip()
            if not text or text in rewrites:
                continue
            rewrites.append(text[:240])
        return rewrites[:6]

    def _ensure_required_retrievers(
        self,
        selected: list[str],
        query_features: dict[str, Any],
        available_retrievers: list[str],
    ) -> list[str]:
        """
        为强业务信号补齐必须执行的 Retriever。

        表格数值查询需要 pageIndex 的页级文本兜底，避免 Qwen 只选向量/精确检索后漏掉合并单元格展开内容。
        """

        available_set = set(available_retrievers)
        result = [name for name in selected if name in available_set]
        query_profile = query_features.get("query_profile") or {}
        query_type = self._effective_query_type("", query_profile)
        if query_features.get("has_table_value_lookup") and RETRIEVER_PAGE_INDEX in available_set:
            if RETRIEVER_PAGE_INDEX not in result:
                result.insert(0, RETRIEVER_PAGE_INDEX)
            elif result[0] != RETRIEVER_PAGE_INDEX:
                result = [RETRIEVER_PAGE_INDEX] + [name for name in result if name != RETRIEVER_PAGE_INDEX]
        required_by_type = {
            "page_location": [RETRIEVER_PAGE_INDEX, RETRIEVER_RIPGREP],
            "process_flow": [RETRIEVER_PAGE_INDEX, RETRIEVER_RIPGREP, RETRIEVER_MILVUS],
            "graph_reasoning": [RETRIEVER_GRAPHRAG, RETRIEVER_MILVUS, RETRIEVER_RIPGREP],
            "comparison": [RETRIEVER_MILVUS, RETRIEVER_RIPGREP, RETRIEVER_GRAPHRAG],
            "project_overview": [RETRIEVER_MILVUS, RETRIEVER_PAGE_INDEX],
        }
        if query_type == "exact_lookup":
            required = [RETRIEVER_RIPGREP, RETRIEVER_MILVUS]
            if query_profile.get("need_page_location") or query_profile.get("need_visual_asset"):
                required.append(RETRIEVER_PAGE_INDEX)
        else:
            required = required_by_type.get(query_type, [])
        for name in reversed(required):
            if name in available_set and name not in result:
                result.insert(0, name)
        return result

    def _merge_qwen_selection_into_ladder(
        self,
        qwen_selected: list[str],
        base_ladder: list[list[str]],
    ) -> list[list[str]]:
        """
        将 Qwen 选择结果合并到规则 fallback 梯子中。

        参数:
            qwen_selected: Qwen 选择的 Retriever
            base_ladder: 规则 fallback 梯子

        返回:
            新的阶段执行顺序
        """

        if not qwen_selected:
            return base_ladder

        remaining_stages: list[list[str]] = []
        qwen_set = set(qwen_selected)
        for stage in base_ladder:
            remaining = [name for name in stage if name not in qwen_set]
            if remaining:
                remaining_stages.append(remaining)
        return self._dedupe_stage_order([qwen_selected] + remaining_stages)

    def _semantic_primary_fallback(self, available_retrievers: set[str]) -> str | None:
        """
        在 Milvus 不可用或规则阶段被过滤为空时，选择一个保底主检索器。

        参数:
            available_retrievers: 当前可用 Retriever

        返回:
            可作为首阶段的 Retriever 名称
        """

        for candidate in (RETRIEVER_PAGE_INDEX, RETRIEVER_RIPGREP, RETRIEVER_GRAPHRAG, RETRIEVER_KEYWORD):
            if candidate in available_retrievers:
                return candidate
        return None

    def _dedupe_stage_order(self, stages: list[list[str]]) -> list[list[str]]:
        """
        对阶段列表做去重，避免同一 Retriever 在多个阶段重复执行。

        参数:
            stages: 原始阶段列表

        返回:
            规范化后的阶段列表
        """

        seen: set[str] = set()
        normalized: list[list[str]] = []
        for stage in stages:
            unique_stage: list[str] = []
            for name in stage:
                if name in seen:
                    continue
                unique_stage.append(name)
                seen.add(name)
            if unique_stage:
                normalized.append(unique_stage)
        return normalized

    def _dedupe_retrievers(self, retrievers: list[str]) -> list[str]:
        """
        去重并保持 Retriever 顺序稳定。

        参数:
            retrievers: 原始 Retriever 列表

        返回:
            去重后的 Retriever 列表
        """

        result: list[str] = []
        for name in retrievers:
            normalized = str(name).strip().lower()
            if normalized not in ALL_RETRIEVERS:
                continue
            if not normalized or normalized in result:
                continue
            result.append(normalized)
        return result

    def _clamp_confidence(self, value: Any, default: float) -> float:
        """
        把任意置信度值规整到 0 到 1 之间。

        参数:
            value: 原始置信度
            default: 无法解析时的默认值

        返回:
            规范化后的置信度
        """

        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return default
        return max(0.0, min(1.0, confidence))
