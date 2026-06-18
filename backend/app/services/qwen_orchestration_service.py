"""
Qwen Orchestration Service

负责：
1. 为 LangGraph 提供意图识别、查询拆解和证据判断能力
2. 保持 Qwen 子能力调用入口独立，避免和回答生成耦合
3. 在专用模型未配置时提供确定性规则降级
"""

from __future__ import annotations

import ast
import json
import logging
import operator
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.retrieval.query_utils import (
    boilerplate_multiplier,
    expand_search_phrases,
    extract_query_terms,
    is_project_overview_query,
    normalize_query_text,
)
from app.retrieval.schemas import Evidence
from app.services.industry_domain_rules import detect_industry_domains, is_industry_domain_question
from app.services.llm_service import LLMService
from app.services.rag_prompt_templates import EVIDENCE_JUDGE_SYSTEM_PROMPT, KNOWN_RETRIEVERS

logger = logging.getLogger(__name__)

RAG_INTENTS = {
    "project_qa",
    "industry_knowledge_qa",
    "knowledge_qa",
    "project_overview",
    "exact_lookup",
    "page_location",
    "graph_reasoning",
}
DIRECT_INTENTS = {"greeting", "pure_general_qa", "general_qa"}
ROUTE_ONLY_INTENTS = {"rag_required"}
ALLOWED_INTENTS = RAG_INTENTS | DIRECT_INTENTS | ROUTE_ONLY_INTENTS
TABLE_HINTS = ("|", "\t", "表格", "table", "min", "max", "wt%", "含量", "percentage")
GREETING_KEYWORDS = (
    "你好",
    "您好",
    "hello",
    "hi",
    "在吗",
    "你是谁",
    "你能做什么",
    "可以做什么",
    "介绍一下你自己",
    "你是什么系统",
)
CAPABILITY_KEYWORDS = ("你能做什么", "可以做什么", "有什么功能", "能帮我做什么")
RAG_REQUIRED_KEYWORDS = (
    "项目",
    "文件",
    "资料",
    "图纸",
    "图中",
    "图里",
    "这张图",
    "该图",
    "p&id",
    "pid",
    "pfd",
    "dwg",
    "页码",
    "图号",
    "位号",
    "设备位号",
    "参数值",
    "根据知识库",
    "知识库",
    "来源",
    "出处",
    "证据",
    "该文件",
    "这个项目",
    "资料里",
    "工艺包",
    "设备清单",
    "财务模型",
    "实验报告",
    "黑粉回收",
    "bmi",
)
PURE_GENERAL_QA_HINTS = (
    "太阳从哪边升起",
    "太阳从哪里升起",
    "水的沸点",
    "牛顿",
    "欧姆定律",
    "三角形面积",
    "面积公式",
    "数学",
    "物理",
    "睡眠",
    "喝水",
    "日常生活",
)
PROJECT_REFERENCE_KEYWORDS = (
    "这个项目",
    "该项目",
    "本项目",
    "项目中",
    "项目的",
    "图中",
    "图里",
    "这张图",
    "该图",
    "资料里",
    "根据文件",
    "根据资料",
    "根据知识库",
    "文件名",
    "图号",
    "页码",
    "哪页",
    "哪一页",
    "出处",
    "来源",
    "参数值",
)
PROJECT_CHAT_HINTS = (
    "流程",
    "参数",
    "设备",
    "位号",
    "图",
    "资料",
    "工艺",
    "物料",
    "流向",
)
PROJECT_NAME_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_-]{1,20}\s*项目\b", re.IGNORECASE)
DOC_OR_TAG_PATTERN = re.compile(r"\b[A-Z]{1,8}[A-Z0-9]*[-_/]\d{2,}[A-Z0-9_-]*\b", re.IGNORECASE)
MATH_TRANSLATION = str.maketrans(
    {
        "×": "*",
        "÷": "/",
        "（": "(",
        "）": ")",
        "＝": "=",
        "？": "?",
        "＋": "+",
        "－": "-",
        "＊": "*",
        "／": "/",
    }
)
SAFE_MATH_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
SAFE_MATH_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


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
        self.settings = get_settings()
        self.model_routes: dict[str, dict[str, Any]] = {}

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

        return self.detect_route_decision(question, chat_type, mode)["intent"]

    def detect_route_decision(self, question: str, chat_type: str, mode: str) -> dict[str, Any]:
        """
        识别问答路由。

        返回值兼容原 intent，同时补充 direct_answer 标记供 LangGraph 短路使用。
        """

        direct_rule = self._rule_detect_direct_answer(question, chat_type, mode)
        if direct_rule is not None:
            self.model_routes["intent"] = {
                "task": "intent",
                "source": "rules",
                "reason": direct_rule["reason"],
                "confidence": direct_rule["confidence"],
                "intent": direct_rule["intent"],
                "direct_answer": True,
                "direct_answer_type": direct_rule["direct_answer_type"],
                "route": direct_rule["route"],
                "knowledge_scope": direct_rule["knowledge_scope"],
            }
            return direct_rule

        rule_intent, confidence, reason = self._rule_detect_intent(question, chat_type, mode)
        if confidence >= 0.8:
            decision = self._route_decision(rule_intent, False, reason, confidence)
            self.model_routes["intent"] = {
                "task": "intent",
                "source": "rules",
                "reason": reason,
                "confidence": confidence,
                "intent": rule_intent,
                "direct_answer": False,
                "direct_answer_type": None,
                "route": decision["route"],
                "knowledge_scope": decision["knowledge_scope"],
            }
            return decision

        try:
            llm = LLMService(self.db)
            raw_text = llm.chat(self._build_intent_prompt(question, chat_type, mode, rule_intent), model_type="intent")
            decision = self._parse_route_payload(raw_text, fallback_intent=rule_intent)
            if decision["direct_answer"] and (
                self._is_project_reference_question(question, chat_type, mode) or is_industry_domain_question(question)
            ):
                decision = self._route_decision(rule_intent, False, "命中知识库检索信号，覆盖模型直答判断", confidence)
            self.model_routes["intent"] = {
                **llm.model_route("intent", f"规则置信度 {confidence:.2f}，使用意图模型兜底"),
                "confidence": confidence,
                "intent": decision["intent"],
                "rule_intent": rule_intent,
                "direct_answer": decision["direct_answer"],
                "direct_answer_type": decision["direct_answer_type"],
                "route": decision["route"],
                "knowledge_scope": decision["knowledge_scope"],
                "route_reason": decision["reason"],
            }
            return decision
        except Exception as exc:  # noqa: BLE001
            logger.warning("意图模型兜底失败，回退规则意图: intent=%s error=%s", rule_intent, exc)
            decision = self._route_decision(rule_intent, False, reason, confidence)
            self.model_routes["intent"] = {
                "task": "intent",
                "source": "rules_fallback",
                "reason": f"意图模型兜底失败，回退规则结果：{reason}",
                "confidence": confidence,
                "intent": rule_intent,
                "direct_answer": False,
                "direct_answer_type": None,
                "route": decision["route"],
                "knowledge_scope": decision["knowledge_scope"],
            }
            return decision

    def _rule_detect_intent(self, question: str, chat_type: str, mode: str) -> tuple[str, float, str]:
        """基于确定性信号识别意图，并返回规则置信度。"""

        lowered = question.lower()
        is_project_reference = self._is_project_reference_question(question, chat_type, mode)
        industry_domains = detect_industry_domains(question)
        if is_project_overview_query(question) and is_project_reference:
            return "project_overview", 0.92, "命中项目概览类规则"
        if is_project_reference and ("项目" in question or PROJECT_NAME_PATTERN.search(question)):
            return "project_qa", 0.88, "命中项目资料问答规则"
        if is_project_reference and any(token in question for token in ("物料流向", "流程", "流向", "工艺路线")):
            return "project_qa", 0.88, "命中项目流程问答规则"
        if is_project_reference and any(token in question for token in ("关系", "关联", "影响", "依赖", "连接", "上下游")):
            return "graph_reasoning", 0.86, "命中关系推理类规则"
        if is_project_reference and (
            any(token in lowered for token in ("drawing", "dwg", "page"))
            or any(token in question for token in ("图纸", "图中", "图里", "这张图", "该图", "页", "第"))
        ):
            return "page_location", 0.88, "命中图纸/页码定位规则"
        if is_project_reference and any(token in question for token in ("编号", "位号", "标准", "条款")):
            return "exact_lookup", 0.9, "命中编号/条款精确查询规则"
        if DOC_OR_TAG_PATTERN.search(question):
            return "exact_lookup", 0.92, "命中文号精确查询规则"
        if industry_domains:
            return "industry_knowledge_qa", 0.9, f"命中行业基础知识领域：{','.join(industry_domains)}"
        if chat_type == "project_chat" or mode in {"project_only", "hybrid"}:
            confidence = 0.78 if len(question.strip()) >= 80 else 0.82
            return "project_qa", confidence, "根据项目问答上下文识别为项目资料问答"
        confidence = 0.72 if len(question.strip()) >= 80 else 0.82
        return "knowledge_qa", confidence, "根据基础问答上下文识别为知识问答"

    def _rule_detect_direct_answer(self, question: str, chat_type: str, mode: str) -> dict[str, Any] | None:
        """在调用意图模型前识别可直接回答的问题。"""

        normalized = self._normalize_direct_question(question)
        lowered = normalized.lower()
        if not normalized:
            return None

        project_required = self._is_project_reference_question(question, chat_type, mode)
        industry_required = is_industry_domain_question(question)
        rag_required = project_required or industry_required
        if self._is_greeting_question(normalized, lowered):
            if rag_required:
                return None
            return self._route_decision("greeting", True, "命中问候/自我介绍直答规则", 0.98)

        if rag_required:
            return None

        if self._extract_math_expression(question) is not None:
            return self._route_decision("pure_general_qa", True, "命中简单数学直答规则", 0.96)

        if self._is_pure_general_question(question, normalized, lowered):
            return self._route_decision("pure_general_qa", True, "命中纯通用知识直答规则", 0.9)

        return None

    def _route_decision(self, intent: str, direct_answer: bool, reason: str, confidence: float) -> dict[str, Any]:
        direct_answer_type = intent if direct_answer and intent in DIRECT_INTENTS else None
        if direct_answer_type == "greeting":
            route = "direct_greeting"
        elif direct_answer_type:
            route = "direct_general_qa"
        elif intent == "industry_knowledge_qa":
            route = "industry_knowledge_rag"
        elif intent in {"project_qa", "project_overview", "exact_lookup", "page_location", "graph_reasoning"}:
            route = "project_rag"
        else:
            route = "rag"
        knowledge_scope = self._knowledge_scope_for_intent(intent)
        return {
            "intent": intent,
            "direct_answer": bool(direct_answer_type),
            "direct_answer_type": direct_answer_type,
            "route": route,
            "skip_retrieval": bool(direct_answer_type),
            "knowledge_scope": knowledge_scope,
            "reason": reason,
            "confidence": confidence,
        }

    def _normalize_direct_question(self, question: str) -> str:
        return re.sub(r"[\s，。！？?!.、]+", "", question.strip())

    def _is_greeting_question(self, normalized: str, lowered: str) -> bool:
        if lowered in {"hi", "hello", "hey"}:
            return True
        return any(
            keyword.replace(" ", "").lower() in lowered
            for keyword in GREETING_KEYWORDS
            if keyword.lower() not in {"hi", "hello"}
        )

    def _is_rag_required_question(self, question: str, chat_type: str, mode: str) -> bool:
        lowered = question.lower()
        if any(keyword in lowered or keyword in question for keyword in RAG_REQUIRED_KEYWORDS):
            return True
        if DOC_OR_TAG_PATTERN.search(question):
            return True
        if chat_type == "project_chat" and any(token in question for token in ("这个", "该", "流程", "参数", "设备", "位号", "图", "资料")):
            return True
        if mode in {"project_only", "hybrid"} and any(token in question for token in ("流程", "参数", "设备", "位号", "图", "资料")):
            return True
        return False

    def _is_project_reference_question(self, question: str, chat_type: str, mode: str) -> bool:
        """
        判断问题是否必须优先进入项目资料检索。

        项目资料优先级高于行业知识，但泛化概念题（如“设备位号是什么意思”）不应仅因出现行业术语就误进项目库。
        """

        lowered = question.lower()
        if PROJECT_NAME_PATTERN.search(question) or DOC_OR_TAG_PATTERN.search(question):
            return True
        if any(keyword in lowered or keyword in question for keyword in PROJECT_REFERENCE_KEYWORDS):
            return True
        if is_project_overview_query(question) and "项目" in question:
            return True
        if chat_type == "project_chat" and any(token in question for token in PROJECT_CHAT_HINTS):
            return True
        if mode in {"project_only", "hybrid"} and any(token in question for token in PROJECT_CHAT_HINTS):
            return True
        return False

    def _is_pure_general_question(self, question: str, normalized: str, lowered: str) -> bool:
        """识别无需知识库的纯通用问题，行业术语已在上游排除。"""

        if any(token.replace(" ", "").lower() in lowered for token in PURE_GENERAL_QA_HINTS):
            return True
        if "是什么" in question and any(token in question for token in ("公式", "定律")):
            return True
        if any(token in question for token in ("怎么提高睡眠质量", "今天适合喝水吗")):
            return True
        return False

    def _knowledge_scope_for_intent(self, intent: str) -> str:
        """根据意图计算检索范围，供后续 Planner/Router 约束检索库。"""

        if intent in {"greeting", "pure_general_qa", "general_qa"}:
            return "none"
        if intent == "industry_knowledge_qa":
            return "industry"
        if intent in {"project_qa", "project_overview", "exact_lookup", "page_location", "graph_reasoning"}:
            if self.settings.project_chat_include_industry_knowledge:
                return "project_with_industry"
            return "project"
        return "industry"

    def _build_intent_prompt(self, question: str, chat_type: str, mode: str, rule_intent: str) -> list[dict[str, str]]:
        """构造意图模型兜底提示词。"""

        return [
            {
                "role": "system",
                "content": (
                    "你是企业知识库问答意图识别器。"
                    "你的任务是判断用户问题是否需要进入企业知识库检索。"
                    f"只能从这些意图中选择：{sorted(ALLOWED_INTENTS)}。"
                    "如果问题只是问候、自我介绍、闲聊开场，选择 greeting。"
                    "如果问题是简单数学、普通常识、与行业无关的基础科学或日常生活问题，选择 pure_general_qa。"
                    "如果问题属于电池回收、湿法冶金、工艺设计、PFD/P&ID、设备、公辅、安全环保等行业基础知识，选择 industry_knowledge_qa。"
                    "如果问题涉及项目资料、文件、图纸、设备、参数、页码、来源、内部知识库，必须选择对应的项目 RAG 意图，不要选择 pure_general_qa。"
                    "边界规则："
                    "“1+1=几”“太阳从哪边升起”“牛顿第二定律是什么”选择 pure_general_qa；"
                    "“你是谁”“你好”“你能做什么”选择 greeting；"
                    "“酸浸原理是什么”“黑粉是什么”“P&ID 图怎么看”选择 industry_knowledge_qa；"
                    "“BMI 项目的酸浸流程是什么”选择 project_qa，不要选择 industry_knowledge_qa；"
                    "“这张 P&ID 图中物料流向是什么”选择 project_qa 或 graph_reasoning。"
                    "请只输出 JSON：{\"intent\":\"...\",\"direct_answer\":true/false,\"reason\":\"...\"}。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "chat_type": chat_type,
                        "mode": mode,
                        "rule_intent": rule_intent,
                    },
                    ensure_ascii=False,
                ),
            },
        ]

    def _parse_intent_payload(self, raw_text: str) -> str:
        return self._parse_route_payload(raw_text, fallback_intent="knowledge_qa")["intent"]

    def _parse_route_payload(self, raw_text: str, fallback_intent: str) -> dict[str, Any]:
        stripped = self._strip_json_fence(raw_text)
        payload = json.loads(stripped)
        intent = str(payload.get("intent") or "").strip()
        if intent == "general_qa":
            intent = "pure_general_qa"
        if intent not in ALLOWED_INTENTS:
            raise ValueError(f"unknown intent: {intent}")
        if intent == "rag_required":
            intent = fallback_intent if fallback_intent in RAG_INTENTS else "knowledge_qa"
        direct_answer = bool(payload.get("direct_answer")) or intent in DIRECT_INTENTS
        if intent not in DIRECT_INTENTS:
            direct_answer = False
        reason = str(payload.get("reason") or "意图模型返回路由判断").strip()
        return self._route_decision(intent, direct_answer, reason, 0.0)

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

    def answer_general_question(self, question: str) -> str:
        """回答不依赖企业资料的通用问题。"""

        rule_answer = self._rule_answer_general_question(question)
        if rule_answer:
            self.model_routes["answer"] = {
                "task": "answer",
                "source": "rules",
                "reason": "通用问答命中本地确定性规则，未检索知识库",
            }
            return rule_answer

        try:
            llm = LLMService(self.db)
            answer = llm.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是通用问答助手。请直接回答用户问题，不要引用企业知识库资料，"
                            "不要说“根据资料”。如果问题可能需要结合企业项目资料，请在答案末尾提醒用户指定项目或文件。"
                        ),
                    },
                    {"role": "user", "content": question},
                ],
                model_type="answer_llm",
                max_tokens=800,
                disable_thinking=True,
            )
            self.model_routes["answer"] = llm.model_route("answer", "通用问答使用普通回答模型，未检索知识库")
            normalized_answer = answer.strip()
            if normalized_answer:
                return normalized_answer
            logger.warning("通用问答模型返回空内容，使用规则兜底答案")
            self.model_routes["answer"] = {
                "task": "answer",
                "source": "rules_fallback",
                "reason": "通用问答模型返回空内容，返回无需检索的兜底说明",
            }
            return "这是一个通用问题，不需要查询企业知识库。当前通用回答模型未返回有效内容，请稍后重试或换个更具体的问题。"
        except Exception as exc:  # noqa: BLE001
            logger.warning("通用问答模型调用失败，返回规则兜底答案: error=%s", exc)
            self.model_routes["answer"] = {
                "task": "answer",
                "source": "rules_fallback",
                "reason": "通用问答模型调用失败，返回无需检索的兜底说明",
            }
            return "这是一个通用问题，不需要查询企业知识库。当前通用回答模型暂不可用，请稍后重试或换个更具体的问题。"

    def _rule_answer_general_question(self, question: str) -> str | None:
        math_answer = self._answer_math_question(question)
        if math_answer:
            return math_answer

        normalized = question.strip().lower()
        if "水的沸点" in question:
            return "在标准大气压下，水的沸点约为 100°C。气压变化时，沸点也会随之变化。"
        if "欧姆定律" in question:
            return "欧姆定律描述电压、电流和电阻的关系：U = I × R，其中 U 表示电压，I 表示电流，R 表示电阻。"
        if "bmi" not in normalized and ("是什么" in question or "原理" in question):
            return None
        return None

    def _answer_math_question(self, question: str) -> str | None:
        expression = self._extract_math_expression(question)
        if expression is None:
            return None
        try:
            value = self._safe_eval_math_expression(expression)
        except (ValueError, ZeroDivisionError, OverflowError):
            return None
        return f"{expression} = {self._format_math_value(value)}"

    def _extract_math_expression(self, question: str) -> str | None:
        normalized = question.translate(MATH_TRANSLATION).replace(" ", "")
        normalized = re.sub(r"(?<=\d)[xX](?=\d)", "*", normalized)
        normalized = normalized.replace("等于几", "").replace("等于多少", "")
        if "=" in normalized:
            normalized = normalized.split("=", 1)[0]
        normalized = re.sub(r"(是多少|多少|几|呢|吗|\?)", "", normalized)
        if not any(operator_token in normalized for operator_token in ("+", "-", "*", "/", "%")):
            return None
        if not re.fullmatch(r"[\d.()+\-*/%]+", normalized):
            return None
        return normalized

    def _safe_eval_math_expression(self, expression: str) -> int | float:
        node = ast.parse(expression, mode="eval")
        return self._eval_math_ast(node.body)

    def _eval_math_ast(self, node: ast.AST) -> int | float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp):
            operator_func = SAFE_MATH_BINOPS.get(type(node.op))
            if operator_func is None:
                raise ValueError("unsupported math operator")
            left = self._eval_math_ast(node.left)
            right = self._eval_math_ast(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10:
                raise ValueError("power too large")
            return operator_func(left, right)
        if isinstance(node, ast.UnaryOp):
            operator_func = SAFE_MATH_UNARYOPS.get(type(node.op))
            if operator_func is None:
                raise ValueError("unsupported unary operator")
            return operator_func(self._eval_math_ast(node.operand))
        raise ValueError("unsupported math expression")

    def _format_math_value(self, value: int | float) -> str:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return f"{value:.10g}"

    def judge_evidence(
        self,
        question: str,
        evidences: list[Evidence],
        context: dict[str, Any] | None = None,
    ) -> dict:
        """
        判断证据是否足够回答。

        参数:
            question: 用户问题。
            evidences: 重排后的证据列表。
            context: 检索命中、查询特征等路由上下文。

        返回:
            证据判断结果。
        """

        rule_result = self._rule_judge_evidence(question, evidences)
        if not evidences or not rule_result.get("enough"):
            self.model_routes["evidence_judge"] = {
                "task": "evidence_judge",
                "source": "rules",
                "reason": "无证据或规则判定证据不足，不调用证据模型",
            }
            return rule_result

        if self._should_skip_evidence_model(evidences, context or {}):
            self.model_routes["evidence_judge"] = {
                "task": "evidence_judge",
                "source": "rules",
                "reason": "图纸证据将在视觉回答阶段处理，证据整理阶段不调用证据模型",
            }
            return rule_result

        model_type, reason = self._select_evidence_model(evidences, context or {})
        try:
            llm = LLMService(self.db)
            raw_text = llm.chat(
                self._build_evidence_prompt(question, evidences, rule_result, context or {}),
                model_type=model_type,
                timeout_seconds=self.settings.evidence_judge_timeout_seconds,
                max_tokens=512,
            )
            result = self._parse_evidence_payload(raw_text)
            result["rule_reason"] = rule_result.get("reason")
            self.model_routes["evidence_judge"] = llm.model_route("evidence_judge", reason)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("证据判断模型失败，回退规则判断: model_type=%s error=%s", model_type, exc)
            self.model_routes["evidence_judge"] = {
                "task": "evidence_judge",
                "model_type": model_type,
                "source": "rules_fallback",
                "reason": f"证据模型失败，回退规则判断：{reason}",
            }
            return rule_result

    def _rule_judge_evidence(self, question: str, evidences: list[Evidence]) -> dict[str, Any]:
        """执行确定性证据充足性判断。"""

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

    def _select_evidence_model(self, evidences: list[Evidence], context: dict[str, Any]) -> tuple[str, str]:
        """按证据数量、图片和表格复杂度选择证据判断模型。"""

        evidence_count = len(evidences)
        visual_asset_count = sum(len(evidence.assets) for evidence in evidences)
        table_signal_count = self._table_signal_count(evidences)
        retriever_hit_total = sum(int(value or 0) for value in (context.get("retriever_hits") or {}).values())
        if evidence_count >= 8 or retriever_hit_total >= 10 or visual_asset_count >= 2 or table_signal_count >= 2:
            return (
                "evidence_judge",
                (
                    f"证据复杂度较高：evidence={evidence_count}, hits={retriever_hit_total}, "
                    f"images={visual_asset_count}, tables={table_signal_count}"
                ),
            )
        return (
            "evidence_judge_fast",
            (
                f"少量纯文本证据：evidence={evidence_count}, hits={retriever_hit_total}, "
                f"images={visual_asset_count}, tables={table_signal_count}"
            ),
        )

    def _should_skip_evidence_model(self, evidences: list[Evidence], context: dict[str, Any]) -> bool:
        """
        判断是否跳过证据判断模型。

        图纸图片会在最终回答的视觉模型阶段读取；证据整理阶段只需要判断是否有可用证据，
        避免因为图片数量触发慢模型而阻塞流式 Thinking。
        """

        visual_asset_count = sum(len(evidence.assets) for evidence in evidences)
        if visual_asset_count <= 0:
            return False

        query_features = context.get("query_features") or {}
        has_complex_text_signal = bool(
            query_features.get("has_table_value_lookup")
            or query_features.get("has_table_hint")
            or query_features.get("has_comparison")
            or query_features.get("has_graph_relation")
            or self._table_signal_count(evidences) >= 2
        )
        if has_complex_text_signal:
            return False

        retriever_hit_total = sum(int(value or 0) for value in (context.get("retriever_hits") or {}).values())
        return len(evidences) <= 5 and retriever_hit_total <= 10

    def _build_evidence_prompt(
        self,
        question: str,
        evidences: list[Evidence],
        rule_result: dict[str, Any],
        context: dict[str, Any],
    ) -> list[dict[str, str]]:
        """构造证据判断提示词。"""

        evidence_summaries = [
            {
                "index": index,
                "score": round(float(evidence.score), 4),
                "file_name": evidence.file_name,
                "drawing_no": evidence.drawing_no,
                "page_number": evidence.page_number,
                "content": self._clip(evidence.content, 260),
                "asset_count": len(evidence.assets),
            }
            for index, evidence in enumerate(evidences[:5], start=1)
        ]
        return [
            {
                "role": "system",
                "content": EVIDENCE_JUDGE_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "rule_result": rule_result,
                        "retriever_hits": context.get("retriever_hits", {}),
                        "query_features": context.get("query_features", {}),
                        "query_profile": context.get("query_profile", {}),
                        "available_retrievers": list(KNOWN_RETRIEVERS),
                        "evidences": evidence_summaries,
                    },
                    ensure_ascii=False,
                ),
            },
        ]

    def _parse_evidence_payload(self, raw_text: str) -> dict[str, Any]:
        stripped = self._strip_json_fence(raw_text)
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError("evidence judge payload must be object")
        raw_enough = payload.get("enough")
        if isinstance(raw_enough, bool):
            enough = raw_enough
        elif isinstance(raw_enough, str):
            enough = raw_enough.strip().lower() in {"true", "yes", "1", "是", "足够"}
        else:
            enough = bool(raw_enough)
        return {
            "enough": enough,
            "confidence": self._clamp_confidence(payload.get("confidence"), default=0.65 if enough else 0.45),
            "answerable_parts": self._string_list(payload.get("answerable_parts")),
            "missing_aspects": self._string_list(payload.get("missing_aspects")),
            "best_evidence_indexes": self._index_list(payload.get("best_evidence_indexes")),
            "suggested_retrievers": self._filter_retrievers(payload.get("suggested_retrievers")),
            "suggested_queries": self._string_list(payload.get("suggested_queries"), limit=6, max_length=240),
            "reason": str(payload.get("reason") or "证据模型未返回原因"),
        }

    def _string_list(self, raw_value: Any, limit: int = 8, max_length: int = 180) -> list[str]:
        if not isinstance(raw_value, list):
            return []
        result: list[str] = []
        for item in raw_value:
            text = str(item or "").strip()
            if not text or text in result:
                continue
            result.append(text[:max_length])
        return result[:limit]

    def _index_list(self, raw_value: Any) -> list[int]:
        if not isinstance(raw_value, list):
            return []
        indexes: list[int] = []
        for item in raw_value:
            try:
                value = int(item)
            except (TypeError, ValueError):
                continue
            if value <= 0 or value in indexes:
                continue
            indexes.append(value)
        return indexes[:8]

    def _filter_retrievers(self, raw_value: Any) -> list[str]:
        if not isinstance(raw_value, list):
            return []
        allowed = set(KNOWN_RETRIEVERS)
        result: list[str] = []
        for item in raw_value:
            name = str(item or "").strip().lower()
            if name not in allowed or name in result:
                continue
            result.append(name)
        return result

    def _clamp_confidence(self, raw_value: Any, default: float) -> float:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return default
        return max(0.0, min(1.0, value))

    def _table_signal_count(self, evidences: list[Evidence]) -> int:
        count = 0
        for evidence in evidences:
            content = evidence.content.lower()
            if any(token in content for token in TABLE_HINTS):
                count += 1
        return count

    def _strip_json_fence(self, raw_text: str) -> str:
        stripped = raw_text.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if "\n" in stripped:
                stripped = stripped.split("\n", 1)[1]
            stripped = stripped.rsplit("```", 1)[0].strip()
        return stripped

    def _clip(self, value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return f"{value[:limit]}..."

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
