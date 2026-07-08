"""Question understanding services.

负责：
1. 在旧 intent / query_profile 之外生成多维问题理解结构
2. 对行业与项目常见术语做轻量归一化和检索改写
3. 仅产出辅助画像，不改变当前 RAG 主流程行为
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from app.retrieval.query_utils import normalize_query_text
from app.services.industry_domain_rules import detect_industry_domains


class AnswerPolicy(str, Enum):
    """回答策略枚举。"""

    STRICT_KB = "STRICT_KB"
    KB_FIRST = "KB_FIRST"
    GENERAL_ALLOWED = "GENERAL_ALLOWED"
    ASK_GENERAL_CONFIRM = "ASK_GENERAL_CONFIRM"


class KnowledgeScope(str, Enum):
    """知识范围枚举。"""

    PROJECT = "project"
    BASE = "base"
    INDUSTRY = "industry"


class TaskType(str, Enum):
    """任务类型枚举。"""

    PROJECT_OVERVIEW = "project_overview"
    PROCESS_FLOW = "process_flow"
    EQUIPMENT_LOOKUP = "equipment_lookup"
    PARAMETER_LOOKUP = "parameter_lookup"
    DOCUMENT_LOCATION = "document_location"
    COMPARISON = "comparison"
    DEFINITION = "definition"
    SUMMARY = "summary"
    TROUBLESHOOTING = "troubleshooting"
    CALCULATION = "calculation"
    CASUAL = "casual"
    UNKNOWN = "unknown"


class ObjectType(str, Enum):
    """问题对象类型枚举。"""

    PROJECT = "project"
    PROCESS = "process"
    MATERIAL_FLOW = "material_flow"
    EQUIPMENT = "equipment"
    PARAMETER = "parameter"
    DOCUMENT = "document"
    CONCEPT = "concept"
    UNKNOWN = "unknown"


class AnswerShape(str, Enum):
    """期望回答形态枚举。"""

    PROJECT_SUMMARY = "project_summary"
    PROCESS_STEPS = "process_steps"
    COMPARISON_TABLE = "comparison_table"
    PARAMETER_TABLE = "parameter_table"
    SOURCE_LOCATION = "source_location"
    DIRECT_ANSWER = "direct_answer"
    LIMITED_ANSWER = "limited_answer"
    REFUSAL = "refusal"


@dataclass(frozen=True)
class RetrievalNeeds:
    """检索需求画像，用于后续 Policy/Planner 逐步接入。"""

    semantic_retrieval: bool = False
    keyword_retrieval: bool = False
    page_level_retrieval: bool = False
    graph_retrieval: bool = False
    exact_text_search: bool = False
    visual_evidence: bool = False

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(frozen=True)
class QuestionUnderstanding:
    """多维问题理解结果。"""

    chat_type: str
    project_id: int | None
    user_id: int | None
    original_question: str
    normalized_question: str
    answer_policy: str
    knowledge_scope: str
    task_type: str
    object_type: str
    entities: list[str] = field(default_factory=list)
    domain_terms: list[str] = field(default_factory=list)
    answer_shape: str = AnswerShape.DIRECT_ANSWER.value
    retrieval_needs: RetrievalNeeds = field(default_factory=RetrievalNeeds)
    query_rewrites: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["retrieval_needs"] = self.retrieval_needs.to_dict()
        return result


class QueryNormalizerService:
    """查询归一化与术语改写服务。"""

    _TERM_EXPANSIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("黑粉", ("Black Mass", "Black powder")),
        ("进料", ("Feeding", "Raw Material Feeding")),
        ("原料进料", ("Raw Material & Chemical Feeding",)),
        ("pfd", ("Process Flow Diagram",)),
        ("p&id", ("Piping & Instrumentation Diagram",)),
        ("p＆id", ("Piping & Instrumentation Diagram",)),
    )

    def normalize_question(self, question: str) -> str:
        """执行基础文本归一化。"""

        return normalize_query_text(question or "")

    def build_query_rewrites(self, question: str) -> list[str]:
        """根据行业术语生成检索改写，保持顺序去重。"""

        normalized = self.normalize_question(question)
        lowered = normalized.lower()
        rewrites: list[str] = [normalized]

        # 黑粉进料流程在项目资料中常以英文小节名出现，需要显式补全英文检索短语。
        if all(token in normalized for token in ("黑粉", "进料", "流程")):
            rewrites.extend(
                [
                    "黑粉 进料 流程",
                    "Black Mass Feeding",
                    "Raw Material Feeding",
                    "Raw Material & Chemical Feeding",
                ]
            )

        for keyword, expansions in self._TERM_EXPANSIONS:
            if keyword in lowered or keyword in normalized:
                rewrites.extend(expansions)

        if "black mass" in lowered and "feeding" in lowered:
            rewrites.append("Black Mass Feeding")
        if "raw material feeding" in lowered:
            rewrites.append("Raw Material Feeding")
        if "raw material & chemical feeding" in lowered:
            rewrites.append("Raw Material & Chemical Feeding")

        return self._dedupe(item for item in rewrites if item.strip())

    def extract_domain_terms(self, question: str) -> list[str]:
        """抽取命中的中文术语及英文等价表达。"""

        normalized = self.normalize_question(question)
        lowered = normalized.lower()
        terms: list[str] = []
        for keyword, expansions in self._TERM_EXPANSIONS:
            if keyword in lowered or keyword in normalized:
                terms.append(keyword)
                terms.extend(expansions)
        return self._dedupe(terms)

    def _dedupe(self, items: Any) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            value = str(item or "").strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(value)
        return result


class QuestionUnderstandingService:
    """规则版问题理解服务，本阶段不依赖 LLM。"""

    _PROJECT_REFERENCE_HINTS = (
        "本项目",
        "这个项目",
        "该项目",
        "图中",
        "资料里",
        "根据文件",
        "根据知识库",
        "这张图",
        "项目",
    )
    _PROCESS_HINTS = (
        "流程",
        "全流程",
        "流向",
        "物料流向",
        "工艺路线",
        "上下游",
        "从哪里到哪里",
        "连接",
        "process flow",
        "flow",
        "feeding",
    )
    _PROCESS_OBJECT_HINTS = (
        "蒸发",
        "结晶",
        "浓缩",
        "干燥",
        "过滤",
        "反应",
        "浸出",
        "萃取",
        "除杂",
        "洗涤",
        "沉淀",
        "分离",
        "回收",
        "冷却",
        "蒸馏",
    )
    _FEEDING_HINTS = ("进料", "原料进料", "feeding", "raw material")
    _PROJECT_OVERVIEW_HINTS = ("项目概况", "项目简介", "建设内容", "处理规模", "项目定位", "overview")
    _COMPARISON_HINTS = ("区别", "对比", "比较", "差异", "哪个更好", "compare", "comparison", "difference")
    _PARAMETER_HINTS = (
        "参数",
        "数值",
        "温度",
        "流量",
        "浓度",
        "含量",
        "最大",
        "最小",
        "设计值",
        "进料量",
        "处理量",
        "投加量",
        "是多少",
        "多少",
        "calculation",
    )
    _DOCUMENT_HINTS = (
        "哪页",
        "哪一页",
        "第几页",
        "几页",
        "页码",
        "图号",
        "哪张图",
        "哪张图纸",
        "哪个图纸",
        "出处",
        "来源",
        "文件名",
        "图纸定位",
        "drawing",
        "page",
    )
    _EQUIPMENT_HINTS = ("设备", "离心机", "压滤机", "过滤器", "mvr", "搅拌釜", "位号")
    _TROUBLESHOOTING_HINTS = ("故障", "异常", "原因", "为什么", "怎么处理", "排查", "troubleshooting")
    _CALCULATION_HINTS = ("计算", "公式", "等于", "=", "+", "-", "*", "/", "×")
    _DEFINITION_HINTS = ("是什么", "什么意思", "定义", "概念", "原理", "how to read", "what is")
    _SUMMARY_HINTS = ("总结", "概述", "归纳", "summary")
    _CASUAL_HINTS = ("你好", "您好", "hi", "hello", "你是谁", "谢谢")
    _VISUAL_HINTS = ("图", "图纸", "这张图", "图中", "p&id", "p＆id", "pid", "drawing")

    _TASK_TO_SHAPE: dict[str, str] = {
        TaskType.PROJECT_OVERVIEW.value: AnswerShape.PROJECT_SUMMARY.value,
        TaskType.PROCESS_FLOW.value: AnswerShape.PROCESS_STEPS.value,
        TaskType.COMPARISON.value: AnswerShape.COMPARISON_TABLE.value,
        TaskType.PARAMETER_LOOKUP.value: AnswerShape.PARAMETER_TABLE.value,
        TaskType.DOCUMENT_LOCATION.value: AnswerShape.SOURCE_LOCATION.value,
        TaskType.DEFINITION.value: AnswerShape.DIRECT_ANSWER.value,
        TaskType.SUMMARY.value: AnswerShape.DIRECT_ANSWER.value,
        TaskType.TROUBLESHOOTING.value: AnswerShape.DIRECT_ANSWER.value,
        TaskType.CALCULATION.value: AnswerShape.DIRECT_ANSWER.value,
        TaskType.CASUAL.value: AnswerShape.DIRECT_ANSWER.value,
        TaskType.EQUIPMENT_LOOKUP.value: AnswerShape.DIRECT_ANSWER.value,
    }

    def __init__(self, normalizer: QueryNormalizerService | None = None) -> None:
        self.normalizer = normalizer or QueryNormalizerService()

    def understand(
        self,
        question: str,
        *,
        chat_type: str,
        project_id: int | None,
        user_id: int | None,
        intent: str | None = None,
        query_profile: dict[str, Any] | None = None,
    ) -> QuestionUnderstanding:
        """生成多维问题理解结果。"""

        normalized = self.normalizer.normalize_question(question)
        lowered = normalized.lower()
        query_rewrites = self.normalizer.build_query_rewrites(question)
        domain_terms = self.normalizer.extract_domain_terms(question)
        industry_domains = detect_industry_domains(question)
        task_type, task_reason, confidence = self._infer_task_type(lowered, normalized, intent)
        object_type = self._infer_object_type(lowered, normalized, task_type)
        answer_shape = self._answer_shape_for_task(task_type)
        knowledge_scope = self._infer_knowledge_scope(chat_type, project_id, industry_domains, normalized)
        answer_policy = self._infer_answer_policy(chat_type, task_type)
        retrieval_needs = self._infer_retrieval_needs(lowered, task_type)
        entities = self._extract_entities(normalized, query_profile, domain_terms)
        reason = self._build_reason(task_reason, knowledge_scope, industry_domains)

        return QuestionUnderstanding(
            chat_type=chat_type,
            project_id=project_id,
            user_id=user_id,
            original_question=question,
            normalized_question=normalized,
            answer_policy=answer_policy,
            knowledge_scope=knowledge_scope,
            task_type=task_type,
            object_type=object_type,
            entities=entities,
            domain_terms=domain_terms,
            answer_shape=answer_shape,
            retrieval_needs=retrieval_needs,
            query_rewrites=query_rewrites,
            confidence=confidence,
            reason=reason,
        )

    def _infer_task_type(self, lowered: str, normalized: str, intent: str | None) -> tuple[str, str, float]:
        if self._contains_any(lowered, self._CASUAL_HINTS) and len(normalized) <= 12:
            return TaskType.CASUAL.value, "命中问候/闲聊规则", 0.93
        if self._contains_any(lowered, self._COMPARISON_HINTS):
            return TaskType.COMPARISON.value, "命中对比类信号", 0.86
        if self._contains_any(lowered, self._DOCUMENT_HINTS):
            return TaskType.DOCUMENT_LOCATION.value, "命中文件/页码/图纸定位信号", 0.84
        if self._is_process_flow_query(lowered, normalized):
            return TaskType.PROCESS_FLOW.value, "命中流程/进料/物料流向信号", 0.9
        if self._contains_any(lowered, self._PARAMETER_HINTS):
            return TaskType.PARAMETER_LOOKUP.value, "命中参数/数值类信号", 0.78
        if self._contains_any(lowered, self._EQUIPMENT_HINTS):
            return TaskType.EQUIPMENT_LOOKUP.value, "命中设备类信号", 0.76
        if self._contains_any(lowered, self._TROUBLESHOOTING_HINTS):
            return TaskType.TROUBLESHOOTING.value, "命中故障/原因分析信号", 0.72
        if self._looks_like_calculation(normalized):
            return TaskType.CALCULATION.value, "命中计算表达式信号", 0.78
        if self._contains_any(lowered, self._DEFINITION_HINTS):
            return TaskType.DEFINITION.value, "命中概念/定义/原理信号", 0.78
        if self._contains_any(lowered, self._PROJECT_OVERVIEW_HINTS) or intent == TaskType.PROJECT_OVERVIEW.value:
            return TaskType.PROJECT_OVERVIEW.value, "命中项目概况类信号", 0.82
        if self._contains_any(lowered, self._SUMMARY_HINTS):
            return TaskType.SUMMARY.value, "命中总结类信号", 0.7
        return TaskType.UNKNOWN.value, "未命中高置信规则", 0.45

    def _is_process_flow_query(self, lowered: str, normalized: str) -> bool:
        has_process = self._contains_any(lowered, self._PROCESS_HINTS)
        has_feeding = self._contains_any(lowered, self._FEEDING_HINTS)
        has_process_object = any(token in normalized for token in self._PROCESS_OBJECT_HINTS)
        has_material_flow = any(token in normalized for token in ("物料流向", "流向", "上下游"))
        has_project_context = any(token in normalized for token in self._PROJECT_REFERENCE_HINTS)
        if has_material_flow:
            return True
        if has_process and (has_feeding or "黑粉" in normalized or has_project_context or has_process_object):
            return True
        return bool("流程" in normalized and ("介绍" in normalized or has_process_object))

    def _infer_object_type(self, lowered: str, normalized: str, task_type: str) -> str:
        if task_type == TaskType.PROJECT_OVERVIEW.value:
            return ObjectType.PROJECT.value
        if task_type == TaskType.PROCESS_FLOW.value:
            if any(token in normalized for token in ("物料", "流向", "进料", "黑粉")) or "feeding" in lowered:
                return ObjectType.MATERIAL_FLOW.value
            return ObjectType.PROCESS.value
        if task_type == TaskType.EQUIPMENT_LOOKUP.value:
            return ObjectType.EQUIPMENT.value
        if task_type in {TaskType.PARAMETER_LOOKUP.value, TaskType.CALCULATION.value}:
            return ObjectType.PARAMETER.value
        if task_type == TaskType.DOCUMENT_LOCATION.value:
            return ObjectType.DOCUMENT.value
        if task_type == TaskType.DEFINITION.value:
            return ObjectType.CONCEPT.value
        return ObjectType.UNKNOWN.value

    def _infer_knowledge_scope(
        self,
        chat_type: str,
        project_id: int | None,
        industry_domains: list[str],
        normalized: str,
    ) -> str:
        if chat_type == "project_chat" or project_id is not None or any(token in normalized for token in self._PROJECT_REFERENCE_HINTS):
            return KnowledgeScope.PROJECT.value
        if industry_domains:
            return KnowledgeScope.INDUSTRY.value
        return KnowledgeScope.BASE.value

    def _infer_answer_policy(self, chat_type: str, task_type: str) -> str:
        if chat_type == "project_chat":
            return AnswerPolicy.STRICT_KB.value
        if task_type == TaskType.CASUAL.value:
            return AnswerPolicy.GENERAL_ALLOWED.value
        return AnswerPolicy.KB_FIRST.value

    def _infer_retrieval_needs(self, lowered: str, task_type: str) -> RetrievalNeeds:
        visual_evidence = self._contains_any(lowered, self._VISUAL_HINTS)
        if task_type == TaskType.CASUAL.value:
            return RetrievalNeeds()
        if task_type == TaskType.PROCESS_FLOW.value:
            return RetrievalNeeds(
                semantic_retrieval=True,
                keyword_retrieval=True,
                page_level_retrieval=True,
                graph_retrieval=True,
                exact_text_search=False,
                visual_evidence=True,
            )
        if task_type == TaskType.DOCUMENT_LOCATION.value:
            return RetrievalNeeds(
                semantic_retrieval=True,
                keyword_retrieval=True,
                page_level_retrieval=True,
                graph_retrieval=False,
                exact_text_search=True,
                visual_evidence=visual_evidence,
            )
        if task_type in {TaskType.PARAMETER_LOOKUP.value, TaskType.EQUIPMENT_LOOKUP.value}:
            return RetrievalNeeds(
                semantic_retrieval=True,
                keyword_retrieval=True,
                page_level_retrieval=False,
                graph_retrieval=False,
                exact_text_search=True,
                visual_evidence=visual_evidence,
            )
        return RetrievalNeeds(
            semantic_retrieval=True,
            keyword_retrieval=True,
            page_level_retrieval=False,
            graph_retrieval=False,
            exact_text_search=False,
            visual_evidence=visual_evidence,
        )

    def _answer_shape_for_task(self, task_type: str) -> str:
        return self._TASK_TO_SHAPE.get(task_type, AnswerShape.LIMITED_ANSWER.value)

    def _extract_entities(
        self,
        normalized: str,
        query_profile: dict[str, Any] | None,
        domain_terms: list[str],
    ) -> list[str]:
        entities: list[str] = []
        entities.extend((query_profile or {}).get("entities") or [])
        entities.extend(domain_terms)
        entities.extend(re.findall(r"\b[A-Z][A-Za-z0-9&./#_-]{1,}\b", normalized))
        for token in ("黑粉", "进料", "原料进料", "PFD", "P&ID"):
            if token.lower() in normalized.lower():
                entities.append(token)
        return self._dedupe(entities)[:20]

    def _build_reason(self, task_reason: str, knowledge_scope: str, industry_domains: list[str]) -> str:
        domain_text = f"，行业领域={','.join(industry_domains)}" if industry_domains else ""
        return f"{task_reason}；knowledge_scope={knowledge_scope}{domain_text}"

    def _contains_any(self, text: str, patterns: tuple[str, ...]) -> bool:
        return any(pattern.lower() in text for pattern in patterns)

    def _looks_like_calculation(self, normalized: str) -> bool:
        if re.fullmatch(r"\s*\d+(?:\.\d+)?\s*[\+\-\*/x×]\s*\d+(?:\.\d+)?\s*(?:=|等于|是多少|几)?\s*", normalized):
            return True
        return bool(re.search(r"\d+\s*[\+\-\*/x×]\s*\d+", normalized) and "公式" in normalized)

    def _dedupe(self, items: list[str] | tuple[str, ...]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            value = str(item or "").strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(value)
        return result
