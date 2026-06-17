"""
Qwen Orchestration Service

负责：
1. 为 LangGraph 提供意图识别、查询拆解和证据判断能力
2. 保持 Qwen 子能力调用入口独立，避免和回答生成耦合
3. 在专用模型未配置时提供确定性规则降级
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.retrieval.query_utils import (
    boilerplate_multiplier,
    expand_search_phrases,
    extract_query_terms,
    is_project_overview_query,
    normalize_query_text,
)
from app.retrieval.schemas import Evidence


class QwenOrchestrationService:
    """
    Qwen 编排服务

    职责：
    - 判断用户意图
    - 拆解检索子查询
    - 判断证据是否足够回答
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def detect_intent(self, question: str, chat_type: str, mode: str) -> str:
        """
        识别问题意图。

        参数:
            question: 用户问题。
            chat_type: 问答类型。
            mode: 问答模式。

        返回:
            意图编码。
        """

        lowered = question.lower()
        if is_project_overview_query(question):
            return "project_overview"
        if any(token in question for token in ("关系", "关联", "影响", "依赖", "连接")):
            return "graph_reasoning"
        if any(token in lowered for token in ("drawing", "dwg", "page")) or any(token in question for token in ("图纸", "页", "第")):
            return "page_location"
        if any(token in question for token in ("编号", "位号", "标准", "条款")):
            return "exact_lookup"
        if re.search(r"\b[A-Z]{1,8}[-_/]\d{2,}[A-Z0-9_-]*\b", question, re.IGNORECASE):
            return "exact_lookup"
        if chat_type == "project_chat" or mode in {"project_only", "hybrid"}:
            return "project_qa"
        return "knowledge_qa"

    def decompose_query(self, question: str, intent: str) -> list[str]:
        """
        拆解查询。

        参数:
            question: 用户问题。
            intent: 已识别意图。

        返回:
            子查询列表。
        """

        expanded = expand_search_phrases(question)
        terms = extract_query_terms(question)
        sub_queries = [question]
        if intent in {"project_overview", "exact_lookup", "page_location", "graph_reasoning"}:
            sub_queries.extend(expanded)
            sub_queries.extend(terms)
        return list(dict.fromkeys(item.strip() for item in sub_queries if item.strip()))[:6]

    def judge_evidence(self, question: str, evidences: list[Evidence]) -> dict:
        """
        判断证据是否足够回答。

        参数:
            question: 用户问题。
            evidences: 重排后的证据列表。

        返回:
            证据判断结果。
        """

        if not evidences:
            return {"enough": False, "reason": "未召回任何证据"}
        valuable_evidences = [item for item in evidences if boilerplate_multiplier(item.content) >= 0.45]
        top_score = max(item.score for item in evidences)
        if top_score <= 0 or not valuable_evidences:
            return {"enough": False, "reason": "召回证据相关性分数过低"}
        if is_project_overview_query(question):
            coverage = self._project_overview_coverage(valuable_evidences)
            if coverage["coverage_count"] < 2:
                return {"enough": False, "reason": f"项目介绍字段覆盖不足：{coverage}"}
            return {"enough": True, "reason": f"项目介绍字段覆盖充分：{coverage}"}
        return {"enough": True, "reason": f"已召回 {len(valuable_evidences)} 条有效候选证据"}

    def _project_overview_coverage(self, evidences: list[Evidence]) -> dict:
        """
        统计项目介绍类问题的证据字段覆盖。

        参数:
            evidences: 已过滤低价值页面后的候选证据。

        返回:
            覆盖字段统计。
        """

        text = normalize_query_text("\n".join(item.content for item in evidences)).lower()
        fields = {
            "project_name": any(token in text for token in ("project", "black mass", "battery")),
            "capacity": bool(re.search(r"\b\d+\s*tpa\b|\b\d+x\d+\s*tpa\b|capacity", text)),
            "design_basis": "design basis" in text or "plant capacity" in text,
            "product": "product" in text or "byproduct" in text,
            "client": "client" in text or "customer" in text,
        }
        matched = [name for name, passed in fields.items() if passed]
        return {"coverage_count": len(matched), "matched_fields": matched}
