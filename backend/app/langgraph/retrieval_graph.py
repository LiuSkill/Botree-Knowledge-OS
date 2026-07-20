"""
Retrieval LangGraph

负责：
1. 编排在线问答中的意图识别、查询拆解、检索规划、多路检索、证据判断和回答生成
2. 在 langgraph 依赖不可用时提供等价的顺序执行器
3. 输出前端可展示的 trace_steps 和后端可审计的 raw 调试信息
"""

from __future__ import annotations

import logging
import hashlib
from dataclasses import replace
import re
import time
import uuid
from collections.abc import Iterator
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.agent.answer_generator import AnswerGenerator, PROJECT_REFUSAL_TEXT
from app.core.config import get_settings
from app.langgraph.state import RetrievalGraphState
from app.retrieval.query_utils import TABLE_ROW_PATTERN, extract_query_terms, normalize_query_text
from app.models.user import User
from app.retrieval.merger import EvidenceMerger
from app.retrieval.router import RetrievalRouter
from app.retrieval.schemas import Evidence
from app.retrieval.scope import normalize_retrieval_scope, retrieval_scope_has_filters
from app.services.answer_policy_gate_service import AnswerAction, AnswerPolicyGateService
from app.services.evidence_access_guard_service import EvidenceAccessGuardService
from app.services.evidence_evaluator_service import EvidenceEvaluatorService, EvidenceStatus
from app.services.query_profile_service import QueryProfileService
from app.services.question_understanding_service import QuestionUnderstandingService
from app.services.qwen_orchestration_service import QwenOrchestrationService
from app.services.policy_resolver_service import PolicyResolver
from app.services.rag_prompt_templates import KNOWN_RETRIEVERS
from app.services.reranker_service import RerankerService
from app.services.retrieval_planner_service import RetrievalPlannerService
from app.services.visual_evidence_service import VisualEvidenceService
from app.services.sensitive_content_service import SECURITY_NOTICE, SensitiveContentService

logger = logging.getLogger(__name__)

TRACE_NODE_STEPS = {
    "chat_policy": "问答策略",
    "confirm_state": "确认状态",
    "pre_intent_gate": "快速意图门控",
    "intent": "意图识别",
    "answer_policy_router": "答案策略",
    "query_decompose": "查询拆解",
    "query_profile": "查询画像",
    "question_understanding": "问题理解",
    "policy_resolution": "策略解析",
    "planner": "检索规划",
    "retrieval": "检索执行",
    "evidence_judge": "证据判断",
    "retry_retrieval": "补充检索",
    "evidence_decision": "证据状态",
    "answer_policy_gate": "答案门控",
    "visual_reading": "视觉图纸阅读",
    "answer": "回答生成",
}

ANSWER_POLICY_PRESET = "PRESET_REPLY"
ANSWER_POLICY_GENERAL_ALLOWED = "GENERAL_ALLOWED"
ANSWER_POLICY_STRICT_KB = "STRICT_KB"
ANSWER_POLICY_KB_FIRST = "KB_FIRST"
ANSWER_POLICY_ASK_GENERAL_CONFIRM = "ASK_GENERAL_CONFIRM"
ANSWER_POLICY_CLARIFY = "CLARIFY"

EVIDENCE_ENOUGH = "ENOUGH"
EVIDENCE_WEAK_ONLY = "WEAK_ONLY"
EVIDENCE_PARTIAL = "PARTIAL"
EVIDENCE_EMPTY = "EMPTY"
EVIDENCE_CONFLICTED = "CONFLICTED"
EVIDENCE_INVALID_QUERY = "INVALID_QUERY"

DEFAULT_RETRIEVER_TOP_K = 20
FUSED_EVIDENCE_TOP_K = 20
RERANKED_EVIDENCE_TOP_K = 10
ANSWER_CONTEXT_TOP_K = 10
VISUAL_EVIDENCE_TOP_K = 8

PRESET_GREETING_ANSWER = "您好，我是博萃循环AI智能体，请问有什么可以帮助您的吗？"
PRESET_IDENTITY_ANSWER = "我是博萃循环AI智能体，可以帮助您查询已授权的知识库资料、项目资料和基础知识。"
DIRECT_GREETING_ANSWER = PRESET_GREETING_ANSWER
DIRECT_CAPABILITY_ANSWER = PRESET_IDENTITY_ANSWER
PROJECT_REFUSAL_ANSWER = PROJECT_REFUSAL_TEXT
PROJECT_OVERVIEW_INSUFFICIENT_ANSWER = "当前项目资料不足，项目资料中未检索到足够的项目介绍信息。请补充项目概况、建设内容、设计依据、产品方案或处理规模等资料后重试。"
PROJECT_CLARIFY_ANSWER = "请描述您需要查询的具体项目资料、设备、参数、流程、图纸编号或文件名称。"
BASE_CLARIFY_ANSWER = "请描述您需要查询的问题，或补充更具体的资料、概念、参数或流程名称。"
BASE_GENERAL_CONFIRM_ANSWER = "我没有在当前知识库中检索到足够可靠的资料。是否需要我基于通用知识进行回答？该回答将不引用知识库资料。"
GENERAL_ANSWER_PREFIX = "以下内容基于通用知识生成，未引用当前知识库资料："

INTENT_LABELS = {
    "greeting": "问候闲聊",
    "pure_general_qa": "纯通用问答",
    "general_qa": "通用问答",
    "industry_knowledge_qa": "行业基础知识问答",
    "project_qa": "项目资料问答",
    "knowledge_qa": "知识问答",
    "project_overview": "项目概览问答",
    "exact_lookup": "精确定位问答",
    "page_location": "页级定位问答",
    "graph_reasoning": "图谱推理问答",
    "process_flow": "流程问答",
    "comparison": "对比问答",
    "unknown": "未知类型问答",
}

RETRIEVER_PLAN_LABELS = {
    "milvus": "语义检索",
    "keyword": "关键词检索",
    "page_index": "页级检索",
    "ripgrep": "精确检索",
    "graphrag": "图谱检索",
}

RETRIEVER_HIT_LABELS = {
    "milvus": "Milvus",
    "keyword": "Keyword",
    "page_index": "PageIndex",
    "ripgrep": "Ripgrep",
    "graphrag": "GraphRAG",
}

ANSWER_SHAPE_LABELS = {
    "comparison_table": "对比表格",
    "direct_answer": "直接回答",
    "direct_value": "精确答案",
    "general": "常规回答",
    "industry_explanation": "行业知识回答",
    "process_steps": "流程步骤",
    "project_summary": "项目概览",
    "source_location": "来源定位",
}


class RetrievalGraph:
    """
    在线检索问答图

    职责：
    - 用节点方式组织 Qwen、Planner、Retriever 和 AnswerGenerator
    - 保持 `/chat/completions` 对前端返回结构兼容
    - 在 trace 中保留每个节点的输入、输出和耗时摘要
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.qwen = QwenOrchestrationService(db)
        self.query_profile_service = QueryProfileService()
        self.question_understanding_service = QuestionUnderstandingService()
        self.policy_resolver = PolicyResolver()
        self.evidence_evaluator = EvidenceEvaluatorService()
        self.evidence_access_guard = EvidenceAccessGuardService(db)
        self.answer_policy_gate = AnswerPolicyGateService()
        self.planner = RetrievalPlannerService(db)
        self.retrieval_router = RetrievalRouter(db)
        self.answer_generator = AnswerGenerator(db)
        self.merger = EvidenceMerger()
        self.reranker = RerankerService(db)
        self.visual_evidence_service = VisualEvidenceService(db)
        self.sensitive_content_service = SensitiveContentService(db)
        self._compiled_graph = self._try_compile_langgraph()

    def prepare(
        self,
        question: str,
        chat_type: str,
        mode: str,
        project_id: int | None,
        user: User,
        *,
        eval_mode: bool = False,
        return_evidence: bool = False,
        retrieval_limit: int | None = None,
        candidate_k: int | None = None,
        rerank_top_k: int | None = None,
        eval_top_k: int | None = None,
        answer_top_k: int | None = None,
        retrieval_mode: str = "full",
        require_real_reranker: bool = True,
        allow_reranker_fallback: bool = True,
        reranker_score_order: str = "desc",
    ) -> RetrievalGraphState:
        """
        先执行到证据判断阶段，为流式回答准备可复用的检索上下文。
        """

        state = self._build_initial_state(
            question,
            chat_type,
            mode,
            project_id,
            user,
            backend="sequential_prepare",
            eval_mode=eval_mode,
            return_evidence=return_evidence,
            retrieval_limit=retrieval_limit,
            candidate_k=candidate_k,
            rerank_top_k=rerank_top_k,
            eval_top_k=eval_top_k,
            answer_top_k=answer_top_k,
            retrieval_mode=retrieval_mode,
            require_real_reranker=require_real_reranker,
            allow_reranker_fallback=allow_reranker_fallback,
            reranker_score_order=reranker_score_order,
        )
        logger.info(
            "LangGraph预处理开始: run_id=%s user_id=%s chat_type=%s mode=%s project_id=%s question_meta=%s",
            state.get("raw", {}).get("run_id"),
            getattr(user, "id", None),
            chat_type,
            mode,
            project_id,
            self._text_log_metadata(question),
        )
        prepared_state = self._run_until_evidence_judge(state)
        logger.info(
            "LangGraph预处理完成: run_id=%s evidence_count=%s query_scope=%s",
            prepared_state.get("raw", {}).get("run_id"),
            len(prepared_state.get("evidences", [])),
            prepared_state.get("query_scope"),
        )
        return prepared_state

    def prepare_stream(
        self,
        question: str,
        chat_type: str,
        mode: str,
        project_id: int | None,
        user: User,
        *,
        eval_mode: bool = False,
        return_evidence: bool = False,
        retrieval_limit: int | None = None,
        candidate_k: int | None = None,
        rerank_top_k: int | None = None,
        eval_top_k: int | None = None,
        answer_top_k: int | None = None,
        retrieval_mode: str = "full",
        require_real_reranker: bool = True,
        allow_reranker_fallback: bool = True,
        reranker_score_order: str = "desc",
    ) -> Iterator[tuple[str, Any]]:
        """
        流式执行检索准备阶段，按 LangGraph 节点产出前端 Thinking 所需的 trace_delta。
        """

        state = self._build_initial_state(
            question,
            chat_type,
            mode,
            project_id,
            user,
            backend="sequential_prepare_stream",
            eval_mode=eval_mode,
            return_evidence=return_evidence,
            retrieval_limit=retrieval_limit,
            candidate_k=candidate_k,
            rerank_top_k=rerank_top_k,
            eval_top_k=eval_top_k,
            answer_top_k=answer_top_k,
            retrieval_mode=retrieval_mode,
            require_real_reranker=require_real_reranker,
            allow_reranker_fallback=allow_reranker_fallback,
            reranker_score_order=reranker_score_order,
        )
        logger.info(
            "LangGraph预处理流开始: run_id=%s user_id=%s chat_type=%s mode=%s project_id=%s question_meta=%s",
            state.get("raw", {}).get("run_id"),
            getattr(user, "id", None),
            chat_type,
            mode,
            project_id,
            self._text_log_metadata(question),
        )
        for trace_key, node in self._prepare_node_specs():
            sequence = self.next_trace_sequence(state)
            state.setdefault("raw", {})["active_trace_sequence"] = sequence
            state["raw"]["active_trace_display_key"] = trace_key
            yield "trace_delta", self._running_trace_delta(state, trace_key, sequence)

            trace_count = len(state.get("trace", []))
            try:
                state = node(state)
            except Exception:
                failed_item = self._latest_trace_item(state, trace_count)
                if failed_item is not None:
                    yield "trace_delta", self.trace_delta_payload(failed_item)
                raise

            trace_item = self._latest_trace_item(state, trace_count)
            if trace_item is not None:
                trace_item["display_text"] = self._trace_success_text(trace_key, state, trace_item)
                yield "trace_delta", self.trace_delta_payload(trace_item)

            if trace_key == "retrieval" or (
                trace_key == "retry_retrieval" and int(state.get("raw", {}).get("retry_count") or 0) > 0
            ):
                for visual_delta in self._visual_reading_trace_deltas(state):
                    yield "trace_delta", visual_delta

            if trace_key in {"pre_intent_gate", "intent", "answer_policy_router"} and self._should_direct_answer(state):
                answer_sequence = self.next_trace_sequence(state)
                state.setdefault("raw", {})["active_trace_sequence"] = answer_sequence
                state["raw"]["active_trace_display_key"] = "answer"
                yield "trace_delta", self._running_trace_delta(state, "answer", answer_sequence)

                trace_count = len(state.get("trace", []))
                try:
                    state = self._direct_answer_node(state)
                except Exception:
                    failed_item = self._latest_trace_item(state, trace_count)
                    if failed_item is not None:
                        yield "trace_delta", self.trace_delta_payload(failed_item)
                    raise

                trace_item = self._latest_trace_item(state, trace_count)
                if trace_item is not None:
                    trace_item["display_text"] = self._trace_success_text("answer", state, trace_item)
                    yield "trace_delta", self.trace_delta_payload(trace_item)
                break
            if self._is_terminal_without_answer_generation(state):
                break

        logger.info(
            "LangGraph预处理流完成: run_id=%s evidence_count=%s query_scope=%s",
            state.get("raw", {}).get("run_id"),
            len(state.get("evidences", [])),
            state.get("query_scope"),
        )
        yield "prepared", state

    def finalize_answer(
        self,
        state: RetrievalGraphState,
        answer: str,
        elapsed_ms: int | None = None,
        trace_sequence: int | None = None,
    ) -> dict[str, Any]:
        """
        将流式收敛后的答案补回状态，并补写回答节点 trace。
        """

        self._apply_final_answer_filter(state, answer)
        final_state = self._append_answer_trace(state, str(state.get("answer") or ""), elapsed_ms, trace_sequence)
        logger.info(
            "LangGraph流式回答完成: run_id=%s final_mode=%s evidence_count=%s answer_preview=%s",
            final_state.get("raw", {}).get("run_id"),
            final_state.get("mode"),
            len(final_state.get("evidences", [])),
            self._clip(final_state.get("answer", ""), 300),
        )
        return self._to_agent_result(final_state)

    def to_agent_result(self, state: RetrievalGraphState) -> dict[str, Any]:
        """将已完成的状态转换为旧 AgentExecutor 兼容输出。"""

        return self._to_agent_result(state)

    def run(
        self,
        question: str,
        chat_type: str,
        mode: str,
        project_id: int | None,
        user: User,
        *,
        eval_mode: bool = False,
        return_evidence: bool = False,
        retrieval_limit: int | None = None,
        candidate_k: int | None = None,
        rerank_top_k: int | None = None,
        eval_top_k: int | None = None,
        answer_top_k: int | None = None,
        retrieval_mode: str = "full",
        require_real_reranker: bool = True,
        allow_reranker_fallback: bool = True,
        reranker_score_order: str = "desc",
    ) -> dict[str, Any]:
        """
        执行在线问答图。

        参数:
            question: 用户问题
            chat_type: 问答类型
            mode: 问答模式
            project_id: 项目ID
            user: 当前用户

        返回:
            与旧 AgentExecutor 兼容的结果字典
        """

        state = self._build_initial_state(
            question,
            chat_type,
            mode,
            project_id,
            user,
            backend="langgraph" if self._compiled_graph is not None else "sequential",
            eval_mode=eval_mode,
            return_evidence=return_evidence,
            retrieval_limit=retrieval_limit,
            candidate_k=candidate_k,
            rerank_top_k=rerank_top_k,
            eval_top_k=eval_top_k,
            answer_top_k=answer_top_k,
            retrieval_mode=retrieval_mode,
            require_real_reranker=require_real_reranker,
            allow_reranker_fallback=allow_reranker_fallback,
            reranker_score_order=reranker_score_order,
        )
        run_id = state.get("raw", {}).get("run_id")
        logger.info(
            "LangGraph问答开始: run_id=%s user_id=%s chat_type=%s mode=%s project_id=%s question_meta=%s",
            run_id,
            getattr(user, "id", None),
            chat_type,
            mode,
            project_id,
            self._text_log_metadata(question),
        )
        if self._compiled_graph is not None:
            final_state = self._compiled_graph.invoke(state)
        else:
            final_state = self._run_sequential(state)
        self._apply_final_answer_filter(final_state)
        logger.info(
            "LangGraph问答完成: run_id=%s final_mode=%s evidence_count=%s answer_preview=%s",
            final_state.get("raw", {}).get("run_id"),
            final_state.get("mode"),
            len(final_state.get("evidences", [])),
            self._clip(final_state.get("answer", ""), 300),
        )
        return self._to_agent_result(final_state)

    def _build_initial_state(
        self,
        question: str,
        chat_type: str,
        mode: str,
        project_id: int | None,
        user: User,
        backend: str,
        eval_mode: bool = False,
        return_evidence: bool = False,
        retrieval_limit: int | None = None,
        candidate_k: int | None = None,
        rerank_top_k: int | None = None,
        eval_top_k: int | None = None,
        answer_top_k: int | None = None,
        retrieval_mode: str = "full",
        require_real_reranker: bool = False,
        allow_reranker_fallback: bool = True,
        reranker_score_order: str = "desc",
    ) -> RetrievalGraphState:
        """构建问答图初始状态。"""

        return {
            "question": question,
            "chat_type": chat_type,
            "mode": mode,
            "project_id": project_id,
            "user": user,
            "trace": [],
            "model_routes": {},
            "evidence_evaluation": {},
            "answer_policy_action": "",
            "answer_policy_decision": {},
            "raw": {
                "langgraph_backend": backend,
                "run_id": uuid.uuid4().hex,
                "eval_mode": bool(eval_mode),
                "return_evidence": bool(return_evidence),
                "retrieval_limit": int(retrieval_limit) if retrieval_limit is not None else None,
                "candidate_k": int(candidate_k) if candidate_k is not None else DEFAULT_RETRIEVER_TOP_K,
                "rerank_top_k": int(rerank_top_k) if rerank_top_k is not None else FUSED_EVIDENCE_TOP_K,
                "eval_top_k": int(eval_top_k) if eval_top_k is not None else RERANKED_EVIDENCE_TOP_K,
                "answer_top_k": int(answer_top_k) if answer_top_k is not None else ANSWER_CONTEXT_TOP_K,
                "retrieval_mode": str(retrieval_mode or "full"),
                "require_real_reranker": bool(require_real_reranker),
                "allow_reranker_fallback": bool(allow_reranker_fallback),
                "reranker_score_order": str(reranker_score_order or "desc"),
                "retrieval_total_budget_ms": int(self._settings().retrieval_total_budget_ms),
                "retrieval_retry_budget_ms": int(self._settings().retrieval_retry_budget_ms),
                "retrieval_min_stage_budget_ms": int(self._settings().retrieval_min_stage_budget_ms),
                "retrieval_min_retry_budget_ms": int(self._settings().retrieval_min_retry_budget_ms),
                "retrieval_max_sub_queries": int(self._settings().retrieval_max_sub_queries),
                "retrieval_max_retry_queries": int(self._settings().retrieval_max_retry_queries),
                "retrieval_max_retry_retrievers": int(self._settings().retrieval_max_retry_retrievers),
                "retrieval_page_index_candidate_limit": int(self._settings().retrieval_page_index_candidate_limit),
                "retrieval_page_index_row_limit": int(self._settings().retrieval_page_index_row_limit),
                "retrieval_ripgrep_candidate_limit": int(self._settings().retrieval_ripgrep_candidate_limit),
                "retrieval_ripgrep_row_limit": int(self._settings().retrieval_ripgrep_row_limit),
                "retrieval_ripgrep_pattern_limit": int(self._settings().retrieval_ripgrep_pattern_limit),
                "retrieval_ripgrep_max_count_per_file": int(self._settings().retrieval_ripgrep_max_count_per_file),
            },
        }

    def _prepare_node_specs(self) -> list[tuple[str, Callable[[RetrievalGraphState], RetrievalGraphState]]]:
        """返回检索准备阶段的节点顺序与前端展示阶段标识。"""

        return [
            ("chat_policy", self._chat_policy_node),
            ("confirm_state", self._confirm_state_node),
            ("pre_intent_gate", self._pre_intent_gate_node),
            ("intent", self._intent_node),
            ("answer_policy_router", self._answer_policy_router_node),
            ("query_decompose", self._query_decompose_node),
            ("query_profile", self._query_profile_node),
            ("question_understanding", self._question_understanding_node),
            ("policy_resolution", self._policy_resolution_node),
            ("planner", self._planner_node),
            ("retrieval", self._retrieval_node),
            ("evidence_judge", self._evidence_judge_node),
            ("retry_retrieval", self._retry_retrieval_node),
            ("evidence_decision", self._evidence_decision_node),
            ("answer_policy_gate", self._answer_policy_gate_node),
        ]

    def _sequential_node_specs(self) -> list[tuple[str, Callable[[RetrievalGraphState], RetrievalGraphState]]]:
        """返回完整同步问答阶段的节点顺序与前端展示阶段标识。"""

        return [*self._prepare_node_specs(), ("answer", self._answer_node)]

    def _run_until_evidence_judge(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """按固定顺序运行到证据判断结束。"""

        for trace_key, node in self._prepare_node_specs():
            state.setdefault("raw", {})["active_trace_display_key"] = trace_key
            state = node(state)
            if trace_key in {"pre_intent_gate", "intent", "answer_policy_router"} and self._should_direct_answer(state):
                state.setdefault("raw", {})["active_trace_display_key"] = "answer"
                return self._direct_answer_node(state)
            if self._is_terminal_without_answer_generation(state):
                return state
        return state

    def _run_sequential(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        按固定节点顺序执行兼容编排。

        参数:
            state: 初始状态

        返回:
            最终状态
        """

        for trace_key, node in self._sequential_node_specs():
            state.setdefault("raw", {})["active_trace_display_key"] = trace_key
            state = node(state)
            if trace_key in {"pre_intent_gate", "intent", "answer_policy_router"} and self._should_direct_answer(state):
                state.setdefault("raw", {})["active_trace_display_key"] = "answer"
                return self._direct_answer_node(state)
            if trace_key != "answer" and self._is_terminal_without_answer_generation(state):
                return state
        return state

    def _append_answer_trace(
        self,
        state: RetrievalGraphState,
        answer: str,
        elapsed_ms: int | None = None,
        trace_sequence: int | None = None,
    ) -> RetrievalGraphState:
        """为流式收敛后的最终答案补写回答节点 trace。"""

        step = "回答生成"
        implementation = "answer_generator"
        input_summary = self._state_log_context(state)
        action = str(state.get("answer_policy_action") or AnswerAction.NORMAL_ANSWER.value)
        state["answer"] = answer
        state["answer_type"] = action
        state["need_user_confirm"] = False
        state["pending_action"] = None
        raw = state.setdefault("raw", {})
        raw["answer_type"] = action
        raw["kb_grounded"] = action == AnswerAction.NORMAL_ANSWER.value
        raw["direct_llm_used"] = False
        raw["refused"] = False
        raw["need_general_confirm"] = False
        raw["reranker_used"] = True
        output_summary = self._state_log_output(state)
        trace_item = {
            "sequence": trace_sequence or self.next_trace_sequence(state),
            "step": step,
            "implementation": implementation,
            "status": "success",
            "elapsed_ms": elapsed_ms or 0,
            "intent": state.get("intent"),
            "sub_query_index": None,
            "sub_query_total": len(state.get("sub_queries", [])),
            "input_summary": input_summary,
            "output_summary": output_summary,
            "details": self._trace_details(step, state, "answer"),
        }
        trace_item["display_text"] = self._trace_success_text("answer", state, trace_item)
        state.setdefault("trace", []).append(trace_item)
        logger.info(
            "LangGraph鑺傜偣瀹屾垚: run_id=%s step=%s implementation=%s status=success elapsed_ms=%s intent=%s sub_query_total=%s output_summary=%s",
            state.get("raw", {}).get("run_id"),
            step,
            implementation,
            elapsed_ms or 0,
            state.get("intent"),
            len(state.get("sub_queries", [])),
            self._clip(str(output_summary), 1600),
        )
        return state

    def _try_compile_langgraph(self):
        """
        尝试编译真实 LangGraph。

        返回:
            编译后的图；不可用时返回 None
        """

        try:
            from langgraph.graph import END, StateGraph
        except Exception:
            logger.info("langgraph依赖不可用，使用顺序兼容执行器")
            return None
        try:
            graph = StateGraph(RetrievalGraphState)
            graph.add_node("chat_policy", self._chat_policy_node)
            graph.add_node("confirm_state", self._confirm_state_node)
            graph.add_node("pre_intent_gate", self._pre_intent_gate_node)
            graph.add_node("intent", self._intent_node)
            graph.add_node("answer_policy_router", self._answer_policy_router_node)
            graph.add_node("query_decompose", self._query_decompose_node)
            graph.add_node("query_profile", self._query_profile_node)
            graph.add_node("question_understanding", self._question_understanding_node)
            graph.add_node("policy_resolution", self._policy_resolution_node)
            graph.add_node("retrieval_planner", self._planner_node)
            graph.add_node("retrieval", self._retrieval_node)
            graph.add_node("evidence_judge", self._evidence_judge_node)
            graph.add_node("retry_retrieval", self._retry_retrieval_node)
            graph.add_node("evidence_decision", self._evidence_decision_node)
            graph.add_node("answer_policy_gate", self._answer_policy_gate_node)
            graph.add_node("answer", self._answer_node)
            graph.add_node("direct_answer", self._direct_answer_node)
            graph.set_entry_point("chat_policy")
            graph.add_edge("chat_policy", "confirm_state")
            graph.add_edge("confirm_state", "pre_intent_gate")
            graph.add_conditional_edges(
                "pre_intent_gate",
                self._route_after_intent,
                {
                    "direct_answer": "direct_answer",
                    "query_decompose": "intent",
                },
            )
            graph.add_conditional_edges(
                "intent",
                self._route_after_intent,
                {
                    "direct_answer": "direct_answer",
                    "query_decompose": "answer_policy_router",
                },
            )
            graph.add_conditional_edges(
                "answer_policy_router",
                self._route_after_answer_policy_router,
                {
                    "direct_answer": "direct_answer",
                    "query_decompose": "query_decompose",
                },
            )
            graph.add_edge("query_decompose", "query_profile")
            graph.add_edge("query_profile", "question_understanding")
            graph.add_edge("question_understanding", "policy_resolution")
            graph.add_edge("policy_resolution", "retrieval_planner")
            graph.add_edge("retrieval_planner", "retrieval")
            graph.add_edge("retrieval", "evidence_judge")
            graph.add_edge("evidence_judge", "retry_retrieval")
            graph.add_edge("retry_retrieval", "evidence_decision")
            graph.add_edge("evidence_decision", "answer_policy_gate")
            graph.add_conditional_edges(
                "answer_policy_gate",
                self._route_after_answer_policy_gate,
                {
                    "answer": "answer",
                    "end": END,
                },
            )
            graph.add_edge("answer", END)
            graph.add_edge("direct_answer", END)
            return graph.compile()
        except Exception:
            logger.exception("LangGraph编译失败，使用顺序兼容执行器")
            return None

    def _with_trace(
        self,
        state: RetrievalGraphState,
        step: str,
        implementation: str,
        func: Callable[[], RetrievalGraphState],
    ) -> RetrievalGraphState:
        """
        执行节点并记录结构化 trace。

        参数:
            state: 当前状态
            step: 节点名称
            implementation: 节点实现来源
            func: 节点执行函数

        返回:
            节点执行后的状态
        """

        run_id = state.get("raw", {}).get("run_id")
        input_summary = self._state_log_context(state)
        logger.info(
            "LangGraph节点开始: run_id=%s step=%s implementation=%s status=started intent=%s sub_query_total=%s input_summary=%s",
            run_id,
            step,
            implementation,
            state.get("intent"),
            len(state.get("sub_queries", [])),
            self._clip(str(input_summary), 1200),
        )
        started_at = time.perf_counter()
        try:
            next_state = func()
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            output_summary = self._state_log_output(next_state)
            raw = next_state.setdefault("raw", {})
            trace_key = str(raw.pop("active_trace_display_key", "") or self._infer_trace_key(step, implementation))
            sequence = raw.pop("active_trace_sequence", None) or self.next_trace_sequence(next_state)
            self._record_trace_timing(next_state, trace_key, elapsed_ms, "success")
            trace_item = {
                "sequence": sequence,
                "step": step,
                "implementation": implementation,
                "status": "success",
                "elapsed_ms": elapsed_ms,
                "intent": next_state.get("intent"),
                "sub_query_index": None,
                "sub_query_total": len(next_state.get("sub_queries", [])),
                "input_summary": input_summary,
                "output_summary": output_summary,
                "details": self._trace_details(step, next_state, trace_key),
            }
            trace_item["display_text"] = self._trace_success_text(trace_key, next_state, trace_item)
            next_state.setdefault("trace", []).append(trace_item)
            logger.info(
                "LangGraph节点完成: run_id=%s step=%s implementation=%s status=success elapsed_ms=%s intent=%s sub_query_total=%s output_summary=%s",
                run_id,
                step,
                implementation,
                elapsed_ms,
                next_state.get("intent"),
                len(next_state.get("sub_queries", [])),
                self._clip(str(output_summary), 1600),
            )
            return next_state
        except Exception:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            raw = state.setdefault("raw", {})
            trace_key = str(raw.pop("active_trace_display_key", "") or self._infer_trace_key(step, implementation))
            sequence = raw.pop("active_trace_sequence", None) or self.next_trace_sequence(state)
            self._record_trace_timing(state, trace_key, elapsed_ms, "failed")
            trace_item = {
                "sequence": sequence,
                "step": step,
                "implementation": implementation,
                "status": "failed",
                "elapsed_ms": elapsed_ms,
                "intent": state.get("intent"),
                "sub_query_index": None,
                "sub_query_total": len(state.get("sub_queries", [])),
                "input_summary": input_summary,
                "output_summary": {},
                "details": self._trace_details(step, state, trace_key),
            }
            trace_item["display_text"] = self._trace_failed_text(trace_key)
            state.setdefault("trace", []).append(trace_item)
            logger.exception(
                "LangGraph节点失败: run_id=%s step=%s implementation=%s status=failed elapsed_ms=%s intent=%s input_summary=%s",
                run_id,
                step,
                implementation,
                elapsed_ms,
                state.get("intent"),
                self._clip(str(input_summary), 1200),
            )
            raise

    def _chat_policy_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """根据 chat_type 固定本轮问答的基础策略和 RAG 参数。"""

        def run() -> RetrievalGraphState:
            chat_type = str(state.get("chat_type") or "base_chat")
            answer_policy = ANSWER_POLICY_STRICT_KB if chat_type == "project_chat" else ANSWER_POLICY_KB_FIRST
            state["chat_policy"] = {
                "chat_type": chat_type,
                "default_answer_policy": answer_policy,
                "candidate_k": self._candidate_k(state),
                "rerank_top_k": self._rerank_top_k(state),
                "eval_top_k": self._eval_top_k(state),
                "answer_top_k": self._answer_top_k(state),
                "require_default_hybrid": True,
                "require_real_reranker": True,
            }
            raw = state.setdefault("raw", {})
            raw["candidate_k"] = self._candidate_k(state)
            raw["rerank_top_k"] = self._rerank_top_k(state)
            raw["eval_top_k"] = self._eval_top_k(state)
            raw["answer_top_k"] = self._answer_top_k(state)
            # 项目问答优先真实 reranker，但超时后允许降级到确定性重排，避免整条检索链路失败。
            raw["require_real_reranker"] = True
            raw["allow_reranker_fallback"] = True
            raw["answer_policy"] = answer_policy
            return state

        return self._with_trace(state, "问答模式策略", "rules", run)

    def _confirm_state_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """记录会话确认态入口；实际 pending 读写由 ChatService 持久化处理。"""

        def run() -> RetrievalGraphState:
            state.setdefault("raw", {})["confirm_state_checked"] = True
            return state

        return self._with_trace(state, "通用回答确认状态", "chat_session", run)

    def _pre_intent_gate_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """在调用意图模型前拦截预设回复和明显常识问题。"""

        def run() -> RetrievalGraphState:
            if self._is_invalid_query(state["question"]) and not self._preset_intent_type(state["question"]):
                state["intent_type"] = "invalid"
                state["intent"] = "unknown"
                state["answer_policy"] = ANSWER_POLICY_CLARIFY
                state["direct_answer"] = True
                state["direct_answer_type"] = "invalid"
                state["evidence_status"] = EVIDENCE_INVALID_QUERY
                state["route_decision"] = self._structured_route_decision(
                    intent_type="invalid",
                    intent="unknown",
                    answer_policy=ANSWER_POLICY_CLARIFY,
                    need_retrieval=False,
                    allow_direct_llm=False,
                    reason="命中无效输入门控",
                    confidence=1.0,
                )
                raw = state.setdefault("raw", {})
                raw["route"] = "clarify"
                raw["query_validity"] = "invalid"
                raw["skip_retrieval"] = True
                raw["route_reason"] = "命中无效输入门控"
                logger.info(
                    "快速门控命中无效输入: run_id=%s chat_type=%s question_meta=%s skip_retrieval=true",
                    raw.get("run_id"),
                    state.get("chat_type"),
                    self._text_log_metadata(state.get("question", "")),
                )
                return state

            intent_type = self._preset_intent_type(state["question"])
            if intent_type:
                state["intent_type"] = intent_type
                state["intent"] = intent_type if intent_type != "bot_identity" else "greeting"
                state["answer_policy"] = ANSWER_POLICY_PRESET
                state["direct_answer"] = True
                state["direct_answer_type"] = intent_type
                state["route_decision"] = self._structured_route_decision(
                    intent_type=intent_type,
                    intent=state["intent"],
                    answer_policy=ANSWER_POLICY_PRESET,
                    need_retrieval=False,
                    allow_direct_llm=False,
                    reason="命中预设问答规则",
                    confidence=1.0,
                )
                raw = state.setdefault("raw", {})
                raw["route"] = "preset_reply"
                raw["skip_retrieval"] = True
                raw["route_reason"] = "命中预设问答规则"
                return state

            if state.get("chat_type") == "base_chat" and self._is_obvious_common_knowledge(state["question"]):
                state["intent_type"] = "obvious_common_knowledge"
                state["intent"] = "pure_general_qa"
                state["answer_policy"] = ANSWER_POLICY_GENERAL_ALLOWED
                state["direct_answer"] = True
                state["direct_answer_type"] = "obvious_common_knowledge"
                state["route_decision"] = self._structured_route_decision(
                    intent_type="obvious_common_knowledge",
                    intent="pure_general_qa",
                    answer_policy=ANSWER_POLICY_GENERAL_ALLOWED,
                    need_retrieval=False,
                    allow_direct_llm=True,
                    reason="命中明显常识直答规则",
                    confidence=0.98,
                )
                raw = state.setdefault("raw", {})
                raw["route"] = "direct_general_qa"
                raw["skip_retrieval"] = True
                raw["route_reason"] = "命中明显常识直答规则"
            return state

        return self._with_trace(state, "快速意图门控", "rules", run)

    def _intent_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        Qwen 意图识别节点。

        参数:
            state: 当前状态

        返回:
            写入 intent 的状态
        """

        def run() -> RetrievalGraphState:
            route_decision = self.qwen.detect_route_decision(state["question"], state["chat_type"], state["mode"])
            if bool(state.get("raw", {}).get("eval_mode")) and state.get("chat_type") == "project_chat":
                original_route_decision = dict(route_decision)
                route_decision = {
                    **route_decision,
                    "intent": "project_qa",
                    "route": "project_rag",
                    "direct_answer": False,
                    "direct_answer_type": None,
                    "skip_retrieval": False,
                    "reason": "eval_mode 强制使用评测项目检索，避免公开测试集问题被直答或行业知识路由跳过项目索引",
                }
                state.setdefault("raw", {})["eval_original_route_decision"] = original_route_decision
            state["intent"] = route_decision["intent"]
            state["direct_answer"] = bool(route_decision.get("direct_answer"))
            state["direct_answer_type"] = route_decision.get("direct_answer_type")
            state["route_decision"] = route_decision
            raw = state.setdefault("raw", {})
            raw["route"] = route_decision.get("route") or "rag"
            raw["skip_retrieval"] = bool(route_decision.get("skip_retrieval"))
            raw["route_reason"] = route_decision.get("reason")
            raw["route_decision"] = route_decision
            if state["direct_answer"]:
                state["query_features"] = {
                    "direct_answer_type": route_decision.get("direct_answer_type"),
                    "skip_retrieval": True,
                }
            state["intent_type"] = str(route_decision.get("intent_type") or self._intent_to_intent_type(state["intent"]))
            state["answer_policy"] = str(
                route_decision.get("answer_policy")
                or self._answer_policy_for_intent(state["intent_type"], state["chat_type"])
            )
            if state.get("chat_type") == "project_chat" and state["intent_type"] == "obvious_common_knowledge":
                state["intent"] = "project_qa"
                state["intent_type"] = "project_fact"
                state["answer_policy"] = ANSWER_POLICY_STRICT_KB
                state["direct_answer"] = False
                state["direct_answer_type"] = None
                state["route_decision"] = {
                    **route_decision,
                    "intent": "project_qa",
                    "intent_type": "project_fact",
                    "answer_policy": ANSWER_POLICY_STRICT_KB,
                    "direct_answer": False,
                    "direct_answer_type": None,
                    "need_retrieval": True,
                    "allow_direct_llm": False,
                    "skip_retrieval": False,
                    "route": "project_rag",
                    "knowledge_scope": "project",
                    "reason": "project_chat 禁止非预设直答，转为项目资料检索",
                }
                raw["skip_retrieval"] = False
                raw["route"] = "project_rag"
                raw["route_reason"] = "project_chat 禁止非预设直答，转为项目资料检索"
                raw["route_decision"] = state["route_decision"]
            raw["answer_policy"] = state["answer_policy"]
            raw["intent_type"] = state["intent_type"]
            state.setdefault("model_routes", {})["intent"] = self.qwen.model_routes.get("intent", {})
            return state

        return self._with_trace(state, "用户意图识别", "qwen", run)

    def _route_after_intent(self, state: RetrievalGraphState) -> str:
        return "direct_answer" if self._should_direct_answer(state) else "query_decompose"

    def _route_after_answer_policy_router(self, state: RetrievalGraphState) -> str:
        return "direct_answer" if self._should_direct_answer(state) else "query_decompose"

    def _route_after_answer_policy_gate(self, state: RetrievalGraphState) -> str:
        return "end" if self._is_terminal_without_answer_generation(state) else "answer"

    def _should_direct_answer(self, state: RetrievalGraphState) -> bool:
        if bool(state.get("raw", {}).get("eval_mode")) and state.get("chat_type") == "project_chat":
            return False
        answer_policy = str(state.get("answer_policy") or "")
        if state.get("chat_type") == "project_chat":
            if answer_policy == ANSWER_POLICY_PRESET:
                return True
            return answer_policy == ANSWER_POLICY_CLARIFY and state.get("direct_answer_type") == "invalid"
        if answer_policy == ANSWER_POLICY_PRESET:
            return True
        if answer_policy == ANSWER_POLICY_GENERAL_ALLOWED:
            return self._is_safe_general_direct_answer(state)
        return bool(state.get("direct_answer")) and self._is_safe_general_direct_answer(state)

    def _is_safe_general_direct_answer(self, state: RetrievalGraphState) -> bool:
        intent_type = str(state.get("intent_type") or "")
        direct_answer_type = str(state.get("direct_answer_type") or state.get("intent") or "")
        query_profile = state.get("query_profile", {}) or {}
        query_type = str(query_profile.get("query_type") or "")
        scope = str(query_profile.get("knowledge_scope") or "")
        if scope in {"project", "industry"}:
            return False
        project_markers = {
            "project_fact",
            "industry_knowledge",
            "process_flow",
            "equipment_relation",
            "parameter_lookup",
            "project_overview",
            "graph_reasoning",
            "page_location",
            "exact_lookup",
            "comparison",
        }
        if intent_type in project_markers or direct_answer_type in project_markers or query_type in project_markers:
            return False
        allowed = {
            "greeting",
            "identity",
            "bot_identity",
            "help",
            "obvious_common_knowledge",
            "simple_math_or_formula",
        }
        return (
            intent_type in allowed
            or direct_answer_type in allowed
            or str(state.get("intent") or "") == "greeting"
            or self._is_obvious_common_knowledge(str(state.get("question") or ""))
        )

    def _is_terminal_without_answer_generation(self, state: RetrievalGraphState) -> bool:
        return bool(state.get("raw", {}).get("terminal_without_answer_generation"))

    def _preset_intent_type(self, question: str) -> str | None:
        normalized = str(question or "").strip().lower()
        compact = normalized.replace(" ", "")
        if compact in {"你好", "您好", "hi", "hello", "嗨"}:
            return "greeting"
        if any(key in compact for key in ("你是谁", "你叫什么", "介绍一下你")):
            return "bot_identity"
        if any(key in compact for key in ("帮助", "怎么用", "使用说明", "能做什么")) and len(compact) <= 24:
            return "help"
        return None

    def _is_invalid_query(self, question: str) -> bool:
        compact = str(question or "").strip().lower().replace(" ", "")
        if not compact:
            return True
        noise_values = {
            "哈哈",
            "哈哈哈",
            "hhh",
            "hhhh",
            "2333",
            "测试",
            "test",
            "111",
            "123",
            "嗯",
            "啊",
            "额",
            "?",
            "？",
            "??",
            "？？",
            "???",
            "？？？",
            "。。。",
            "...",
            "asdf",
        }
        if compact in noise_values:
            return True
        if len(compact) <= 2 and not any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in compact):
            return True
        if len(compact) <= 3 and not any(term in compact for term in ("图", "泵", "水", "酸", "锂", "镍", "钴", "项目")):
            return True
        if all(not (ch.isalnum() or "\u4e00" <= ch <= "\u9fff") for ch in compact):
            return True
        return False

    def _is_obvious_common_knowledge(self, question: str) -> bool:
        compact = str(question or "").strip().lower().replace(" ", "")
        if not compact:
            return False
        domain_terms = (
            "项目", "资料", "图纸", "设备", "参数", "工艺", "合同", "标书", "设计", "厂区",
            "黑粉", "回收", "浸出", "萃取", "电化学", "压滤机", "过滤器", "行业", "规范",
        )
        if any(term in compact for term in domain_terms):
            return False
        if compact in {"1+1等于几", "1+1=几", "一加一等于几", "水的化学式是什么", "水的化学式"}:
            return True
        if any(key in compact for key in ("等于几", "多少度沸腾", "首都是哪里", "化学式是什么")) and len(compact) <= 30:
            return True
        return False

    def _structured_route_decision(
        self,
        *,
        intent_type: str,
        intent: str,
        answer_policy: str,
        need_retrieval: bool,
        allow_direct_llm: bool,
        reason: str,
        confidence: float,
    ) -> dict[str, Any]:
        return {
            "intent": intent,
            "intent_type": intent_type,
            "chat_type": "",
            "need_retrieval": need_retrieval,
            "allow_direct_llm": allow_direct_llm,
            "answer_policy": answer_policy,
            "confidence": confidence,
            "reason": reason,
            "direct_answer": not need_retrieval,
            "direct_answer_type": intent_type if not need_retrieval else None,
            "skip_retrieval": not need_retrieval,
            "route": "direct" if not need_retrieval else "rag",
        }

    def _intent_to_intent_type(self, intent: str) -> str:
        mapping = {
            "greeting": "greeting",
            "pure_general_qa": "obvious_common_knowledge",
            "general_qa": "obvious_common_knowledge",
            "industry_knowledge_qa": "industry_knowledge",
            "project_qa": "project_fact",
            "project_overview": "project_fact",
            "exact_lookup": "document_lookup",
            "page_location": "drawing_or_page_location",
            "graph_reasoning": "project_fact",
            "process_flow": "project_fact",
            "comparison": "project_fact",
            "knowledge_qa": "kb_question",
            "invalid": "invalid",
        }
        return mapping.get(str(intent or ""), "ambiguous")

    def _answer_policy_for_intent(self, intent_type: str, chat_type: str) -> str:
        if intent_type in {"greeting", "bot_identity", "help"}:
            return ANSWER_POLICY_PRESET
        if intent_type in {"invalid", "invalid_or_noise_query", "ambiguous"}:
            return ANSWER_POLICY_CLARIFY
        if chat_type == "project_chat":
            if intent_type == "obvious_common_knowledge":
                return ANSWER_POLICY_CLARIFY
            return ANSWER_POLICY_STRICT_KB
        if intent_type == "obvious_common_knowledge":
            return ANSWER_POLICY_GENERAL_ALLOWED
        return ANSWER_POLICY_KB_FIRST

    def _answer_policy_router_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """根据 chat_type 和 intent_type 生成最终答案策略。"""

        def run() -> RetrievalGraphState:
            intent_type = str(state.get("intent_type") or self._intent_to_intent_type(str(state.get("intent") or "")))
            answer_policy = self._answer_policy_for_intent(intent_type, str(state.get("chat_type") or "base_chat"))
            state["intent_type"] = intent_type
            state["answer_policy"] = answer_policy
            raw = state.setdefault("raw", {})
            raw["intent_type"] = intent_type
            raw["answer_policy"] = answer_policy
            if answer_policy in {ANSWER_POLICY_PRESET, ANSWER_POLICY_GENERAL_ALLOWED}:
                state["direct_answer"] = True
                state["direct_answer_type"] = intent_type
                raw["skip_retrieval"] = True
            return state

        return self._with_trace(state, "答案策略路由", "rules", run)

    def _retrieval_limit(self, state: RetrievalGraphState) -> int:
        raw_limit = state.get("raw", {}).get("retrieval_limit")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = DEFAULT_RETRIEVER_TOP_K
        return max(1, min(limit, DEFAULT_RETRIEVER_TOP_K))

    def _candidate_k(self, state: RetrievalGraphState) -> int:
        raw = state.get("raw", {})
        raw_limit = raw.get("candidate_k") or raw.get("retrieval_limit")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = self._default_candidate_k(state)
        return max(1, min(limit, DEFAULT_RETRIEVER_TOP_K))

    def _rerank_top_k(self, state: RetrievalGraphState) -> int:
        raw = state.get("raw", {})
        raw_limit = raw.get("rerank_top_k")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = self._default_rerank_top_k(state)
        return max(1, min(limit, FUSED_EVIDENCE_TOP_K))

    def _eval_top_k(self, state: RetrievalGraphState) -> int:
        raw = state.get("raw", {})
        raw_limit = raw.get("eval_top_k")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = self._default_eval_top_k(state)
        return max(1, min(limit, RERANKED_EVIDENCE_TOP_K))

    def _answer_top_k(self, state: RetrievalGraphState) -> int:
        raw_limit = state.get("raw", {}).get("answer_top_k")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = ANSWER_CONTEXT_TOP_K
        if limit != ANSWER_CONTEXT_TOP_K:
            logger.warning("answer_top_k=%s 当前真实答案生成链路固定使用Top10", limit)
        return ANSWER_CONTEXT_TOP_K

    def _default_candidate_k(self, _state: RetrievalGraphState) -> int:
        return DEFAULT_RETRIEVER_TOP_K

    def _default_rerank_top_k(self, _state: RetrievalGraphState) -> int:
        return FUSED_EVIDENCE_TOP_K

    def _default_eval_top_k(self, _state: RetrievalGraphState) -> int:
        return RERANKED_EVIDENCE_TOP_K

    def _is_flow_visual_query(self, state: RetrievalGraphState) -> bool:
        query_profile = state.get("query_profile") or {}
        query_features = state.get("query_features") or {}
        query_type = str(query_profile.get("query_type") or "")
        answer_shape = str(query_profile.get("answer_shape") or "")
        return bool(
            query_type == "process_flow"
            or answer_shape == "process_steps"
            or query_profile.get("need_visual_asset")
            or query_features.get("has_page_hint")
            or query_features.get("has_doc_code")
        )

    def _visual_query_context(self, state: RetrievalGraphState) -> dict[str, Any]:
        """汇总视觉证据增强所需的稳定信号，避免仅靠关键词触发。"""

        query_features = dict(state.get("query_features") or {})
        query_profile = state.get("query_profile") or {}
        understanding = state.get("question_understanding") or {}
        retrieval_needs = understanding.get("retrieval_needs") or {}

        query_features["query_type"] = str(query_profile.get("query_type") or query_features.get("query_type") or "")
        query_features["answer_shape"] = str(
            query_profile.get("answer_shape") or query_features.get("answer_shape") or ""
        )
        query_features["need_visual_asset"] = bool(
            query_profile.get("need_visual_asset") or query_features.get("need_visual_asset")
        )
        query_features["visual_evidence"] = bool(
            query_features.get("visual_evidence")
            or self._is_flow_visual_query(state)
            or (isinstance(retrieval_needs, dict) and retrieval_needs.get("visual_evidence"))
        )
        if isinstance(retrieval_needs, dict) and retrieval_needs:
            query_features["retrieval_needs"] = dict(retrieval_needs)
        return query_features

    def _retrieval_mode(self, state: RetrievalGraphState) -> str:
        mode = str(state.get("raw", {}).get("retrieval_mode") or "full").strip().lower()
        return mode if mode in {"fast", "smart", "full"} else "full"

    def _settings(self) -> Any:
        return getattr(self, "settings", get_settings())

    def _ensure_retrieval_clock(self, state: RetrievalGraphState) -> float:
        raw = state.setdefault("raw", {})
        started_at = raw.get("retrieval_started_at")
        if isinstance(started_at, (int, float)):
            return float(started_at)
        current = time.perf_counter()
        raw["retrieval_started_at"] = current
        return current

    def _ensure_retry_clock(self, state: RetrievalGraphState) -> float:
        raw = state.setdefault("raw", {})
        started_at = raw.get("retry_started_at")
        if isinstance(started_at, (int, float)):
            return float(started_at)
        current = time.perf_counter()
        raw["retry_started_at"] = current
        return current

    def _remaining_budget_ms(self, started_at: float | None, budget_ms: int | None) -> int | None:
        if started_at is None or budget_ms is None:
            return None
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        return max(int(budget_ms) - elapsed_ms, 0)

    def _remaining_retrieval_budget_ms(self, state: RetrievalGraphState) -> int | None:
        raw = state.get("raw", {})
        started_at = raw.get("retrieval_started_at")
        budget_ms = raw.get("retrieval_total_budget_ms")
        if not isinstance(started_at, (int, float)):
            return None
        try:
            normalized_budget = int(budget_ms)
        except (TypeError, ValueError):
            return None
        return self._remaining_budget_ms(float(started_at), normalized_budget)

    def _remaining_retry_budget_ms(self, state: RetrievalGraphState) -> int | None:
        raw = state.get("raw", {})
        started_at = raw.get("retry_started_at")
        budget_ms = raw.get("retrieval_retry_budget_ms")
        if not isinstance(started_at, (int, float)):
            return None
        try:
            normalized_budget = int(budget_ms)
        except (TypeError, ValueError):
            return None
        return self._remaining_budget_ms(float(started_at), normalized_budget)

    def _effective_retry_budget_ms(self, state: RetrievalGraphState) -> int | None:
        budgets = [
            value
            for value in (
                self._remaining_retrieval_budget_ms(state),
                self._remaining_retry_budget_ms(state),
            )
            if value is not None
        ]
        if not budgets:
            return None
        return max(0, min(budgets))

    def _max_sub_queries(self, state: RetrievalGraphState) -> int:
        raw_limit = state.get("raw", {}).get("retrieval_max_sub_queries")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = int(self._settings().retrieval_max_sub_queries)
        return max(1, min(limit, 3))

    def _max_retry_queries(self, state: RetrievalGraphState) -> int:
        raw_limit = state.get("raw", {}).get("retrieval_max_retry_queries")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = int(self._settings().retrieval_max_retry_queries)
        return max(1, min(limit, 4))

    def _max_retry_retrievers(self, state: RetrievalGraphState) -> int:
        raw_limit = state.get("raw", {}).get("retrieval_max_retry_retrievers")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = int(self._settings().retrieval_max_retry_retrievers)
        return max(1, min(limit, 3))

    def _min_stage_budget_ms(self, state: RetrievalGraphState) -> int:
        raw_limit = state.get("raw", {}).get("retrieval_min_stage_budget_ms")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = int(self._settings().retrieval_min_stage_budget_ms)
        return max(0, min(limit, 5000))

    def _min_retry_budget_ms(self, state: RetrievalGraphState) -> int:
        raw_limit = state.get("raw", {}).get("retrieval_min_retry_budget_ms")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = int(self._settings().retrieval_min_retry_budget_ms)
        return max(0, min(limit, 5000))

    def _looks_like_exact_lookup_fragment(self, query: str) -> bool:
        return bool(
            re.search(r"\b[A-Z]{1,8}[A-Z0-9]*[-_/][A-Z0-9]{2,}(?:[-_/][A-Z0-9]{2,})*\b", query, re.IGNORECASE)
            or re.search(r"\b\d+(?:\.\d+){1,3}\b", query)
            or re.search(r"\b\d+\s*[xX]\s*\d+\b", query)
        )

    def _looks_like_meta_retry_query(self, query: str) -> bool:
        lowered = normalize_query_text(query).lower()
        blocked_fragments = (
            "无法确定",
            "当前资料",
            "未检索到",
            "缺乏",
            "没有相关信息",
            "完整规格",
            "相关信息",
            "相关资料",
            "哪一份文档属于",
            "which document belongs",
            "unable to determine",
            "not found",
            "missing aspects",
            "suggested queries",
        )
        return any(fragment in lowered for fragment in blocked_fragments)

    def _search_query_quality_score(self, query: str, original_question: str) -> int:
        normalized = normalize_query_text(query)
        if not normalized:
            return -100
        if normalized == normalize_query_text(original_question):
            return 100
        if self._looks_like_meta_retry_query(normalized):
            return -80

        score = 0
        terms = extract_query_terms(normalized)
        if self._looks_like_exact_lookup_fragment(normalized):
            score += 45
        if len(terms) >= 2:
            score += 18
        elif len(terms) == 1:
            score += 4
        if any(char.isdigit() for char in normalized) and any("\u4e00" <= char <= "\u9fff" or char.isalpha() for char in normalized):
            score += 12
        if " " in normalized and len(normalized) >= 8:
            score += 8
        if re.fullmatch(r"\d{1,6}", normalized):
            score -= 60
        if len(normalized) < 6 and not self._looks_like_exact_lookup_fragment(normalized):
            score -= 18
        if any(marker in normalized for marker in ("哪个", "哪一", "是什么", "什么是", "有哪些", "指哪个")) and not self._looks_like_exact_lookup_fragment(normalized):
            score -= 20
        if len(terms) == 1 and re.fullmatch(r"[\u4e00-\u9fff]{2,8}", terms[0]) and not self._looks_like_exact_lookup_fragment(normalized):
            score -= 16
        return score

    def _sanitize_search_queries(
        self,
        original_question: str,
        candidates: list[Any],
        *,
        limit: int,
        prefer_original: bool = True,
    ) -> list[str]:
        normalized_original = normalize_query_text(original_question)
        scored: list[tuple[int, int, str]] = []
        seen: set[str] = set()
        for index, item in enumerate(candidates):
            text = normalize_query_text(str(item or "")).strip()
            if not text or len(text) > 120:
                continue
            key = text.lower()
            if key in seen:
                continue
            score = self._search_query_quality_score(text, normalized_original)
            if text == normalized_original and not prefer_original:
                score = min(score, 5)
            if text != normalized_original and score < 10:
                continue
            seen.add(key)
            scored.append((score, index, text))

        scored.sort(key=lambda item: (-item[0], item[1]))
        result: list[str] = []
        if prefer_original and normalized_original and normalized_original.lower() in seen:
            result.append(normalized_original)
        for _, _, text in scored:
            if text in result:
                continue
            result.append(text)
            if len(result) >= limit:
                break
        return result[:limit] if result else ([normalized_original] if normalized_original else [])

    def _enforce_default_hybrid_plan(
        self,
        plan_dict: dict[str, Any],
        available_retrievers: list[str],
        retrieval_mode: str,
        query_features: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """确保默认语义检索，同时仅在精确查询场景追加 keyword。"""

        available = set(available_retrievers)
        metadata = dict(plan_dict.get("metadata") or {})
        preserve_planner_ladder = bool(
            metadata.get("policy_matrix_used")
            or (query_features or {}).get("has_structured_list_lookup")
            or (query_features or {}).get("has_table_value_lookup")
        )
        if preserve_planner_ladder:
            selected = [name for name in list(plan_dict.get("selected_retrievers") or []) if name in available]
            fallback_ladder = [
                [name for name in stage if name in available]
                for stage in list(plan_dict.get("fallback_ladder") or [])
            ]
            fallback_ladder = [stage for stage in fallback_ladder if stage]
            skipped = [
                name
                for name in available_retrievers
                if name not in selected and not any(name in stage for stage in fallback_ladder)
            ]
            skip_reasons = {
                key: value
                for key, value in dict(plan_dict.get("skip_reasons") or {}).items()
                if key in skipped
            }
            metadata.update(
                {
                    "default_hybrid_used": False,
                    "reranker_used": bool(plan_dict.get("reranker_used", True)),
                    "retrievers_added": [],
                    "retrieval_mode": retrieval_mode,
                }
            )
            return {
                **plan_dict,
                "selected_retrievers": selected,
                "fallback_retrievers": [],
                "fallback_ladder": fallback_ladder or ([selected] if selected else []),
                "skipped_retrievers": skipped,
                "skip_reasons": skip_reasons,
                "metadata": metadata,
                "default_hybrid_used": False,
                "reranker_used": bool(plan_dict.get("reranker_used", True)),
                "retrievers_added": [],
                "route_reason": plan_dict.get("reason", ""),
            }
        query_profile = (query_features or {}).get("query_profile") or {}
        if query_profile.get("query_type") == "project_overview":
            selected = [name for name in list(plan_dict.get("selected_retrievers") or []) if name in available]
            fallback_ladder = [[name for name in stage if name in available] for stage in list(plan_dict.get("fallback_ladder") or [])]
            fallback_ladder = [stage for stage in fallback_ladder if stage]
            skipped = [name for name in available_retrievers if name not in selected and not any(name in stage for stage in fallback_ladder)]
            metadata = dict(plan_dict.get("metadata") or {})
            metadata.update(
                {
                    "default_hybrid_used": "milvus" in selected,
                    "reranker_used": bool(plan_dict.get("reranker_used", True)),
                    "retrievers_added": [],
                    "retrieval_mode": retrieval_mode,
                    "auto_keyword_used": "keyword" in selected,
                }
            )
            return {
                **plan_dict,
                "selected_retrievers": selected,
                "fallback_retrievers": [],
                "fallback_ladder": fallback_ladder or ([selected] if selected else []),
                "skipped_retrievers": skipped,
                "skip_reasons": {
                    key: value
                    for key, value in dict(plan_dict.get("skip_reasons") or {}).items()
                    if key in skipped
                },
                "metadata": metadata,
                "default_hybrid_used": "milvus" in selected,
                "reranker_used": bool(plan_dict.get("reranker_used", True)),
                "retrievers_added": [],
                "weights": plan_dict.get("weights") or {"project_metadata": 0.3, "milvus": 1.0, "keyword": 0.7},
                "route_reason": plan_dict.get("reason", ""),
            }
        required = [name for name in ("milvus",) if name in available]
        auto_optional: list[str] = []
        if "keyword" in available and self._should_auto_add_keyword(query_features or {}):
            auto_optional.append("keyword")
        required_with_optional = [*required, *auto_optional]
        selected = list(dict.fromkeys([*required_with_optional, *list(plan_dict.get("selected_retrievers") or [])]))
        stages = list(plan_dict.get("fallback_ladder") or [])
        optional = [
            name
            for stage in stages
            for name in stage
            if name in available and name not in required_with_optional
        ]
        first_stage = list(dict.fromkeys([*required_with_optional, *optional]))
        fallback_ladder = [first_stage] if first_stage else stages
        selected = [name for name in selected if name in available]
        skipped = [name for name in available_retrievers if name not in selected and name not in first_stage]
        skip_reasons = {
            key: value
            for key, value in dict(plan_dict.get("skip_reasons") or {}).items()
            if key in skipped
        }
        metadata = dict(plan_dict.get("metadata") or {})
        metadata.update(
            {
                "default_hybrid_used": bool(required),
                "reranker_used": True,
                "retrievers_added": [
                    name for name in required_with_optional if name not in list(plan_dict.get("selected_retrievers") or [])
                ],
                "retrieval_mode": retrieval_mode,
                "auto_keyword_used": "keyword" in auto_optional,
            }
        )
        return {
            **plan_dict,
            "selected_retrievers": selected,
            "fallback_retrievers": [],
            "fallback_ladder": fallback_ladder,
            "skipped_retrievers": skipped,
            "skip_reasons": skip_reasons,
            "metadata": metadata,
            "default_hybrid_used": bool(required),
            "reranker_used": True,
            "retrievers_added": metadata["retrievers_added"],
            "weights": plan_dict.get("weights") or {"milvus": 1.0, "keyword": 0.7},
            "route_reason": plan_dict.get("reason", ""),
        }

    def _should_auto_add_keyword(self, query_features: dict[str, Any]) -> bool:
        try:
            keyword_count = int(query_features.get("keyword_count") or len(query_features.get("terms") or []))
        except (TypeError, ValueError):
            keyword_count = 0
        try:
            query_length = int(query_features.get("query_length") or 0)
        except (TypeError, ValueError):
            query_length = 0
        return bool(
            query_features.get("has_exact_token")
            or query_features.get("has_doc_code")
            or query_features.get("has_table_value_lookup")
            or query_features.get("has_element_symbol")
            or keyword_count >= 2
            or query_length >= 6
        )

    def _evidence_debug_id(self, evidence: Evidence) -> str:
        """Build a stable evidence id for eval traces."""

        return f"{evidence.document_id}:{evidence.chunk_id}"

    def _evidence_score(self, evidence: Evidence) -> float:
        try:
            return float(evidence.score)
        except (TypeError, ValueError):
            return 0.0

    def _top_scored_evidences(self, evidences: list[Evidence], limit: int) -> list[Evidence]:
        if limit <= 0:
            return []
        return sorted(evidences, key=self._evidence_score, reverse=True)[:limit]

    def _record_answer_context(self, state: RetrievalGraphState) -> list[Evidence]:
        """Record the fixed Top10 answer context without changing eval_top_k evidences."""

        answer_top_k = self._answer_top_k(state)
        answer_evidences = self._top_scored_evidences(
            self._preferred_answer_context(state, list(state.get("evidences", [])), answer_top_k),
            answer_top_k,
        )
        # 部分纯算法单测使用 object.__new__ 构造不完整实例；正式链路必须具备服务并执行过滤。
        if hasattr(self, "sensitive_content_service") or hasattr(self, "db"):
            answer_evidences = self._sanitize_evidences(state, answer_evidences)
        raw = state.setdefault("raw", {})
        raw["answer_top_k"] = answer_top_k
        raw["answer_context_count"] = len(answer_evidences)
        raw["answer_context_doc_ids"] = [self._evidence_debug_id(evidence) for evidence in answer_evidences]
        raw["final_answer_doc_ids_top5"] = raw["answer_context_doc_ids"][:5]
        raw["final_answer_doc_ids_top10"] = raw["answer_context_doc_ids"][:10]
        return answer_evidences

    def prepare_answer_context(self, state: RetrievalGraphState) -> list[Evidence]:
        """为流式链路准备安全上下文；返回后可安全进入 LLM 和前端 citation。"""

        evidences = self._record_answer_context(state)
        state["evidences"] = evidences
        return evidences

    def _sanitize_evidences(self, state: RetrievalGraphState, evidences: list[Evidence]) -> list[Evidence]:
        user = state.get("user")
        if user is None:
            return []  # 无法判定权限时默认不放行证据内容。
        safe_evidences: list[Evidence] = []
        allowed_types, rules = self.sensitive_content_service.runtime_config_for_user(user)
        redaction_types: set[str] = set(state.get("redaction_types", []))
        redaction_count = int(state.get("redaction_count") or 0)
        for evidence in evidences:
            result = self.sensitive_content_service.runtime_filter.filter(evidence.content, allowed_types, rules)
            safe_evidences.append(replace(evidence, content=result.safe_content))
            redaction_types.update(result.redaction_types)
            redaction_count += result.redaction_count
        state["redaction_types"] = sorted(redaction_types)
        state["redaction_count"] = redaction_count
        state["redacted"] = bool(redaction_types)
        return safe_evidences

    def _preferred_answer_context(
        self,
        state: RetrievalGraphState,
        evidences: list[Evidence],
        limit: int,
    ) -> list[Evidence]:
        if not evidences:
            return []
        query_features = state.get("query_features", {}) or {}
        if not query_features.get("has_structured_list_lookup"):
            return self._top_scored_evidences(evidences, limit)

        row_evidences = [evidence for evidence in evidences if self._is_structured_list_row_evidence(evidence)]
        dominant_group = self._dominant_structured_list_group(row_evidences)
        if dominant_group is None:
            return self._top_scored_evidences(evidences, limit)

        prioritized = [evidence for evidence in row_evidences if self._structured_list_group_key(evidence) == dominant_group]
        supporting = [
            evidence
            for evidence in evidences
            if self._structured_list_group_key(evidence) == dominant_group and evidence not in prioritized
        ]
        remaining = [evidence for evidence in evidences if self._structured_list_group_key(evidence) != dominant_group]
        return self._top_scored_evidences([*prioritized, *supporting, *remaining], limit)

    def _should_skip_retry_for_structured_list_partial(
        self,
        state: RetrievalGraphState,
        evaluation: dict[str, Any],
    ) -> bool:
        if str(evaluation.get("evidence_status") or EVIDENCE_EMPTY) != EVIDENCE_PARTIAL:
            return False
        query_features = state.get("query_features", {}) or {}
        if not query_features.get("has_structured_list_lookup"):
            return False
        row_evidences = [evidence for evidence in state.get("evidences", []) if self._is_structured_list_row_evidence(evidence)]
        dominant_group = self._dominant_structured_list_group(row_evidences)
        if dominant_group is None:
            return False
        dominant_rows = [evidence for evidence in row_evidences if self._structured_list_group_key(evidence) == dominant_group]
        return len(dominant_rows) >= 3

    def _is_structured_list_row_evidence(self, evidence: Evidence) -> bool:
        return bool(TABLE_ROW_PATTERN.search(str(getattr(evidence, "content", "") or "")))

    def _structured_list_group_key(self, evidence: Evidence) -> tuple[int | None, int | None]:
        return (getattr(evidence, "document_id", None), getattr(evidence, "page_number", None))

    def _dominant_structured_list_group(self, evidences: list[Evidence]) -> tuple[int | None, int | None] | None:
        if not evidences:
            return None
        groups: dict[tuple[int | None, int | None], dict[str, Any]] = {}
        for index, evidence in enumerate(evidences):
            key = self._structured_list_group_key(evidence)
            group = groups.setdefault(
                key,
                {
                    "first_index": index,
                    "best_score": float(evidence.score),
                    "top3_score_sum": 0.0,
                    "scores": [],
                },
            )
            group["first_index"] = min(int(group["first_index"]), index)
            group["best_score"] = max(float(group["best_score"]), float(evidence.score))
            group["scores"].append(float(evidence.score))
        for group in groups.values():
            scores = sorted(group.pop("scores"), reverse=True)
            group["row_count"] = len(scores)
            group["top3_score_sum"] = sum(scores[:3])
        ranked = sorted(
            groups.items(),
            key=lambda item: (
                float(item[1]["best_score"]),
                float(item[1]["top3_score_sum"]),
                int(item[1]["row_count"]),
                -int(item[1]["first_index"]),
            ),
            reverse=True,
        )
        return ranked[0][0] if ranked else None

    def _rerank_evidences(
        self,
        state: RetrievalGraphState,
        candidates: list[Evidence],
        limit: int,
    ) -> list[Evidence]:
        """兼容真实 reranker 与旧单测假对象的签名差异。"""

        skip_reason = self._reranker_skip_reason(state, candidates)
        if skip_reason:
            raw = state.setdefault("raw", {})
            raw["reranker_used"] = False
            raw["reranker_skipped_reason"] = skip_reason
            try:
                self.reranker.last_details = [{"skipped": True, "reason": skip_reason}]
            except Exception:
                pass
            logger.info(
                "Reranker跳过: run_id=%s reason=%s candidate_count=%s intent_type=%s",
                raw.get("run_id"),
                skip_reason,
                len(candidates),
                state.get("intent_type"),
            )
            return self._top_scored_evidences(candidates, limit)

        kwargs = {
            "require_real_model": bool(state.get("raw", {}).get("require_real_reranker")),
            "allow_fallback": bool(state.get("raw", {}).get("allow_reranker_fallback")),
            "score_order": str(state.get("raw", {}).get("reranker_score_order") or "desc"),
        }
        try:
            return self.reranker.rerank(state["question"], candidates, limit, **kwargs)
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise
            return self.reranker.rerank(state["question"], candidates, limit)

    def _reranker_skip_reason(self, state: RetrievalGraphState, candidates: list[Evidence]) -> str | None:
        if not candidates:
            return "NO_VALID_CANDIDATES"
        if str(state.get("raw", {}).get("query_validity") or "") == "invalid":
            return "INVALID_QUERY"
        if state.get("intent_type") in {"invalid", "invalid_or_noise_query", "ambiguous"}:
            return "INVALID_OR_AMBIGUOUS_INTENT"
        if self._is_flow_visual_query(state) and any(item.retriever == "page_index" for item in candidates):
            return "FLOW_VISUAL_PAGE_INDEX_PRIORITY"
        if state.get("intent") == "project_overview" and len(candidates) <= 12:
            return "PROJECT_OVERVIEW_LIGHTWEIGHT_DEDUPE"
        if max((float(item.score) for item in candidates), default=0.0) <= 0:
            return "LOW_SCORE_CANDIDATES"
        return None

    def _direct_answer_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        直答节点。

        greeting/general_qa 不进入查询拆解、检索规划、检索和证据判断。
        """

        def run() -> RetrievalGraphState:
            answer_type = str(state.get("direct_answer_type") or state.get("intent") or "general_qa")
            answer_policy = str(state.get("answer_policy") or ANSWER_POLICY_GENERAL_ALLOWED)
            intent_type = str(state.get("intent_type") or answer_type)
            route = "direct_greeting" if state.get("intent") == "greeting" else "direct_general_qa"
            if answer_policy == ANSWER_POLICY_CLARIFY:
                answer = self._clarify_answer(state)
                state.setdefault("model_routes", {})["answer"] = {
                    "task": "answer",
                    "source": "rules",
                    "reason": "无效或不明确输入命中澄清规则，未检索知识库",
                }
                query_scope = "澄清问题"
                state["answer_type"] = "clarify"
                route = "clarify"
            elif answer_policy == ANSWER_POLICY_PRESET:
                answer = self._greeting_answer(state["question"])
                state.setdefault("model_routes", {})["answer"] = {
                    "task": "answer",
                    "source": "rules",
                    "reason": "问候/自我介绍命中固定回复，未检索知识库",
                }
                query_scope = "闲聊问候"
                state["answer_type"] = "preset"
            else:
                answer = self.qwen.answer_general_question(state["question"])
                state.setdefault("model_routes", {})["answer"] = self.qwen.model_routes.get("answer", {})
                query_scope = "通用问答"
                state["answer_type"] = "general_llm"

            self._apply_final_answer_filter(state, answer)
            state["direct_answer"] = True
            state["direct_answer_type"] = answer_type
            state["intent_type"] = intent_type
            state["answer_policy"] = answer_policy
            state["evidence_status"] = EVIDENCE_INVALID_QUERY if answer_policy == ANSWER_POLICY_CLARIFY else EVIDENCE_EMPTY
            state["need_user_confirm"] = False
            state["pending_action"] = None
            state["sub_queries"] = []
            state["query_profile"] = {
                "query_type": answer_type,
                "answer_shape": "direct_answer",
                "knowledge_scope": "none",
                "is_industry_domain": False,
                "industry_domains": [],
                "reason": "直答问题不进入知识库检索链路",
            }
            state["query_features"] = {
                **state.get("query_features", {}),
                "direct_answer_type": answer_type,
                "skip_retrieval": True,
            }
            state["retrieval_plan"] = {
                "selected_retrievers": [],
                "fallback_retrievers": [],
                "fallback_ladder": [],
                "reason": "直答问题跳过检索规划",
                "confidence": 1.0,
                "qwen_used": False,
                "strategy": "direct_answer",
                "rule_id": route,
                "skipped_retrievers": [],
                "skip_reasons": {},
                "query_features": state["query_features"],
            }
            state["query_scope"] = query_scope
            state["used_retrievers"] = []
            state["planned_retrievers"] = []
            state["executed_retrievers"] = []
            state["skipped_retrievers"] = []
            state["skip_reasons"] = {}
            state["fallback_ladder"] = []
            state["fallback_used"] = []
            state["fallback_trigger_reason"] = []
            state["retriever_hits"] = {}
            state["retriever_elapsed_ms"] = {}
            state["retriever_top_scores"] = {}
            state["rerank_details"] = []
            state["evidences"] = []
            state["visual_asset_count"] = 0
            state["evidence_judgement"] = {
                "enough": True,
                "reason": "直答场景无需检索证据",
                "direct_answer": True,
            }
            raw = state.setdefault("raw", {})
            raw["route"] = route
            raw["skip_retrieval"] = True
            raw["route_reason"] = raw.get("route_reason") or "命中直答规则"
            raw["query_features"] = state["query_features"]
            raw["retrieval_plan"] = state["retrieval_plan"]
            raw["planned_retrievers"] = []
            raw["skipped_retrievers"] = []
            raw["fallback_ladder"] = []
            raw["answer_policy"] = answer_policy
            raw["intent_type"] = intent_type
            raw["answer_type"] = state["answer_type"]
            raw["evidence_status"] = state["evidence_status"]
            raw["query_validity"] = "invalid" if answer_policy == ANSWER_POLICY_CLARIFY else raw.get("query_validity", "valid")
            raw["direct_llm_used"] = answer_policy == ANSWER_POLICY_GENERAL_ALLOWED
            raw["kb_grounded"] = False
            raw["refused"] = False
            raw["need_general_confirm"] = False
            raw["reranker_used"] = False
            logger.info(
                "LangGraph直答短路: run_id=%s route=%s intent=%s skip_retrieval=%s reason=%s",
                raw.get("run_id"),
                route,
                state.get("intent"),
                True,
                raw.get("route_reason"),
            )
            return state

        return self._with_trace(state, "回答生成", "direct_answer", run)

    def _clarify_answer(self, state: RetrievalGraphState) -> str:
        if state.get("chat_type") == "project_chat":
            return PROJECT_CLARIFY_ANSWER
        return BASE_CLARIFY_ANSWER

    def _greeting_answer(self, question: str) -> str:
        normalized = question.replace(" ", "")
        if any(keyword in normalized for keyword in ("你是谁", "你叫什么", "介绍一下你", "你能做什么", "可以做什么", "有什么功能", "能帮我做什么", "帮助", "怎么用")):
            return PRESET_IDENTITY_ANSWER
        return PRESET_GREETING_ANSWER

    def _query_decompose_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        Qwen 查询拆解节点。

        参数:
            state: 当前状态

        返回:
            写入 sub_queries 的状态
        """

        def run() -> RetrievalGraphState:
            raw_sub_queries = self.qwen.decompose_query(state["question"], state["intent"])
            state["sub_queries"] = self._sanitize_search_queries(
                state["question"],
                raw_sub_queries or [state["question"]],
                limit=self._max_sub_queries(state),
            )
            state.setdefault("model_routes", {})["query_decompose"] = {
                "task": "query_decompose",
                "source": "rules",
                "reason": "查询拆解使用确定性短语扩展规则，未调用模型",
            }
            return state

        return self._with_trace(state, "任务拆解", "qwen", run)

    def _query_profile_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        规则型查询画像节点。

        参数:
            state: 当前状态

        返回:
            写入 query_profile 的状态
        """

        def run() -> RetrievalGraphState:
            profile = self.query_profile_service.build_profile(
                state["question"],
                intent=state.get("intent"),
                sub_queries=state.get("sub_queries", []),
                run_id=state.get("raw", {}).get("run_id"),
            )
            route_scope = (state.get("route_decision") or {}).get("knowledge_scope")
            if route_scope:
                profile["knowledge_scope"] = route_scope
            if bool(state.get("raw", {}).get("eval_mode")) and state.get("chat_type") == "project_chat":
                original_profile = dict(profile)
                profile.update(
                    {
                        "query_type": "project_qa",
                        "answer_shape": profile.get("answer_shape") or "general",
                        "knowledge_scope": "project",
                        "is_industry_domain": False,
                        "industry_domains": [],
                        "reason": "eval_mode 强制使用评测项目资料范围",
                    }
                )
                state.setdefault("raw", {})["eval_original_query_profile"] = original_profile
            state["query_profile"] = profile
            state.setdefault("raw", {})["query_profile"] = profile
            state.setdefault("model_routes", {})["query_profile"] = {
                "task": "query_profile",
                "source": "rules",
                "reason": "查询画像使用确定性规则生成，未调用模型",
            }
            return state

        return self._with_trace(state, "查询画像生成", "query_profile", run)

    def _question_understanding_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        QuestionUnderstanding 节点。

        仅生成新问题理解结构并写入日志/状态，不覆盖旧 intent 或 query_profile。
        """

        def run() -> RetrievalGraphState:
            user = state.get("user")
            understanding = self.question_understanding_service.understand(
                state["question"],
                chat_type=str(state.get("chat_type") or "base_chat"),
                project_id=state.get("project_id"),
                user_id=getattr(user, "id", None),
                intent=state.get("intent"),
                query_profile=state.get("query_profile", {}),
            ).to_dict()
            state["question_understanding"] = understanding
            state.setdefault("raw", {})["question_understanding"] = understanding
            state.setdefault("model_routes", {})["question_understanding"] = {
                "task": "question_understanding",
                "source": "rules",
                "reason": "QuestionUnderstanding 本阶段使用规则生成，未调用模型",
            }
            logger.info(
                "question_understanding=%s run_id=%s task_type=%s answer_shape=%s retrieval_needs=%s query_rewrites=%s confidence=%s reason=%s",
                self._clip(str(understanding), 1600),
                state.get("raw", {}).get("run_id"),
                understanding.get("task_type"),
                understanding.get("answer_shape"),
                understanding.get("retrieval_needs"),
                understanding.get("query_rewrites"),
                understanding.get("confidence"),
                understanding.get("reason"),
            )
            return state

        return self._with_trace(state, "问题理解生成", "question_understanding", run)

    def _policy_resolution_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        PolicyResolver 节点。

        解析最终策略字段供后续模块读取；本阶段不回写旧主控字段，避免改变 RAG 行为。
        """

        def run() -> RetrievalGraphState:
            user = state.get("user")
            resolution = self.policy_resolver.resolve(
                chat_type=str(state.get("chat_type") or "base_chat"),
                project_id=state.get("project_id"),
                user_id=getattr(user, "id", None),
                intent=state.get("intent"),
                query_profile=state.get("query_profile", {}),
                question_understanding=state.get("question_understanding", {}),
            ).to_dict()
            state["policy_resolution"] = resolution
            state["resolved_task_type"] = str(resolution.get("resolved_task_type") or "")
            state["resolved_answer_shape"] = str(resolution.get("resolved_answer_shape") or "")
            state["resolved_answer_policy"] = str(resolution.get("answer_policy") or "")
            state["resolved_knowledge_scope"] = str(resolution.get("knowledge_scope") or "")
            state["answer_policy"] = state["resolved_answer_policy"]
            raw = state.setdefault("raw", {})
            raw["policy_resolution"] = resolution
            raw["resolved_task_type"] = state["resolved_task_type"]
            raw["resolved_answer_shape"] = state["resolved_answer_shape"]
            raw["resolved_answer_policy"] = state["resolved_answer_policy"]
            raw["resolved_knowledge_scope"] = state["resolved_knowledge_scope"]
            raw["answer_policy"] = state["answer_policy"]
            state.setdefault("model_routes", {})["policy_resolution"] = {
                "task": "policy_resolution",
                "source": "rules",
                "reason": "PolicyResolver 使用规则解决 intent/query_profile/QuestionUnderstanding 冲突",
            }
            logger.info(
                "policy_resolution=%s run_id=%s original_intent=%s query_profile_task_type=%s question_understanding_task_type=%s resolved_task_type=%s answer_policy=%s knowledge_scope=%s conflict_detected=%s conflict_reason=%s resolution_rule=%s",
                self._clip(str(resolution), 1600),
                state.get("raw", {}).get("run_id"),
                resolution.get("original_intent"),
                resolution.get("query_profile_task_type"),
                resolution.get("question_understanding_task_type"),
                resolution.get("resolved_task_type"),
                resolution.get("answer_policy"),
                resolution.get("knowledge_scope"),
                resolution.get("conflict_detected"),
                resolution.get("conflict_reason"),
                resolution.get("resolution_rule"),
            )
            return state

        return self._with_trace(state, "策略解析", "policy_resolution", run)

    def _planner_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        Retrieval Planner 节点。

        参数:
            state: 当前状态

        返回:
            写入 retrieval_plan 和 query_features 的状态
        """

        def run() -> RetrievalGraphState:
            available_retrievers = self.retrieval_router.available_retrievers()
            plan = self.planner.plan(
                query=state["question"],
                sub_queries=state.get("sub_queries", [state["question"]]),
                intent=state.get("intent", "knowledge_qa"),
                chat_type=state["chat_type"],
                mode=state["mode"],
                project_id=state["project_id"],
                available_retrievers=available_retrievers,
                query_profile=state.get("query_profile", {}),
                retrieval_mode=self._retrieval_mode(state),
                policy_resolution=state.get("policy_resolution", {}),
                question_understanding=state.get("question_understanding", {}),
            )
            plan_dict = self._enforce_default_hybrid_plan(
                plan.to_dict(),
                available_retrievers,
                self._retrieval_mode(state),
                plan.query_features,
            )
            state["retrieval_plan"] = plan_dict
            state["query_features"] = plan.query_features
            state["planned_retrievers"] = list(plan_dict.get("selected_retrievers", []))
            state["skipped_retrievers"] = list(plan_dict.get("skipped_retrievers", []))
            state["skip_reasons"] = dict(plan_dict.get("skip_reasons", {}))
            state["fallback_ladder"] = list(plan_dict.get("fallback_ladder", []))
            state.setdefault("raw", {})["retrieval_plan"] = plan_dict
            state["raw"]["query_features"] = plan.query_features
            state["raw"]["planned_retrievers"] = state["planned_retrievers"]
            state["raw"]["skipped_retrievers"] = state["skipped_retrievers"]
            state["raw"]["fallback_ladder"] = state["fallback_ladder"]
            state["raw"]["retrieval_mode"] = self._retrieval_mode(state)
            state.setdefault("model_routes", {})["planner"] = plan.metadata.get("model_route", {})
            logger.info(
                "Retrieval Planner完成: run_id=%s step=retrieval_planner implementation=%s status=success intent=%s resolved_task_type=%s rule_id=%s query_features=%s selected_retrievers=%s skipped_retrievers=%s skip_reasons=%s fallback_ladder=%s query_rewrites=%s retrieval_needs=%s confidence=%s qwen_used=%s",
                state.get("raw", {}).get("run_id"),
                plan.strategy,
                state.get("intent"),
                plan_dict.get("resolved_task_type"),
                plan.rule_id,
                self._clip(str(plan.query_features), 1200),
                state["planned_retrievers"],
                state["skipped_retrievers"],
                self._clip(str(state["skip_reasons"]), 1200),
                state["fallback_ladder"],
                plan_dict.get("query_rewrites") or plan_dict.get("query_rewrite"),
                plan_dict.get("retrieval_needs"),
                plan.confidence,
                plan.qwen_used,
            )
            return state

        return self._with_trace(state, "数据检索规划", "planner", run)

    def _retrieval_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        按计划执行多路检索，并在图层只做一次统一重排。

        参数:
            state: 当前状态

        返回:
            写入 evidence、fallback 结果和 trace 摘要的状态
        """

        def run() -> RetrievalGraphState:
            evidence_groups: list[list[Evidence]] = []
            used_retrievers: list[str] = []
            skipped_retrievers: list[str] = []
            fallback_used: list[str] = []
            fallback_trigger_reason: list[dict[str, Any]] = []
            retrieval_sub_queries: list[dict[str, Any]] = []
            query_scope = ""
            effective_mode = state["mode"]
            retriever_hits: dict[str, int] = {}
            retriever_elapsed: dict[str, int] = {}
            retriever_top_scores: dict[str, float] = {}
            skip_reasons: dict[str, str] = dict(state.get("skip_reasons", {}))

            plan = state.get("retrieval_plan") or {
                "selected_retrievers": ["page_index"],
                "fallback_retrievers": ["keyword"],
                "fallback_ladder": [["page_index"], ["keyword"]],
                "reason": "缺少 Planner 结果，使用保底计划",
                "confidence": 0.0,
                "qwen_used": False,
                "strategy": "rules",
                "rule_id": "fallback",
                "skipped_retrievers": [],
                "skip_reasons": {},
                "query_features": {},
            }
            planned_retrievers = list(plan.get("selected_retrievers", []))
            fallback_retrievers = list(plan.get("fallback_retrievers", ["keyword"]))
            fallback_ladder = list(plan.get("fallback_ladder", []))
            effective_task_type = str(state.get("resolved_task_type") or state.get("intent") or "")
            knowledge_scope = str(state.get("resolved_knowledge_scope") or (state.get("query_profile") or {}).get("knowledge_scope") or "")
            self._ensure_retrieval_clock(state)
            max_sub_queries = 1 if effective_task_type == "project_overview" else self._max_sub_queries(state)
            sub_queries = state.get("sub_queries", [state["question"]])[:max_sub_queries]
            candidate_k = self._candidate_k(state)
            rerank_top_k = self._rerank_top_k(state)
            eval_top_k = self._eval_top_k(state)
            merge_limit = FUSED_EVIDENCE_TOP_K
            retriever_timeouts: dict[str, bool] = {}

            for sub_query_index, sub_query in enumerate(sub_queries, start=1):
                remaining_budget_ms = self._remaining_retrieval_budget_ms(state)
                if remaining_budget_ms is not None and remaining_budget_ms <= 0:
                    state.setdefault("raw", {})["retrieval_budget_exhausted"] = True
                    break
                logger.info(
                    "LangGraph子查询开始: run_id=%s step=retrieval implementation=router status=started intent=%s sub_query_index=%s sub_query_total=%s query=%s planned_retrievers=%s fallback_ladder=%s",
                    state.get("raw", {}).get("run_id"),
                    effective_task_type or state.get("intent"),
                    sub_query_index,
                    len(sub_queries),
                    self._clip(sub_query, 300),
                    planned_retrievers,
                    fallback_ladder,
                )
                retrieval = self.retrieval_router.execute_planned(
                    query=sub_query,
                    mode=state["mode"],
                    project_id=state["project_id"],
                    user=state["user"],
                    retriever_names=planned_retrievers,
                    limit=candidate_k,
                    chat_type=state["chat_type"],
                    fallback_retrievers=fallback_retrievers,
                    fallback_ladder=fallback_ladder,
                    query_features=state.get("query_features", {}),
                    skip_reasons=skip_reasons,
                    run_id=state.get("raw", {}).get("run_id"),
                    intent=effective_task_type or state.get("intent"),
                    sub_query_index=sub_query_index,
                    sub_query_total=len(sub_queries),
                    knowledge_scope=knowledge_scope,
                    remaining_budget_ms=remaining_budget_ms,
                    min_stage_budget_ms=self._min_stage_budget_ms(state),
                )
                evidence_groups.append(retrieval["evidences"])
                used_retrievers.extend(retrieval["used_retrievers"])
                skipped_retrievers.extend(retrieval.get("skipped_retrievers", []))
                fallback_used.extend(retrieval.get("fallback_used", []))
                fallback_trigger_reason.extend(retrieval.get("fallback_trigger_reason", []))
                query_scope = retrieval["query_scope"]
                effective_mode = retrieval["mode"]
                for name, count in retrieval.get("retriever_hits", {}).items():
                    retriever_hits[name] = retriever_hits.get(name, 0) + int(count)
                for name, elapsed_ms in retrieval.get("retriever_elapsed_ms", {}).items():
                    retriever_elapsed[name] = retriever_elapsed.get(name, 0) + int(elapsed_ms)
                for name, top_score in retrieval.get("retriever_top_scores", {}).items():
                    retriever_top_scores[name] = max(retriever_top_scores.get(name, 0.0), float(top_score))
                for name, timed_out in retrieval.get("retriever_timeouts", {}).items():
                    retriever_timeouts[name] = retriever_timeouts.get(name, False) or bool(timed_out)
                for name, reason in retrieval.get("skip_reasons", {}).items():
                    skip_reasons.setdefault(name, reason)
                retrieval_sub_queries.append(
                    {
                        "sub_query_index": sub_query_index,
                        "query": self._clip(sub_query, 300),
                        "execution_elapsed_ms": int(retrieval.get("execution_elapsed_ms") or 0),
                        "candidate_evidence_count": len(retrieval.get("evidences", [])),
                        "executed_retrievers": retrieval.get("executed_retrievers", []),
                        "skipped_retrievers": retrieval.get("skipped_retrievers", []),
                        "retriever_hits": retrieval.get("retriever_hits", {}),
                        "retriever_elapsed_ms": retrieval.get("retriever_elapsed_ms", {}),
                        "fallback_used": retrieval.get("fallback_used", []),
                        "fallback_trigger_reason": retrieval.get("fallback_trigger_reason", []),
                        "retriever_timeouts": retrieval.get("retriever_timeouts", {}),
                    }
                )

                logger.info(
                    "LangGraph子查询完成: run_id=%s step=retrieval implementation=router status=success intent=%s sub_query_index=%s sub_query_total=%s query=%s execution_elapsed_ms=%s executed_retrievers=%s skipped_retrievers=%s fallback_used=%s fallback_trigger_reason=%s retriever_hits=%s retriever_elapsed_ms=%s",
                    state.get("raw", {}).get("run_id"),
                    effective_task_type or state.get("intent"),
                    sub_query_index,
                    len(sub_queries),
                    self._clip(sub_query, 300),
                    retrieval.get("execution_elapsed_ms", 0),
                    retrieval.get("executed_retrievers", []),
                    retrieval.get("skipped_retrievers", []),
                    retrieval.get("fallback_used", []),
                    self._clip(str(retrieval.get("fallback_trigger_reason", [])), 1200),
                    retrieval.get("retriever_hits", {}),
                    retrieval.get("retriever_elapsed_ms", {}),
                )

            merged = self._top_scored_evidences(self.merger.merge(evidence_groups, merge_limit), merge_limit)
            rerank_candidates = self._top_scored_evidences(merged, rerank_top_k)
            pre_rerank_guard = self.evidence_access_guard.filter_evidences(
                evidences=rerank_candidates,
                chat_type=str(state.get("chat_type") or ""),
                project_id=state.get("project_id"),
                user=state.get("user"),
                audit_action="RAG证据权限过滤",
            )
            rerank_candidates = self._top_scored_evidences(pre_rerank_guard.evidences, rerank_top_k)
            raw_before_doc_ids = [self._evidence_debug_id(evidence) for evidence in rerank_candidates]
            raw_before_scores = [float(evidence.score) for evidence in rerank_candidates]
            rerank_started_at = time.perf_counter()
            evidences = self._rerank_evidences(state, rerank_candidates, eval_top_k)
            rerank_elapsed_ms = int((time.perf_counter() - rerank_started_at) * 1000)
            evidences = self._top_scored_evidences(evidences, eval_top_k)
            metadata_evidence_count = sum(1 for evidence in evidences if evidence.metadata.get("metadata_only"))
            if metadata_evidence_count:
                evidences = [evidence for evidence in evidences if not evidence.metadata.get("metadata_only")]
                evidences = self._top_scored_evidences(evidences, eval_top_k)
            evidences = self.visual_evidence_service.enrich(
                state["question"],
                evidences,
                self._visual_query_context(state),
            )
            evidences = self._top_scored_evidences(evidences, VISUAL_EVIDENCE_TOP_K)
            visual_asset_count = sum(len(evidence.assets) for evidence in evidences)
            logger.info(
                "LangGraph检索重排完成: run_id=%s merged_count=%s final_count=%s rerank=%s final_evidence=%s",
                state.get("raw", {}).get("run_id"),
                len(merged),
                len(evidences),
                self._clip(str(self.reranker.last_details), 1200),
                self._evidence_log_summary(evidences),
            )
            final_executed_retrievers = list(dict.fromkeys(used_retrievers))
            final_skipped_retrievers = [
                name for name in list(dict.fromkeys(skipped_retrievers)) if name not in final_executed_retrievers
            ]
            filtered_skip_reasons = {
                name: reason for name, reason in skip_reasons.items() if name in final_skipped_retrievers
            }

            state["mode"] = effective_mode
            state["query_scope"] = query_scope
            state["used_retrievers"] = final_executed_retrievers
            state["executed_retrievers"] = final_executed_retrievers
            state["skipped_retrievers"] = final_skipped_retrievers
            state["skip_reasons"] = filtered_skip_reasons
            state["fallback_ladder"] = fallback_ladder
            state["fallback_used"] = list(dict.fromkeys(fallback_used))
            state["fallback_trigger_reason"] = fallback_trigger_reason
            state["retriever_hits"] = retriever_hits
            state["retriever_elapsed_ms"] = retriever_elapsed
            state["retriever_top_scores"] = retriever_top_scores
            state["rerank_details"] = self.reranker.last_details
            state["evidences"] = evidences
            state["visual_asset_count"] = visual_asset_count
            state.setdefault("raw", {})["query_features"] = state.get("query_features", {})
            state["raw"]["planned_retrievers"] = planned_retrievers
            state["raw"]["executed_retrievers"] = state["executed_retrievers"]
            state["raw"]["skipped_retrievers"] = state["skipped_retrievers"]
            state["raw"]["skip_reasons"] = state["skip_reasons"]
            state["raw"]["raw_skip_reasons"] = skip_reasons
            state["raw"]["fallback_ladder"] = fallback_ladder
            state["raw"]["fallback_used"] = state["fallback_used"]
            state["raw"]["fallback_trigger_reason"] = fallback_trigger_reason
            state["raw"]["retriever_hits"] = retriever_hits
            state["raw"]["retriever_elapsed_ms"] = retriever_elapsed
            state["raw"]["retriever_top_scores"] = retriever_top_scores
            state["raw"]["retriever_timeouts"] = retriever_timeouts
            state["raw"]["retrieval_sub_queries"] = retrieval_sub_queries
            state["raw"]["retrieval_limit"] = candidate_k
            state["raw"]["candidate_k"] = candidate_k
            state["raw"]["rerank_top_k"] = rerank_top_k
            state["raw"]["eval_top_k"] = eval_top_k
            state["raw"]["fused_evidence_top_k"] = merge_limit
            state["raw"]["visual_evidence_top_k"] = VISUAL_EVIDENCE_TOP_K
            state["raw"]["retrieval_before_rerank_doc_ids"] = raw_before_doc_ids
            state["raw"]["retrieval_before_rerank_scores"] = raw_before_scores
            state["raw"]["pre_rerank_evidence_guard"] = pre_rerank_guard.to_dict()
            state["raw"]["rerank_after_doc_ids"] = [self._evidence_debug_id(evidence) for evidence in evidences]
            state["raw"]["rerank_after_scores"] = [float(evidence.score) for evidence in evidences]
            state["raw"]["reranker_runtime"] = getattr(self.reranker, "last_runtime", {})
            state["raw"]["rerank_elapsed_ms"] = rerank_elapsed_ms
            state["raw"]["metadata_evidence_filtered_count"] = metadata_evidence_count
            state["raw"]["visual_asset_count"] = visual_asset_count
            return state

        return self._with_trace(state, "检索召回与数据组装", "router+reranker", run)

    def _evidence_judge_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        Qwen 证据判断节点。

        参数:
            state: 当前状态

        返回:
            写入 evidence_judgement 的状态
        """

        def run() -> RetrievalGraphState:
            state["evidences"] = self._sanitize_evidences(state, list(state.get("evidences", [])))
            raw = state.setdefault("raw", {})
            eval_top_k = self._eval_top_k(state)
            before_evidences = self._top_scored_evidences(list(state.get("evidences", [])), eval_top_k)
            raw["evidence_before_judge_doc_ids"] = [self._evidence_debug_id(evidence) for evidence in before_evidences]
            if bool(raw.get("eval_mode")) or self._retrieval_mode(state) in {"fast", "smart"}:
                state["evidences"] = self._top_scored_evidences(list(state.get("evidences", [])), eval_top_k)
                state["evidence_judgement"] = {
                    "enough": True,
                    "reason": "lightweight_evidence_filter",
                    "source": "lightweight",
                    "llm_called": False,
                    "evidence_count": len(state.get("evidences", [])),
                }
                raw["evidence_judgement"] = state["evidence_judgement"]
                raw["evidence_after_judge_doc_ids"] = [self._evidence_debug_id(evidence) for evidence in state.get("evidences", [])]
                self._record_answer_context(state)
                raw["evidence_judge_elapsed_ms"] = 0
                raw["llm_evidence_judge_ms"] = 0
                raw["lightweight_filter_ms"] = 0
                state.setdefault("model_routes", {})["evidence_judge"] = {
                    "task": "evidence_judge",
                    "source": "lightweight",
                    "reason": "BEIR/fast/smart evaluation uses non-LLM evidence filter",
                }
                return state
            judge_started_at = time.perf_counter()
            state["evidences"] = self._sanitize_evidences(state, list(state.get("evidences", [])))
            state["evidence_judgement"] = self.qwen.judge_evidence(
                state["question"],
                state.get("evidences", []),
                {
                    "retriever_hits": state.get("retriever_hits", {}),
                    "query_features": state.get("query_features", {}),
                    "query_profile": state.get("query_profile", {}),
                    "visual_asset_count": state.get("visual_asset_count", 0),
                },
            )
            evidence_judge_elapsed_ms = int((time.perf_counter() - judge_started_at) * 1000)
            state["evidences"] = self._top_scored_evidences(list(state.get("evidences", [])), eval_top_k)
            raw["evidence_judgement"] = state["evidence_judgement"]
            raw["evidence_after_judge_doc_ids"] = [self._evidence_debug_id(evidence) for evidence in state.get("evidences", [])]
            self._record_answer_context(state)
            evidence_route = self.qwen.model_routes.get("evidence_judge", {})
            state.setdefault("model_routes", {})["evidence_judge"] = evidence_route
            evidence_route_source = str(evidence_route.get("source") or "").strip().lower()
            raw["evidence_judge_elapsed_ms"] = evidence_judge_elapsed_ms
            raw["llm_evidence_judge_ms"] = (
                0
                if evidence_route_source in {"", "rules", "rules_fallback", "rules_fast_path", "lightweight", "not_called"}
                else evidence_judge_elapsed_ms
            )
            raw["lightweight_filter_ms"] = 0
            return state

        return self._with_trace(state, "资料证据有效性判断", "qwen", run)

    def _retry_retrieval_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        证据不足时执行最多一次补充检索。

        参数:
            state: 当前状态

        返回:
            写入 retry 结果和最终 evidence_judgement 的状态
        """

        def run() -> RetrievalGraphState:
            judgement = state.get("evidence_judgement", {}) or {}
            raw = state.setdefault("raw", {})
            retry_count = int(raw.get("retry_count", 0) or 0)
            pre_retry_evaluation = self.evidence_evaluator.evaluate(
                question=state["question"],
                evidences=list(state.get("evidences", [])),
                judgement=judgement,
                resolved_task_type=state.get("resolved_task_type"),
                answer_shape=state.get("resolved_answer_shape"),
                query_profile=state.get("query_profile", {}),
            ).to_dict()
            pre_retry_status = str(pre_retry_evaluation.get("evidence_status") or EVIDENCE_EMPTY)
            raw["pre_retry_evidence_status"] = pre_retry_status
            raw["pre_retry_evidence_evaluation"] = pre_retry_evaluation
            if self._should_skip_retry_for_visual_partial(state, pre_retry_evaluation):
                raw.setdefault("max_retry", 1)
                raw["retry_count"] = retry_count
                raw["retry_allowed"] = False
                raw["retry_skipped_reason"] = "VISUAL_PARTIAL_ANSWER_READY"
                logger.info(
                    "Retry跳过: run_id=%s reason=%s visual_asset_count=%s strong=%s answerable_parts=%s",
                    raw.get("run_id"),
                    raw["retry_skipped_reason"],
                    state.get("visual_asset_count", 0),
                    pre_retry_evaluation.get("strong_evidence_count"),
                    pre_retry_evaluation.get("answerable_parts"),
                )
                return state
            if self._should_skip_retry_for_structured_list_partial(state, pre_retry_evaluation):
                raw.setdefault("max_retry", 1)
                raw["retry_count"] = retry_count
                raw["retry_allowed"] = False
                raw["retry_skipped_reason"] = "STRUCTURED_LIST_ROWS_READY"
                logger.info(
                    "Retry跳过: run_id=%s reason=%s dominant_row_doc_ids=%s",
                    raw.get("run_id"),
                    raw["retry_skipped_reason"],
                    [self._evidence_debug_id(evidence) for evidence in state.get("evidences", [])[:6]],
                )
                return state
            retry_skip_reason = self._retry_skip_reason(
                state,
                judgement,
                retry_count,
                pre_retry_status,
                pre_retry_evaluation,
            )
            if retry_skip_reason:
                raw.setdefault("max_retry", 1)
                raw["retry_count"] = retry_count
                raw["retry_allowed"] = False
                raw["retry_skipped_reason"] = retry_skip_reason
                logger.info(
                    "Retry跳过: run_id=%s reason=%s intent_type=%s answer_policy=%s evidence_count=%s",
                    raw.get("run_id"),
                    retry_skip_reason,
                    state.get("intent_type"),
                    state.get("answer_policy"),
                    len(state.get("evidences", [])),
                )
                return state
            if bool(raw.get("eval_mode")):
                raw.setdefault("max_retry", 1)
                raw["retry_count"] = retry_count
                raw["retry_skipped_reason"] = "eval_mode"
                logger.info(
                    "LangGraph eval模式跳过证据补充检索: run_id=%s evidence_enough=%s evidence_count=%s",
                    raw.get("run_id"),
                    judgement.get("enough"),
                    len(state.get("evidences", [])),
                )
                return state
            if pre_retry_status == EVIDENCE_ENOUGH or retry_count >= 1:
                raw.setdefault("max_retry", 1)
                raw.setdefault("retry_count", retry_count)
                raw.setdefault("retry_skipped_reason", "evidence_enough_or_retry_limit")
                raw["retry_allowed"] = False
                return state
            self._ensure_retry_clock(state)
            retry_budget_ms = self._effective_retry_budget_ms(state)
            min_retry_budget_ms = self._min_retry_budget_ms(state)
            if retry_budget_ms is not None and retry_budget_ms <= 0:
                raw.setdefault("max_retry", 1)
                raw["retry_count"] = retry_count
                raw["retry_allowed"] = False
                raw["retry_skipped_reason"] = "BUDGET_EXHAUSTED"
                return state
            if retry_budget_ms is not None and retry_budget_ms < min_retry_budget_ms:
                raw.setdefault("max_retry", 1)
                raw["retry_count"] = retry_count
                raw["retry_allowed"] = False
                raw["retry_skipped_reason"] = "BUDGET_TOO_LOW"
                return state

            retry_scope = self._retry_scope_from_evidences(state)
            raw["retry_scope"] = retry_scope
            raw["retry_scope_document_ids"] = retry_scope.get("document_ids", [])
            raw["retry_scope_page_numbers_by_document"] = retry_scope.get("page_numbers_by_document", {})
            raw["retry_scope_chunk_ids"] = retry_scope.get("chunk_ids", [])

            retry_retrievers, retry_queries, retry_reason = self._retry_strategy_for_status(
                pre_retry_status,
                judgement,
                state,
            )
            if not retry_retrievers or not retry_queries:
                raw.setdefault("max_retry", 1)
                raw["retry_count"] = retry_count
                raw["retry_skipped_reason"] = "missing_retry_retrievers_or_queries"
                raw["retry_allowed"] = False
                return state
            if (
                pre_retry_status in {EVIDENCE_WEAK_ONLY, EVIDENCE_PARTIAL}
                and not retrieval_scope_has_filters(retry_scope)
                and not self._has_retry_signal(judgement)
            ):
                raw.setdefault("max_retry", 1)
                raw["retry_count"] = retry_count
                raw["retry_skipped_reason"] = "NO_SCOPE_HINT"
                raw["retry_allowed"] = False
                return state

            raw["max_retry"] = 1
            raw["retry_count"] = retry_count + 1
            raw["retry_allowed"] = True
            raw["retry_reason"] = retry_reason
            raw["retry_retrievers"] = retry_retrievers
            raw["retry_queries"] = retry_queries
            raw["retry_query_count"] = len(retry_queries)
            raw["retry_fallback_ladder"] = self._retry_execution_ladder(retry_retrievers)
            raw["retry_budget_ms"] = retry_budget_ms
            raw["retry_min_budget_ms"] = min_retry_budget_ms
            logger.info(
                "Retry retrieval plan: run_id=%s retry_scope_document_ids=%s retry_scope_pages=%s retry_ladder=%s retry_queries=%s",
                raw.get("run_id"),
                raw["retry_scope_document_ids"],
                raw["retry_scope_page_numbers_by_document"],
                raw["retry_fallback_ladder"],
                [self._clip(query, 160) for query in retry_queries],
            )
            logger.info(
                "LangGraph证据不足补充检索开始: run_id=%s retry_reason=%s retry_retrievers=%s retry_query_count=%s",
                raw.get("run_id"),
                self._clip(str(raw["retry_reason"]), 300),
                retry_retrievers,
                len(retry_queries),
            )

            retry_groups: list[list[Evidence]] = []
            retry_hits: dict[str, int] = {}
            retry_elapsed: dict[str, int] = {}
            retry_top_scores: dict[str, float] = {}
            retry_retriever_timeouts: dict[str, bool] = {}
            retry_executed: list[str] = []
            retry_skipped: list[str] = []
            retry_skip_reasons: dict[str, str] = {}
            retry_budget_stop_reason: str | None = None
            retry_query_details: list[dict[str, Any]] = []
            query_scope = state.get("query_scope") or ""
            effective_mode = state["mode"]
            retrieval_limit = self._candidate_k(state)
            retry_rerank_top_k = self._rerank_top_k(state)
            merge_limit = FUSED_EVIDENCE_TOP_K
            retry_fallback_ladder = self._retry_execution_ladder(retry_retrievers)

            for index, retry_query in enumerate(retry_queries, start=1):
                remaining_retry_budget_ms = self._effective_retry_budget_ms(state)
                if remaining_retry_budget_ms is not None and remaining_retry_budget_ms < min_retry_budget_ms:
                    retry_budget_stop_reason = "budget_exhausted" if remaining_retry_budget_ms <= 0 else "budget_too_low"
                    break
                logger.info(
                    "LangGraph补充检索子查询开始: run_id=%s step=retry_retrieval implementation=router status=started retry_query_index=%s retry_query_total=%s query=%s retry_retrievers=%s remaining_retry_budget_ms=%s",
                    raw.get("run_id"),
                    index,
                    len(retry_queries),
                    self._clip(retry_query, 300),
                    retry_retrievers,
                    remaining_retry_budget_ms,
                )
                retrieval = self.retrieval_router.execute_planned(
                    query=retry_query,
                    mode=state["mode"],
                    project_id=state["project_id"],
                    user=state["user"],
                    retriever_names=retry_retrievers,
                    limit=retrieval_limit,
                    chat_type=state["chat_type"],
                    fallback_retrievers=[],
                    fallback_ladder=retry_fallback_ladder,
                    query_features=state.get("query_features", {}),
                    skip_reasons=state.get("skip_reasons", {}),
                    run_id=raw.get("run_id"),
                    intent=state.get("intent"),
                    sub_query_index=index,
                    sub_query_total=len(retry_queries),
                    knowledge_scope=str((state.get("query_profile") or {}).get("knowledge_scope") or ""),
                    remaining_budget_ms=remaining_retry_budget_ms,
                    min_stage_budget_ms=self._min_stage_budget_ms(state),
                    retrieval_scope=retry_scope,
                )
                retry_groups.append(retrieval.get("evidences", []))
                retry_executed.extend(retrieval.get("executed_retrievers", []))
                retry_skipped.extend(retrieval.get("skipped_retrievers", []))
                query_scope = retrieval.get("query_scope") or query_scope
                effective_mode = retrieval.get("mode") or effective_mode
                for name, count in retrieval.get("retriever_hits", {}).items():
                    retry_hits[name] = retry_hits.get(name, 0) + int(count)
                for name, elapsed_ms in retrieval.get("retriever_elapsed_ms", {}).items():
                    retry_elapsed[name] = retry_elapsed.get(name, 0) + int(elapsed_ms)
                for name, top_score in retrieval.get("retriever_top_scores", {}).items():
                    retry_top_scores[name] = max(retry_top_scores.get(name, 0.0), float(top_score))
                for name, reason in retrieval.get("skip_reasons", {}).items():
                    retry_skip_reasons.setdefault(name, reason)
                for name, timed_out in retrieval.get("retriever_timeouts", {}).items():
                    retry_retriever_timeouts[name] = retry_retriever_timeouts.get(name, False) or bool(timed_out)
                retry_query_details.append(
                    {
                        "retry_query_index": index,
                        "query": self._clip(retry_query, 300),
                        "execution_elapsed_ms": int(retrieval.get("execution_elapsed_ms") or 0),
                        "candidate_evidence_count": len(retrieval.get("evidences", [])),
                        "executed_retrievers": retrieval.get("executed_retrievers", []),
                        "skipped_retrievers": retrieval.get("skipped_retrievers", []),
                        "retriever_hits": retrieval.get("retriever_hits", {}),
                        "retriever_elapsed_ms": retrieval.get("retriever_elapsed_ms", {}),
                        "retrieval_scope": retrieval.get("retrieval_scope", {}),
                        "fallback_trigger_reason": retrieval.get("fallback_trigger_reason", []),
                        "retriever_timeouts": retrieval.get("retriever_timeouts", {}),
                    }
                )
                logger.info(
                    "LangGraph补充检索子查询完成: run_id=%s step=retry_retrieval implementation=router status=success retry_query_index=%s retry_query_total=%s query=%s execution_elapsed_ms=%s executed_retrievers=%s skipped_retrievers=%s retriever_hits=%s retriever_elapsed_ms=%s",
                    raw.get("run_id"),
                    index,
                    len(retry_queries),
                    self._clip(retry_query, 300),
                    retrieval.get("execution_elapsed_ms", 0),
                    retrieval.get("executed_retrievers", []),
                    retrieval.get("skipped_retrievers", []),
                    retrieval.get("retriever_hits", {}),
                    retrieval.get("retriever_elapsed_ms", {}),
                )

            retry_new_evidence_count = self._retry_added_value_count(list(state.get("evidences", [])), retry_groups)
            merged = self._top_scored_evidences(
                self._merge_evidences_by_source([state.get("evidences", []), *retry_groups], merge_limit),
                merge_limit,
            )
            rerank_started_at = time.perf_counter()
            evidences = self._rerank_evidences(
                state,
                self._top_scored_evidences(merged, retry_rerank_top_k),
                self._eval_top_k(state),
            )
            retry_rerank_elapsed_ms = int((time.perf_counter() - rerank_started_at) * 1000)
            evidences = self._top_scored_evidences(evidences, self._eval_top_k(state))
            evidences = self.visual_evidence_service.enrich(
                state["question"],
                evidences,
                self._visual_query_context(state),
            )
            evidences = self._top_scored_evidences(evidences, VISUAL_EVIDENCE_TOP_K)
            visual_asset_count = sum(len(evidence.assets) for evidence in evidences)

            state["mode"] = effective_mode
            state["query_scope"] = query_scope
            state["evidences"] = evidences
            state["visual_asset_count"] = visual_asset_count
            state["rerank_details"] = self.reranker.last_details
            state["used_retrievers"] = list(dict.fromkeys([*state.get("used_retrievers", []), *retry_executed]))
            state["executed_retrievers"] = list(dict.fromkeys([*state.get("executed_retrievers", []), *retry_executed]))
            state["skipped_retrievers"] = [
                name
                for name in list(dict.fromkeys([*state.get("skipped_retrievers", []), *retry_skipped]))
                if name not in state["executed_retrievers"]
            ]
            merged_skip_reasons = {**state.get("skip_reasons", {}), **retry_skip_reasons}
            state["skip_reasons"] = {
                name: reason for name, reason in merged_skip_reasons.items() if name in state["skipped_retrievers"]
            }
            for name, count in retry_hits.items():
                state.setdefault("retriever_hits", {})[name] = state.get("retriever_hits", {}).get(name, 0) + count
            for name, elapsed_ms in retry_elapsed.items():
                state.setdefault("retriever_elapsed_ms", {})[name] = (
                    state.get("retriever_elapsed_ms", {}).get(name, 0) + elapsed_ms
                )
            for name, top_score in retry_top_scores.items():
                state.setdefault("retriever_top_scores", {})[name] = max(
                    state.get("retriever_top_scores", {}).get(name, 0.0),
                    top_score,
                )

            retry_judge_started_at = time.perf_counter()
            state["evidences"] = self._sanitize_evidences(state, list(state.get("evidences", [])))
            state["evidence_judgement"] = self.qwen.judge_evidence(
                state["question"],
                state.get("evidences", []),
                {
                    "retriever_hits": state.get("retriever_hits", {}),
                    "query_features": state.get("query_features", {}),
                    "query_profile": state.get("query_profile", {}),
                    "visual_asset_count": state.get("visual_asset_count", 0),
                    "retry_count": raw["retry_count"],
                },
            )
            retry_evidence_judge_elapsed_ms = int((time.perf_counter() - retry_judge_started_at) * 1000)
            retry_evidence_route = self.qwen.model_routes.get("evidence_judge", {})
            state.setdefault("model_routes", {})["evidence_judge_retry"] = retry_evidence_route
            state["model_routes"]["evidence_judge"] = retry_evidence_route
            retry_evidence_route_source = str(retry_evidence_route.get("source") or "").strip().lower()

            raw["retry_hits"] = retry_hits
            raw["retry_elapsed_ms"] = retry_elapsed
            raw["retry_top_scores"] = retry_top_scores
            raw["retry_retriever_timeouts"] = retry_retriever_timeouts
            raw["retry_query_details"] = retry_query_details
            raw["retry_new_evidence_count"] = retry_new_evidence_count
            raw["retry_added_value"] = retry_new_evidence_count > 0
            raw["retry_budget_exhausted"] = retry_budget_stop_reason == "budget_exhausted"
            raw["retry_budget_stop_reason"] = retry_budget_stop_reason
            raw["retry_executed_retrievers"] = list(dict.fromkeys(retry_executed))
            raw["executed_retrievers"] = state["executed_retrievers"]
            raw["skipped_retrievers"] = state["skipped_retrievers"]
            raw["skip_reasons"] = state["skip_reasons"]
            raw["retriever_hits"] = state.get("retriever_hits", {})
            raw["retriever_elapsed_ms"] = state.get("retriever_elapsed_ms", {})
            raw["retriever_top_scores"] = state.get("retriever_top_scores", {})
            raw["rerank_details"] = state.get("rerank_details", [])
            raw["retry_rerank_elapsed_ms"] = retry_rerank_elapsed_ms
            raw["retry_retrieval_limit"] = retrieval_limit
            raw["retry_fused_evidence_top_k"] = merge_limit
            raw["retry_rerank_top_k"] = retry_rerank_top_k
            raw["visual_evidence_top_k"] = VISUAL_EVIDENCE_TOP_K
            raw["retry_evidence_judge_elapsed_ms"] = retry_evidence_judge_elapsed_ms
            raw["retry_llm_evidence_judge_ms"] = (
                0
                if retry_evidence_route_source in {"", "rules", "rules_fallback", "rules_fast_path", "lightweight", "not_called"}
                else retry_evidence_judge_elapsed_ms
            )
            raw["evidence_judgement"] = state["evidence_judgement"]
            raw["visual_asset_count"] = visual_asset_count
            logger.info(
                "Retry retrieval value: run_id=%s retry_new_evidence_count=%s retry_added_value=%s retry_budget_stop_reason=%s",
                raw.get("run_id"),
                retry_new_evidence_count,
                retry_new_evidence_count > 0,
                retry_budget_stop_reason,
            )
            logger.info(
                "LangGraph证据不足补充检索完成: run_id=%s retry_retrievers=%s retry_query_count=%s final_evidence_count=%s final_enough=%s",
                raw.get("run_id"),
                retry_retrievers,
                len(retry_queries),
                len(evidences),
                state["evidence_judgement"].get("enough"),
            )
            return state

        return self._with_trace(state, "证据不足补充检索", "router+reranker", run)

    def _retry_skip_reason(
        self,
        state: RetrievalGraphState,
        judgement: dict[str, Any],
        retry_count: int,
        evidence_status: str,
        evaluation: dict[str, Any],
    ) -> str | None:
        has_retry_signal = self._has_retry_signal(judgement) or bool(evaluation.get("should_retry"))
        if bool(state.get("raw", {}).get("eval_mode")):
            return None
        if state.get("answer_policy") == ANSWER_POLICY_CLARIFY:
            return "CLARIFY_POLICY"
        if str(state.get("raw", {}).get("query_validity") or "") == "invalid":
            return "INVALID_QUERY"
        if state.get("intent_type") in {"invalid", "invalid_or_noise_query", "ambiguous", "greeting", "bot_identity", "help"}:
            return "NON_RETRIEVAL_INTENT"
        if evidence_status == EVIDENCE_ENOUGH:
            return "EVIDENCE_ENOUGH"
        if evidence_status in {EVIDENCE_WEAK_ONLY, EVIDENCE_PARTIAL} and not has_retry_signal:
            return "LOW_RETRY_SIGNAL"
        if (
            evidence_status == EVIDENCE_EMPTY
            and not has_retry_signal
            and not self._looks_like_exact_lookup_fragment(str(state.get("question") or ""))
        ):
            return "LOW_RETRY_SIGNAL"
        if state.get("intent") == "project_overview":
            return "PROJECT_OVERVIEW_INSUFFICIENT_NO_HEAVY_RETRY"
        if retry_count >= 1:
            return "RETRY_LIMIT"
        return None

    def _should_skip_retry_for_visual_partial(
        self,
        state: RetrievalGraphState,
        evaluation: dict[str, Any],
    ) -> bool:
        """流程图问答已具备可回答的图纸证据时，避免补充检索把延迟放大。"""

        if str(evaluation.get("evidence_status") or EVIDENCE_EMPTY) != EVIDENCE_PARTIAL:
            return False
        if not bool(evaluation.get("allow_limited_answer")):
            return False
        if not self._is_flow_visual_query(state):
            return False
        visual_asset_count = int(state.get("visual_asset_count") or 0)
        if visual_asset_count <= 0 and not any(evidence.assets for evidence in state.get("evidences", [])):
            return False
        strong_count = int(evaluation.get("strong_evidence_count") or 0)
        answerable_parts = evaluation.get("answerable_parts") or []
        return strong_count > 0 or bool(answerable_parts)

    def _evidence_decision_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """将证据判断归一化为答案门控可消费的 evidence_status。"""

        def run() -> RetrievalGraphState:
            evaluation = self.evidence_evaluator.evaluate(
                question=state["question"],
                evidences=list(state.get("evidences", [])),
                judgement=state.get("evidence_judgement", {}) or {},
                resolved_task_type=state.get("resolved_task_type"),
                answer_shape=state.get("resolved_answer_shape"),
                query_profile=state.get("query_profile", {}),
            ).to_dict()
            status = str(evaluation.get("evidence_status") or EVIDENCE_EMPTY)
            state["evidence_status"] = status
            state["evidence_evaluation"] = evaluation
            raw = state.setdefault("raw", {})
            raw["evidence_status"] = status
            raw["evidence_evaluation"] = evaluation
            raw["weak_evidence_count"] = evaluation.get("weak_evidence_count", 0)
            raw["strong_evidence_count"] = evaluation.get("strong_evidence_count", 0)
            raw["missing_aspects"] = evaluation.get("missing_aspects", [])
            raw["should_retry"] = bool(evaluation.get("should_retry"))
            raw["allow_limited_answer"] = bool(evaluation.get("allow_limited_answer"))
            raw["evidence_decision_reason"] = evaluation.get("reason")
            logger.info(
                "evidence_evaluation=%s run_id=%s evidence_status=%s weak=%s strong=%s missing_aspects=%s should_retry=%s allow_limited_answer=%s",
                self._clip(str(evaluation), 1600),
                raw.get("run_id"),
                status,
                evaluation.get("weak_evidence_count"),
                evaluation.get("strong_evidence_count"),
                evaluation.get("missing_aspects"),
                evaluation.get("should_retry"),
                evaluation.get("allow_limited_answer"),
            )
            return state

        return self._with_trace(state, "证据状态判断", "rules", run)

    def _apply_final_evidence_guard(self, state: RetrievalGraphState) -> None:
        """答案门控前二次断言证据权限、项目、审核状态和版本有效性。"""

        raw = state.setdefault("raw", {})
        guard_result = self.evidence_access_guard.filter_evidences(
            evidences=list(state.get("evidences", [])),
            chat_type=str(state.get("chat_type") or ""),
            project_id=state.get("project_id"),
            user=state.get("user"),
            audit_action="AnswerGenerator证据断言失败",
        )
        raw["final_evidence_guard"] = guard_result.to_dict()
        if not guard_result.rejected:
            return

        state["evidences"] = guard_result.evidences
        judgement = dict(state.get("evidence_judgement", {}) or {})
        if not guard_result.evidences:
            judgement.update(
                {
                    "enough": False,
                    "confidence": 0.0,
                    "relevance": "none",
                    "support_level": "none",
                    "conflict": False,
                    "risk": guard_result.risk,
                    "reason": f"最终证据断言剔除全部证据：{guard_result.primary_reason}",
                }
            )
        state["evidence_judgement"] = judgement
        evaluation = self.evidence_evaluator.evaluate(
            question=state["question"],
            evidences=list(state.get("evidences", [])),
            judgement=judgement,
            resolved_task_type=state.get("resolved_task_type"),
            answer_shape=state.get("resolved_answer_shape"),
            query_profile=state.get("query_profile", {}),
        ).to_dict()
        if not guard_result.evidences and guard_result.risk != "none":
            evaluation["risk"] = guard_result.risk
            evaluation["reason"] = f"{evaluation.get('reason') or ''}；最终证据断言：{guard_result.primary_reason}".strip("；")
        status = str(evaluation.get("evidence_status") or EVIDENCE_EMPTY)
        state["evidence_status"] = status
        state["evidence_evaluation"] = evaluation
        raw["evidence_status"] = status
        raw["evidence_evaluation"] = evaluation
        raw["weak_evidence_count"] = evaluation.get("weak_evidence_count", 0)
        raw["strong_evidence_count"] = evaluation.get("strong_evidence_count", 0)
        raw["missing_aspects"] = evaluation.get("missing_aspects", [])
        raw["should_retry"] = bool(evaluation.get("should_retry"))
        raw["allow_limited_answer"] = bool(evaluation.get("allow_limited_answer"))

    def _answer_policy_gate_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """根据答案策略和证据状态决定生成、拒答、反问或澄清。"""

        def run() -> RetrievalGraphState:
            policy = str(state.get("resolved_answer_policy") or state.get("policy_resolution", {}).get("answer_policy") or "")
            evidence_status = str(state.get("evidence_status") or EVIDENCE_EMPTY)
            raw = state.setdefault("raw", {})
            state["need_user_confirm"] = False
            state["pending_action"] = None
            raw["terminal_without_answer_generation"] = False
            raw["answer_policy"] = policy
            raw["evidence_status"] = evidence_status
            raw.setdefault("direct_llm_used", False)
            raw.setdefault("kb_grounded", False)
            raw.setdefault("refused", False)
            raw.setdefault("need_general_confirm", False)

            if policy == ANSWER_POLICY_CLARIFY:
                state["answer"] = self._clarify_answer(state)
                state["answer_type"] = "clarify"
                if str(raw.get("query_validity") or "") == "invalid" or state.get("intent_type") in {"invalid", "invalid_or_noise_query"}:
                    state["evidence_status"] = EVIDENCE_INVALID_QUERY
                    raw["evidence_status"] = EVIDENCE_INVALID_QUERY
                state["evidences"] = []
                raw["terminal_without_answer_generation"] = True
                return state

            self._apply_final_evidence_guard(state)
            evidence_status = str(state.get("evidence_status") or EVIDENCE_EMPTY)
            raw["evidence_status"] = evidence_status

            decision = self.answer_policy_gate.resolve(
                answer_policy=policy,
                evidence_status=evidence_status,
                resolved_task_type=str(state.get("resolved_task_type") or ""),
                answer_shape=str(state.get("resolved_answer_shape") or ""),
                evidence=list(state.get("evidences", [])),
                is_obvious_common_knowledge=self._is_obvious_common_knowledge(state["question"]),
                chat_type=str(state.get("chat_type") or ""),
                intent_type=str(state.get("intent_type") or ""),
                query_profile=state.get("query_profile", {}),
            ).to_dict()
            action = str(decision.get("action") or AnswerAction.REFUSAL.value)
            state["answer_policy"] = policy
            state["answer_policy_action"] = action
            state["answer_policy_decision"] = decision
            raw["answer_policy"] = policy
            raw["answer_policy_action"] = action
            raw["answer_policy_gate"] = decision
            raw["answer_policy_decision"] = decision

            if action in {
                AnswerAction.NORMAL_ANSWER.value,
                AnswerAction.GENERAL_ANSWER.value,
                AnswerAction.PARTIAL_ANSWER_WITH_LLM.value,
            }:
                state["answer_type"] = action
                raw["answer_type"] = action
                return state

            if action == AnswerAction.ASK_GENERAL_CONFIRM.value:
                state["answer"] = BASE_GENERAL_CONFIRM_ANSWER
                state["answer_type"] = action
                state["need_user_confirm"] = True
                state["pending_action"] = "confirm_general_answer"
                state["evidences"] = []
                raw["need_general_confirm"] = True
                raw["terminal_without_answer_generation"] = True
                return state

            state["answer"] = self.answer_generator.generate_by_action(
                state["question"],
                list(state.get("evidences", [])),
                action=action,
                query_profile=state.get("query_profile", {}),
                evidence_evaluation=state.get("evidence_evaluation", {}),
            )
            state["answer_type"] = action
            state.setdefault("model_routes", {})["answer"] = self.answer_generator.last_model_route or {}
            raw["answer_type"] = action
            raw["terminal_without_answer_generation"] = True
            raw["direct_llm_used"] = action in {AnswerAction.GENERAL_ANSWER.value, AnswerAction.PARTIAL_ANSWER_WITH_LLM.value}
            raw["kb_grounded"] = action in {
                AnswerAction.LIMITED_ANSWER.value,
                AnswerAction.PARTIAL_ANSWER.value,
                AnswerAction.PARTIAL_ANSWER_WITH_LLM.value,
                AnswerAction.CONFLICT_ANSWER.value,
            }
            raw["refused"] = action == AnswerAction.REFUSAL.value
            if action == AnswerAction.REFUSAL.value:
                state["evidences"] = []
            logger.info(
                "answer_policy_gate=%s run_id=%s action=%s answer_policy=%s evidence_status=%s",
                self._clip(str(decision), 1200),
                raw.get("run_id"),
                action,
                policy,
                evidence_status,
            )
            return state

        return self._with_trace(state, "答案策略门控", "rules", run)

    def _answer_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        回答生成节点。

        参数:
            state: 当前状态

        返回:
            写入 answer 的状态
        """

        def run() -> RetrievalGraphState:
            if self._is_terminal_without_answer_generation(state):
                return state
            answer_evidences = self._record_answer_context(state)
            action = str(state.get("answer_policy_action") or AnswerAction.NORMAL_ANSWER.value)
            if self.db is None:
                state["answer"] = self.answer_generator.generate_by_action(
                    state["question"],
                    answer_evidences,
                    action=action,
                    query_profile=state.get("query_profile", {}),
                    evidence_evaluation=state.get("evidence_evaluation", {}),
                )
            else:
                state["answer"] = self.answer_generator.generate_by_action(
                    state["question"],
                    answer_evidences,
                    action=action,
                    query_profile=state.get("query_profile", {}),
                    evidence_evaluation=state.get("evidence_evaluation", {}),
                    user=state.get("user"),
                    request_id=state.get("raw", {}).get("run_id"),
                )
            self._apply_final_answer_filter(state)
            state["evidences"] = answer_evidences
            state["answer_type"] = action
            state["need_user_confirm"] = False
            state["pending_action"] = None
            raw = state.setdefault("raw", {})
            raw["answer_type"] = action
            raw["kb_grounded"] = action in {
                AnswerAction.NORMAL_ANSWER.value,
                AnswerAction.PARTIAL_ANSWER_WITH_LLM.value,
            }
            raw["direct_llm_used"] = action in {
                AnswerAction.NORMAL_ANSWER.value,
                AnswerAction.GENERAL_ANSWER.value,
                AnswerAction.PARTIAL_ANSWER_WITH_LLM.value,
            }
            raw["refused"] = False
            raw["need_general_confirm"] = False
            raw["reranker_used"] = bool(raw.get("reranker_used"))
            state.setdefault("model_routes", {})["answer"] = self.answer_generator.last_model_route or {}
            return state

        return self._with_trace(state, "回答生成", "answer_generator", run)

    def _has_retry_signal(self, judgement: dict[str, Any]) -> bool:
        return bool(judgement.get("suggested_retrievers") or judgement.get("suggested_queries"))

    def _retry_scope_from_evidences(self, state: RetrievalGraphState) -> dict[str, Any]:
        """Build a narrow retry scope from first-round top evidences."""

        document_ids: list[int] = []
        chunk_ids: list[int] = []
        file_names: list[str] = []
        page_numbers_by_document: dict[int, list[int]] = {}
        page_window = 1
        evidences = sorted(
            [evidence for evidence in state.get("evidences", []) if not evidence.metadata.get("metadata_only")],
            key=lambda item: float(item.score),
            reverse=True,
        )[:8]
        for evidence in evidences:
            document_id = self._positive_int(getattr(evidence, "document_id", None))
            chunk_id = self._positive_int(getattr(evidence, "chunk_id", None))
            if document_id is not None and document_id not in document_ids:
                document_ids.append(document_id)
            if chunk_id is not None and chunk_id not in chunk_ids:
                chunk_ids.append(chunk_id)
            file_name = str(getattr(evidence, "file_name", "") or "").strip()
            if file_name and file_name not in file_names:
                file_names.append(file_name)
            page_number = self._positive_int(getattr(evidence, "page_number", None))
            if document_id is None or page_number is None:
                continue
            pages = page_numbers_by_document.setdefault(document_id, [])
            for page in range(max(1, page_number - page_window), page_number + page_window + 1):
                if page not in pages:
                    pages.append(page)

        scope = normalize_retrieval_scope(
            {
                "document_ids": document_ids,
                "chunk_ids": chunk_ids,
                "page_numbers_by_document": page_numbers_by_document,
                "file_names": file_names,
            }
        )
        if scope:
            scope["source"] = "first_round_evidence"
            scope["source_evidence_count"] = len(evidences)
        return scope

    def _positive_int(self, value: Any) -> int | None:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return None
        return normalized if normalized > 0 else None

    def _retry_scope_query_candidates(self, state: RetrievalGraphState) -> list[str]:
        candidates: list[str] = []
        for evidence in state.get("evidences", [])[:5]:
            parts = [
                getattr(evidence, "file_name", None),
                getattr(evidence, "drawing_no", None),
                (getattr(evidence, "metadata", {}) or {}).get("document_name"),
            ]
            text = " ".join(str(item).strip() for item in parts if str(item or "").strip())
            if text:
                candidates.append(text)
        return list(dict.fromkeys(candidates))[:4]

    def _retry_query_limit_for_status(self, evidence_status: str, state: RetrievalGraphState) -> int:
        configured_limit = self._max_retry_queries(state)
        if evidence_status == EVIDENCE_EMPTY and self._looks_like_exact_lookup_fragment(str(state.get("question") or "")):
            return min(configured_limit, 2)
        return 1

    def _retry_execution_ladder(self, retry_retrievers: list[str]) -> list[list[str]]:
        preferred_order = {"page_index": 0, "ripgrep": 1, "keyword": 2, "project_metadata": 3, "milvus": 4}
        ordered = sorted(list(dict.fromkeys(retry_retrievers)), key=lambda name: preferred_order.get(name, 10))
        return [[name] for name in ordered]

    def _retry_added_value_count(self, current_evidences: list[Evidence], retry_groups: list[list[Evidence]]) -> int:
        existing_keys = {
            (evidence.document_id, evidence.chunk_id, evidence.page_number)
            for evidence in current_evidences
        }
        retry_keys = {
            (evidence.document_id, evidence.chunk_id, evidence.page_number)
            for group in retry_groups
            for evidence in group
        }
        return len(retry_keys - existing_keys)

    def _prioritize_retry_retrievers(
        self,
        retrievers: list[str],
        evidence_status: str,
        judgement: dict[str, Any],
        state: RetrievalGraphState,
    ) -> list[str]:
        suggested = {
            str(item or "").strip().lower()
            for item in (judgement.get("suggested_retrievers") or [])
            if str(item or "").strip()
        }
        already_used = {
            str(item or "").strip().lower()
            for item in state.get("used_retrievers", [])
            if str(item or "").strip()
        }
        exact_lookup = self._looks_like_exact_lookup_fragment(str(state.get("question") or ""))
        flow_visual_query = self._is_flow_visual_query(state)

        def priority(name: str) -> tuple[int, str]:
            value = 50
            if name in suggested:
                value -= 20
            rank_map = {
                "page_index": 0,
                "ripgrep": 1,
                "keyword": 2,
                "project_metadata": 3,
                "milvus": 4,
            }
            value += rank_map.get(name, 10) * 4
            if flow_visual_query and name == "page_index":
                value -= 12
            if evidence_status == EVIDENCE_CONFLICTED and name == "project_metadata":
                value -= 18
            if exact_lookup and name in {"page_index", "ripgrep", "keyword"}:
                value -= 8
            if name in already_used and name not in suggested:
                value += 6
            if evidence_status in {EVIDENCE_WEAK_ONLY, EVIDENCE_PARTIAL} and name == "milvus" and name not in suggested:
                value += 12
            return value, name

        ordered = sorted(list(dict.fromkeys(retrievers)), key=priority)
        limit = 1 if state.get("intent") == "project_overview" else self._max_retry_retrievers(state)
        return ordered[:limit]

    def _retry_strategy_for_status(
        self,
        evidence_status: str,
        judgement: dict[str, Any],
        state: RetrievalGraphState,
    ) -> tuple[list[str], list[str], str]:
        """按证据状态选择一次性补检索策略。"""

        suggested_retrievers = list(judgement.get("suggested_retrievers") or [])
        flow_visual_query = self._is_flow_visual_query(state)
        if evidence_status == EVIDENCE_EMPTY:
            if flow_visual_query:
                default_retrievers = ["page_index", "ripgrep", "keyword", "milvus", "project_metadata"]
            else:
                default_retrievers = ["ripgrep", "keyword", "milvus", "project_metadata", "page_index"]
        elif evidence_status == EVIDENCE_WEAK_ONLY:
            default_retrievers = (
                ["page_index", "ripgrep", "keyword", "milvus"]
                if flow_visual_query
                else ["page_index", "ripgrep", "milvus", "keyword"]
            )
        elif evidence_status == EVIDENCE_PARTIAL:
            default_retrievers = (
                ["page_index", "ripgrep", "keyword"]
                if flow_visual_query
                else ["milvus", "ripgrep", "page_index", "keyword"]
            )
        elif evidence_status == EVIDENCE_CONFLICTED:
            default_retrievers = (
                ["page_index", "ripgrep", "keyword", "project_metadata"]
                if flow_visual_query
                else ["project_metadata", "ripgrep", "page_index", "keyword"]
            )
        else:
            return [], [], "evidence_enough"

        already_used = {str(item or "").strip().lower() for item in state.get("used_retrievers", [])}
        if "milvus" in already_used and evidence_status in {EVIDENCE_EMPTY, EVIDENCE_WEAK_ONLY, EVIDENCE_PARTIAL}:
            suggested_retrievers = [name for name in suggested_retrievers if str(name or "").strip().lower() != "milvus"]
            default_retrievers = [name for name in default_retrievers if name != "milvus"]

        retry_retrievers = self._prioritize_retry_retrievers(
            self._filter_available_retrievers([*suggested_retrievers, *default_retrievers]),
            evidence_status,
            judgement,
            state,
        )
        retry_queries = self._retry_queries_for_status(evidence_status, judgement, state)
        reason = judgement.get("reason") or f"evidence_status={evidence_status}"
        return retry_retrievers, retry_queries, reason

    def _retry_queries_for_status(
        self,
        evidence_status: str,
        judgement: dict[str, Any],
        state: RetrievalGraphState,
    ) -> list[str]:
        suggested_queries = [str(item).strip() for item in (judgement.get("suggested_queries") or []) if str(item).strip()]
        query_limit = self._retry_query_limit_for_status(evidence_status, state)
        preferred_suggested = self._sanitize_search_queries(
            state["question"],
            suggested_queries,
            limit=query_limit,
            prefer_original=False,
        )
        suggested_keys = {normalize_query_text(query).lower() for query in suggested_queries}
        if preferred_suggested and any(normalize_query_text(query).lower() in suggested_keys for query in preferred_suggested):
            return preferred_suggested

        candidates: list[str] = []
        candidates.extend(suggested_queries)
        candidates.extend(self._retry_scope_query_candidates(state))
        if evidence_status == EVIDENCE_EMPTY:
            profile = state.get("query_profile", {}) or {}
            profile_terms = [
                *list(profile.get("project_name_candidates") or [])[:2],
                *list(profile.get("entities") or [])[:4],
                *list(profile.get("keywords") or [])[:4],
            ]
            candidates.append(state["question"])
            if profile_terms:
                candidates.append(" ".join(str(item) for item in profile_terms))
            candidates.extend(state.get("sub_queries", [])[1:3])
        elif evidence_status in {EVIDENCE_WEAK_ONLY, EVIDENCE_PARTIAL, EVIDENCE_CONFLICTED}:
            candidates.extend(self._build_retry_queries(suggested_queries, state))
        elif evidence_status == EVIDENCE_WEAK_ONLY:
            candidates.append(f"{state['question']} 正文 参数 流程 设备关系")
            candidates.extend(state.get("sub_queries", [])[:2])
        elif evidence_status == EVIDENCE_PARTIAL:
            candidates.append(state["question"])
        elif evidence_status == EVIDENCE_CONFLICTED:
            candidates.append(f"{state['question']} 版本 审核状态 来源 发布时间 优先级")
        if not candidates:
            candidates = self._build_retry_queries([], state)
        return self._sanitize_search_queries(
            state["question"],
            candidates,
            limit=query_limit,
            prefer_original=False,
        )

    def _filter_available_retrievers(self, retrievers: list[Any]) -> list[str]:
        """按当前 Router 可用列表过滤补充检索器。"""

        available = set(self.retrieval_router.available_retrievers()) & set(KNOWN_RETRIEVERS)
        result: list[str] = []
        for item in retrievers:
            name = str(item or "").strip().lower()
            if name not in available or name in result:
                continue
            result.append(name)
        return result

    def _build_retry_queries(self, suggested_queries: list[Any], state: RetrievalGraphState) -> list[str]:
        """结合模型建议、原始问题、子查询和画像关键词生成补充检索 query。"""

        candidates: list[str] = []
        candidates.extend(str(item).strip() for item in suggested_queries if str(item).strip())
        candidates.append(state["question"])
        candidates.extend(((state.get("question_understanding", {}) or {}).get("query_rewrites") or [])[:4])
        candidates.extend(((state.get("query_features", {}) or {}).get("query_rewrites") or [])[:4])
        candidates.extend(state.get("sub_queries", [])[1:3])
        profile = state.get("query_profile", {}) or {}
        profile_terms = [
            *list(profile.get("project_name_candidates") or [])[:2],
            *list(profile.get("entities") or [])[:4],
            *list(profile.get("keywords") or [])[:4],
        ]
        if profile_terms:
            candidates.append(" ".join(str(item) for item in profile_terms))
        return self._sanitize_search_queries(
            state["question"],
            candidates,
            limit=1 if state.get("intent") == "project_overview" else self._max_retry_queries(state),
            prefer_original=False,
        )

    def _merge_evidences_by_source(self, evidence_groups: list[list[Evidence]], limit: int) -> list[Evidence]:
        """按文档、chunk、页码和图号去重，保留最高分证据。"""

        by_source: dict[tuple[int, int, int | None], Evidence] = {}
        for group in evidence_groups:
            for evidence in group:
                key = (evidence.document_id, evidence.chunk_id, evidence.page_number)
                existing = by_source.get(key)
                if existing is None or self._evidence_score(evidence) > self._evidence_score(existing):
                    by_source[key] = evidence
        return self._top_scored_evidences(list(by_source.values()), limit)

    def _state_log_context(self, state: RetrievalGraphState) -> dict[str, Any]:
        """
        生成节点输入日志摘要。

        参数:
            state: 当前状态

        返回:
            安全可记录的输入摘要
        """

        user = state.get("user")
        raw = state.get("raw", {})
        return {
            "question_meta": self._text_log_metadata(state.get("question", "")),
            "chat_type": state.get("chat_type"),
            "mode": state.get("mode"),
            "project_id": state.get("project_id"),
            "user_id": getattr(user, "id", None),
            "intent": state.get("intent"),
            "route": raw.get("route"),
            "skip_retrieval": bool(raw.get("skip_retrieval")),
            "direct_answer_type": state.get("direct_answer_type"),
            "reason": raw.get("route_reason"),
            "sub_query_count": len(state.get("sub_queries", [])),
            "query_profile": self._query_profile_log_summary(state.get("query_profile", {})),
            "question_understanding": self._question_understanding_log_summary(state.get("question_understanding", {})),
            "policy_resolution": self._policy_resolution_log_summary(state.get("policy_resolution", {})),
            "resolved_task_type": state.get("resolved_task_type"),
            "resolved_answer_shape": state.get("resolved_answer_shape"),
            "query_features": state.get("query_features", {}),
            "retrieval_plan": state.get("retrieval_plan", {}),
            "planned_retrievers": state.get("planned_retrievers", []),
            "model_routes": state.get("model_routes", {}),
            "trace_steps": len(state.get("trace", [])),
        }

    def _state_log_output(self, state: RetrievalGraphState) -> dict[str, Any]:
        """
        生成节点输出日志摘要。

        参数:
            state: 节点执行后的状态

        返回:
            安全可记录的输出摘要
        """

        return {
            "intent": state.get("intent"),
            "route": state.get("raw", {}).get("route"),
            "skip_retrieval": bool(state.get("raw", {}).get("skip_retrieval")),
            "direct_answer_type": state.get("direct_answer_type"),
            "reason": state.get("raw", {}).get("route_reason"),
            "sub_query_count": len(state.get("sub_queries", [])),
            "query_profile": self._query_profile_log_summary(state.get("query_profile", {})),
            "question_understanding": self._question_understanding_log_summary(state.get("question_understanding", {})),
            "policy_resolution": self._policy_resolution_log_summary(state.get("policy_resolution", {})),
            "resolved_task_type": state.get("resolved_task_type"),
            "resolved_answer_shape": state.get("resolved_answer_shape"),
            "resolved_answer_policy": state.get("resolved_answer_policy"),
            "resolved_knowledge_scope": state.get("resolved_knowledge_scope"),
            "query_features": state.get("query_features", {}),
            "retrieval_plan": state.get("retrieval_plan", {}),
            "query_scope": state.get("query_scope"),
            "used_retrievers": state.get("used_retrievers", []),
            "planned_retrievers": state.get("planned_retrievers", []),
            "executed_retrievers": state.get("executed_retrievers", []),
            "skipped_retrievers": state.get("skipped_retrievers", []),
            "fallback_ladder": state.get("fallback_ladder", []),
            "fallback_used": state.get("fallback_used", []),
            "fallback_trigger_reason": state.get("fallback_trigger_reason", []),
            "retriever_hits": state.get("retriever_hits", {}),
            "retriever_elapsed_ms": state.get("retriever_elapsed_ms", {}),
            "retriever_top_scores": state.get("retriever_top_scores", {}),
            "retriever_timeouts": state.get("raw", {}).get("retriever_timeouts", {}),
            "timing_summary": state.get("raw", {}).get("timing_summary", {}),
            "retrieval_sub_query_count": len(state.get("raw", {}).get("retrieval_sub_queries", [])),
            "rerank_details": self._clip(str(state.get("rerank_details", [])), 1000),
            "evidence_judgement": state.get("evidence_judgement", {}),
            "evidence_evaluation": state.get("evidence_evaluation", {}),
            "answer_policy_gate": state.get("answer_policy_decision", {}),
            "answer_policy_decision": state.get("answer_policy_decision", {}),
            "retry_count": state.get("raw", {}).get("retry_count", 0),
            "retry_retrievers": state.get("raw", {}).get("retry_retrievers", []),
            "retry_query_count": state.get("raw", {}).get("retry_query_count", 0),
            "retry_budget_stop_reason": state.get("raw", {}).get("retry_budget_stop_reason"),
            "retry_query_detail_count": len(state.get("raw", {}).get("retry_query_details", [])),
            "model_routes": state.get("model_routes", {}),
            "evidence": self._evidence_log_summary(state.get("evidences", [])),
            "visual_asset_count": state.get("visual_asset_count", 0),
            "answer_preview": self._clip(state.get("answer", ""), 300),
        }

    def _query_profile_log_summary(self, query_profile: dict[str, Any] | None) -> dict[str, Any]:
        """生成不含完整实体/关键词正文的查询画像日志摘要。"""

        profile = query_profile or {}
        return {
            "query_type": profile.get("query_type"),
            "answer_shape": profile.get("answer_shape"),
            "need_page_location": bool(profile.get("need_page_location")),
            "need_exact_term": bool(profile.get("need_exact_term")),
            "need_visual_asset": bool(profile.get("need_visual_asset")),
            "need_graph_reasoning": bool(profile.get("need_graph_reasoning")),
            "entity_count": len(profile.get("entities") or []),
            "keyword_count": len(profile.get("keywords") or []),
            "reason_present": bool(profile.get("reason")),
        }

    def _question_understanding_log_summary(self, understanding: dict[str, Any] | None) -> dict[str, Any]:
        """生成 QuestionUnderstanding 日志摘要。"""

        data = understanding or {}
        return {
            "task_type": data.get("task_type"),
            "answer_shape": data.get("answer_shape"),
            "knowledge_scope": data.get("knowledge_scope"),
            "answer_policy": data.get("answer_policy"),
            "retrieval_needs": data.get("retrieval_needs", {}),
            "query_rewrite_count": len(data.get("query_rewrites") or []),
            "confidence": data.get("confidence"),
            "reason_present": bool(data.get("reason")),
        }

    def _policy_resolution_log_summary(self, policy_resolution: dict[str, Any] | None) -> dict[str, Any]:
        """生成 PolicyResolver 日志摘要。"""

        data = policy_resolution or {}
        return {
            "original_intent": data.get("original_intent"),
            "query_profile_task_type": data.get("query_profile_task_type"),
            "question_understanding_task_type": data.get("question_understanding_task_type"),
            "resolved_task_type": data.get("resolved_task_type"),
            "resolved_answer_shape": data.get("resolved_answer_shape"),
            "answer_policy": data.get("answer_policy"),
            "knowledge_scope": data.get("knowledge_scope"),
            "conflict_detected": data.get("conflict_detected"),
            "conflict_reason_present": bool(data.get("conflict_reason")),
            "resolution_rule": data.get("resolution_rule"),
        }

    def _trace_details(self, step: str, state: RetrievalGraphState, trace_key: str | None = None) -> dict[str, Any]:
        """
        生成前端可展示的节点详情。

        参数:
            step: 当前节点名
            state: 节点执行后的状态

        返回:
            trace 详情字典
        """

        return {
            "step": step,
            "intent": state.get("intent"),
            "route": state.get("raw", {}).get("route"),
            "skip_retrieval": bool(state.get("raw", {}).get("skip_retrieval")),
            "direct_answer_type": state.get("direct_answer_type"),
            "reason": state.get("raw", {}).get("route_reason"),
            "sub_queries": [self._clip(item, 160) for item in state.get("sub_queries", [])],
            "query_profile": state.get("query_profile", {}),
            "question_understanding": state.get("question_understanding", {}),
            "policy_resolution": state.get("policy_resolution", {}),
            "resolved_task_type": state.get("resolved_task_type"),
            "resolved_answer_shape": state.get("resolved_answer_shape"),
            "resolved_answer_policy": state.get("resolved_answer_policy"),
            "resolved_knowledge_scope": state.get("resolved_knowledge_scope"),
            "query_features": state.get("query_features", {}),
            "retrieval_plan": state.get("retrieval_plan", {}),
            "planned_retrievers": state.get("planned_retrievers", []),
            "executed_retrievers": state.get("executed_retrievers", []),
            "skipped_retrievers": state.get("skipped_retrievers", []),
            "skip_reasons": state.get("skip_reasons", {}),
            "fallback_ladder": state.get("fallback_ladder", []),
            "fallback_used": state.get("fallback_used", []),
            "fallback_trigger_reason": state.get("fallback_trigger_reason", []),
            "retriever_hits": state.get("retriever_hits", {}),
            "retriever_elapsed_ms": state.get("retriever_elapsed_ms", {}),
            "retriever_top_scores": state.get("retriever_top_scores", {}),
            "retriever_timeouts": state.get("raw", {}).get("retriever_timeouts", {}),
            "retrieval_sub_queries": state.get("raw", {}).get("retrieval_sub_queries", []),
            "evidence_judgement": state.get("evidence_judgement", {}),
            "evidence_evaluation": state.get("evidence_evaluation", {}),
            "answer_policy_gate": state.get("answer_policy_decision", {}),
            "answer_policy_decision": state.get("answer_policy_decision", {}),
            "retry_count": state.get("raw", {}).get("retry_count", 0),
            "retry_reason": state.get("raw", {}).get("retry_reason"),
            "retry_retrievers": state.get("raw", {}).get("retry_retrievers", []),
            "retry_query_count": state.get("raw", {}).get("retry_query_count", 0),
            "retry_query_details": state.get("raw", {}).get("retry_query_details", []),
            "retry_budget_stop_reason": state.get("raw", {}).get("retry_budget_stop_reason"),
            "timing_summary": state.get("raw", {}).get("timing_summary", {}),
            "evidence_judge_elapsed_ms": state.get("raw", {}).get("evidence_judge_elapsed_ms", 0),
            "retry_evidence_judge_elapsed_ms": state.get("raw", {}).get("retry_evidence_judge_elapsed_ms", 0),
            "model_route": self._model_route_for_trace_key(state, trace_key or self._infer_trace_key(step, "")),
            "evidence": self._evidence_log_summary(state.get("evidences", [])),
            "visual_asset_count": state.get("visual_asset_count", 0),
            "answer_preview": self._clip(state.get("answer", ""), 300),
        }

    def _model_route_for_trace_key(self, state: RetrievalGraphState, trace_key: str) -> dict[str, Any]:
        """按 trace_key 取当前节点的模型路由信息。"""

        model_routes = state.get("model_routes", {})
        return model_routes.get(trace_key, {})

    def _record_trace_timing(
        self,
        state: RetrievalGraphState,
        trace_key: str,
        elapsed_ms: int,
        status: str,
    ) -> None:
        raw = state.setdefault("raw", {})
        stage_timings = dict(raw.get("stage_timings_ms") or {})
        stage_timings[trace_key] = int(elapsed_ms or 0)
        raw["stage_timings_ms"] = stage_timings

        stage_status = dict(raw.get("stage_status") or {})
        stage_status[trace_key] = status
        raw["stage_status"] = stage_status
        raw["timing_summary"] = self._build_timing_summary(state)

    def _sum_ms(self, values: Any) -> int:
        if isinstance(values, dict):
            iterable = values.values()
        elif isinstance(values, (list, tuple, set)):
            iterable = values
        else:
            return 0
        total = 0
        for item in iterable:
            try:
                total += int(item or 0)
            except (TypeError, ValueError):
                continue
        return total

    def _query_timing_total_ms(self, entries: Any) -> int:
        if not isinstance(entries, list):
            return 0
        return self._sum_ms(
            [
                entry.get("execution_elapsed_ms", 0)
                for entry in entries
                if isinstance(entry, dict)
            ]
        )

    def _query_retriever_total_ms(self, entries: Any) -> int:
        if not isinstance(entries, list):
            return 0
        total = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            total += self._sum_ms(entry.get("retriever_elapsed_ms") or {})
        return total

    def _slowest_query_timing(self, entries: Any, index_key: str) -> dict[str, Any] | None:
        if not isinstance(entries, list):
            return None
        slowest_entry: dict[str, Any] | None = None
        slowest_elapsed_ms = -1
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            elapsed_ms = int(entry.get("execution_elapsed_ms") or 0)
            if elapsed_ms <= slowest_elapsed_ms:
                continue
            slowest_elapsed_ms = elapsed_ms
            slowest_entry = entry
        if slowest_entry is None:
            return None
        return {
            "index": slowest_entry.get(index_key),
            "query": slowest_entry.get("query", ""),
            "elapsed_ms": int(slowest_entry.get("execution_elapsed_ms") or 0),
            "executed_retrievers": slowest_entry.get("executed_retrievers", []),
        }

    def _stage_uses_llm(self, state: RetrievalGraphState, trace_key: str) -> bool:
        route = self._model_route_for_trace_key(state, trace_key)
        source = str(route.get("source") or "").strip().lower()
        return bool(source and source not in {"rules", "rules_fallback", "rules_fast_path", "lightweight", "not_called"})

    def _build_timing_summary(self, state: RetrievalGraphState) -> dict[str, Any]:
        raw = state.get("raw", {})
        stage_timings = dict(raw.get("stage_timings_ms") or {})
        llm_stage_timings = {
            key: int(value or 0)
            for key, value in stage_timings.items()
            if self._stage_uses_llm(state, key)
        }
        retrieval_stage_ms = int(stage_timings.get("retrieval") or 0)
        retry_stage_ms = int(stage_timings.get("retry_retrieval") or 0)
        evidence_judge_stage_ms = int(stage_timings.get("evidence_judge") or 0)
        retrieval_sub_queries = list(raw.get("retrieval_sub_queries") or [])
        retry_query_details = list(raw.get("retry_query_details") or [])
        retrieval_sub_query_total_ms = self._query_timing_total_ms(retrieval_sub_queries)
        retry_query_total_ms = self._query_timing_total_ms(retry_query_details)
        retriever_total_ms = self._query_retriever_total_ms(retrieval_sub_queries) or self._sum_ms(
            raw.get("retriever_elapsed_ms") or {}
        )
        retry_retriever_total_ms = self._query_retriever_total_ms(retry_query_details) or self._sum_ms(
            raw.get("retry_elapsed_ms") or {}
        )
        rerank_ms = int(raw.get("rerank_elapsed_ms") or 0)
        retry_rerank_ms = int(raw.get("retry_rerank_elapsed_ms") or 0)
        evidence_judge_elapsed_ms = int(raw.get("evidence_judge_elapsed_ms") or 0)
        llm_evidence_judge_ms = int(raw.get("llm_evidence_judge_ms") or 0)
        retry_evidence_judge_elapsed_ms = int(raw.get("retry_evidence_judge_elapsed_ms") or 0)
        retry_llm_evidence_judge_ms = int(raw.get("retry_llm_evidence_judge_ms") or 0)
        retrieval_sub_query_overhead_ms = max(retrieval_sub_query_total_ms - retriever_total_ms, 0)
        retry_query_overhead_ms = max(retry_query_total_ms - retry_retriever_total_ms, 0)
        retrieval_overhead_ms = max(retrieval_stage_ms - retrieval_sub_query_total_ms - rerank_ms, 0)
        retry_overhead_ms = max(
            retry_stage_ms - retry_query_total_ms - retry_rerank_ms - retry_evidence_judge_elapsed_ms,
            0,
        )
        sorted_stage_timings = sorted(stage_timings.items(), key=lambda item: int(item[1] or 0), reverse=True)
        slowest_stage = sorted_stage_timings[0] if sorted_stage_timings else None
        retriever_elapsed = dict(raw.get("retriever_elapsed_ms") or {})
        slowest_retriever = None
        if retriever_elapsed:
            slowest_retriever = max(retriever_elapsed.items(), key=lambda item: int(item[1] or 0))
        return {
            "total_stage_ms": self._sum_ms(stage_timings),
            "stage_timings_ms": stage_timings,
            "llm_stage_timings_ms": llm_stage_timings,
            "retrieval_pipeline_ms": {
                "retrieval_stage_ms": retrieval_stage_ms,
                "retrieval_sub_query_total_ms": retrieval_sub_query_total_ms,
                "retriever_total_ms": retriever_total_ms,
                "retrieval_sub_query_overhead_ms": retrieval_sub_query_overhead_ms,
                "rerank_ms": rerank_ms,
                "retrieval_overhead_ms": retrieval_overhead_ms,
                "evidence_judge_stage_ms": evidence_judge_stage_ms,
                "evidence_judge_elapsed_ms": evidence_judge_elapsed_ms,
                "llm_evidence_judge_ms": llm_evidence_judge_ms,
                "retry_stage_ms": retry_stage_ms,
                "retry_query_total_ms": retry_query_total_ms,
                "retry_retriever_total_ms": retry_retriever_total_ms,
                "retry_query_overhead_ms": retry_query_overhead_ms,
                "retry_rerank_ms": retry_rerank_ms,
                "retry_evidence_judge_elapsed_ms": retry_evidence_judge_elapsed_ms,
                "retry_llm_evidence_judge_ms": retry_llm_evidence_judge_ms,
                "retry_overhead_ms": retry_overhead_ms,
            },
            "slowest_stage": (
                {"name": slowest_stage[0], "elapsed_ms": int(slowest_stage[1] or 0)} if slowest_stage is not None else None
            ),
            "slowest_retriever": (
                {"name": slowest_retriever[0], "elapsed_ms": int(slowest_retriever[1] or 0)}
                if slowest_retriever is not None
                else None
            ),
            "slowest_sub_query": self._slowest_query_timing(retrieval_sub_queries, "sub_query_index"),
            "slowest_retry_query": self._slowest_query_timing(retry_query_details, "retry_query_index"),
        }

    def next_trace_sequence(self, state: RetrievalGraphState) -> int:
        """为同一次问答生成递增的 trace 序号，便于前端合并 running/success 状态。"""

        raw = state.setdefault("raw", {})
        sequence = int(raw.get("trace_sequence", 0)) + 1
        raw["trace_sequence"] = sequence
        return sequence

    def trace_delta_payload(self, trace_item: dict[str, Any]) -> dict[str, Any]:
        """裁剪 trace item 为 SSE trace_delta 事件，同时保留右侧详情面板需要的结构化字段。"""

        payload: dict[str, Any] = {
            "sequence": trace_item.get("sequence"),
            "step": trace_item.get("step"),
            "status": trace_item.get("status", "success"),
            "display_text": trace_item.get("display_text") or trace_item.get("result") or "",
        }
        for key in (
            "implementation",
            "elapsed_ms",
            "result",
            "intent",
            "sub_query_index",
            "sub_query_total",
            "input_summary",
            "output_summary",
            "details",
        ):
            if key in trace_item:
                payload[key] = trace_item[key]
        return payload

    def answer_running_trace_delta(self, state: RetrievalGraphState, sequence: int) -> dict[str, Any]:
        """生成回答阶段开始时的 trace_delta。"""

        return self._running_trace_delta(state, "answer", sequence)

    def _running_trace_delta(self, state: RetrievalGraphState, trace_key: str, sequence: int) -> dict[str, Any]:
        return self.trace_delta_payload(
            {
                "sequence": sequence,
                "step": TRACE_NODE_STEPS.get(trace_key, trace_key),
                "status": "running",
                "display_text": self._trace_running_text(trace_key, state),
                "elapsed_ms": None,
                "details": {},
            }
        )

    def _latest_trace_item(self, state: RetrievalGraphState, trace_count: int) -> dict[str, Any] | None:
        trace_items = state.get("trace", [])
        if len(trace_items) <= trace_count:
            return None
        return trace_items[-1]

    def _visual_reading_trace_deltas(self, state: RetrievalGraphState) -> list[dict[str, Any]]:
        visual_asset_count = int(state.get("visual_asset_count") or 0)
        if visual_asset_count <= 0:
            return []

        sequence = self.next_trace_sequence(state)
        running_delta = self._running_trace_delta(state, "visual_reading", sequence)
        step = TRACE_NODE_STEPS["visual_reading"]
        trace_item = {
            "sequence": sequence,
            "step": step,
            "implementation": "visual_evidence",
            "status": "success",
            "elapsed_ms": 0,
            "intent": state.get("intent"),
            "sub_query_index": None,
            "sub_query_total": len(state.get("sub_queries", [])),
            "input_summary": self._state_log_context(state),
            "output_summary": self._state_log_output(state),
            "details": self._trace_details(step, state, "visual_reading"),
        }
        trace_item["display_text"] = self._trace_success_text("visual_reading", state, trace_item)
        state.setdefault("trace", []).append(trace_item)
        return [running_delta, self.trace_delta_payload(trace_item)]

    def _infer_trace_key(self, step: str, implementation: str) -> str:
        if implementation == "query_profile":
            return "query_profile"
        if implementation == "question_understanding":
            return "question_understanding"
        if implementation == "policy_resolution":
            return "policy_resolution"
        if implementation == "planner":
            return "planner"
        if implementation == "direct_answer":
            return "answer"
        if "补充检索" in step:
            return "retry_retrieval"
        if implementation == "router+reranker":
            return "retrieval"
        if implementation == "answer_generator":
            return "answer"
        if "意图" in step:
            return "intent"
        if "查询" in step or "拆解" in step:
            return "query_decompose"
        if "证据" in step:
            return "evidence_judge"
        return step

    def _trace_running_text(self, trace_key: str, state: RetrievalGraphState) -> str:
        if trace_key == "intent":
            return "正在识别问题类型..."
        if trace_key == "query_decompose":
            return "正在拆解查询..."
        if trace_key == "query_profile":
            return "正在生成查询画像..."
        if trace_key == "question_understanding":
            return "正在理解问题结构..."
        if trace_key == "policy_resolution":
            return "正在解析问答策略..."
        if trace_key == "planner":
            return "正在选择检索方式..."
        if trace_key == "retrieval":
            return f"正在检索资料：{self._material_scope_label(state)}..."
        if trace_key == "evidence_judge":
            return "正在判断证据是否足够..."
        if trace_key == "retry_retrieval":
            return "证据不足，正在补充检索..."
        if trace_key == "visual_reading":
            return "正在阅读图纸..."
        if trace_key == "answer":
            if self._should_direct_answer(state):
                if state.get("direct_answer_type") in {"pure_general_qa", "general_qa"}:
                    return "正在回答通用问题..."
                return "正在准备回复..."
            return f"正在生成回答...\n{self._answer_basis_text(state)}"
        return "正在执行..."

    def _trace_success_text(
        self,
        trace_key: str,
        state: RetrievalGraphState,
        _: dict[str, Any],
    ) -> str:
        if trace_key == "intent":
            intent = str(state.get("intent") or "knowledge_qa")
            if self._should_direct_answer(state):
                return f"已识别为：{INTENT_LABELS.get(intent, intent)}，不检索知识库"
            return f"已识别为：{INTENT_LABELS.get(intent, intent)}"
        if trace_key == "query_decompose":
            sub_queries = state.get("sub_queries", []) or [state.get("question", "")]
            query_text = "；".join(self._clip(item, 120) for item in sub_queries)
            return f"生成 {len(sub_queries)} 个检索问题：{query_text}"
        if trace_key == "query_profile":
            profile = state.get("query_profile", {}) or {}
            query_type = str(profile.get("query_type") or "unknown")
            answer_shape = str(profile.get("answer_shape") or "general")
            answer_shape_text = self._answer_shape_label(answer_shape, profile)
            return f"已生成查询画像：{INTENT_LABELS.get(query_type, query_type)} / {answer_shape_text}"
        if trace_key == "question_understanding":
            understanding = state.get("question_understanding", {}) or {}
            task_type = str(understanding.get("task_type") or "unknown")
            answer_shape = str(understanding.get("answer_shape") or "direct_answer")
            rewrites = understanding.get("query_rewrites") or []
            rewrite_text = "；".join(self._clip(str(item), 80) for item in rewrites[:5]) or "无"
            return f"已生成问题理解：{task_type} / {answer_shape}\n改写：{rewrite_text}"
        if trace_key == "policy_resolution":
            resolution = state.get("policy_resolution", {}) or {}
            conflict_text = "是" if resolution.get("conflict_detected") else "否"
            return (
                "已解析最终策略："
                f"{resolution.get('resolved_task_type')} / {resolution.get('answer_policy')} / {resolution.get('knowledge_scope')}"
                f"\n冲突：{conflict_text}"
            )
        if trace_key == "planner":
            plan = state.get("retrieval_plan", {})
            selected = state.get("planned_retrievers") or plan.get("selected_retrievers", [])
            skipped = state.get("skipped_retrievers") or plan.get("skipped_retrievers", [])
            selected_text = self._format_retrievers(selected, RETRIEVER_PLAN_LABELS, " + ") or "默认检索"
            skipped_text = self._format_retrievers(skipped, RETRIEVER_PLAN_LABELS, "、") or "无"
            return f"选择：{selected_text}\n跳过：{skipped_text}"
        if trace_key == "retrieval":
            return self._retriever_hit_text(state)
        if trace_key == "evidence_judge":
            evidence_count = len(state.get("evidences", []))
            visual_asset_count = int(state.get("visual_asset_count") or 0)
            evaluation = state.get("evidence_evaluation", {}) or {}
            status = evaluation.get("evidence_status") or ("ENOUGH" if state.get("evidence_judgement", {}).get("enough") else "PENDING")
            weak_count = int(evaluation.get("weak_evidence_count") or 0)
            strong_count = int(evaluation.get("strong_evidence_count") or 0)
            return (
                f"证据状态：{status}，强证据 {strong_count} 条，弱证据 {weak_count} 条，"
                f"合并后保留 {evidence_count} 条证据\n关联 {visual_asset_count} 张图纸图片"
            )
        if trace_key == "retry_retrieval":
            retry_count = int(state.get("raw", {}).get("retry_count") or 0)
            if retry_count <= 0:
                return "证据已足够或缺少补充检索建议，未执行补充检索"
            retrievers = self._format_retrievers(state.get("raw", {}).get("retry_retrievers", []), RETRIEVER_PLAN_LABELS, " + ")
            query_count = int(state.get("raw", {}).get("retry_query_count") or 0)
            return f"已补充检索 {query_count} 个查询：{retrievers or '默认检索'}"
        if trace_key == "visual_reading":
            visual_asset_count = int(state.get("visual_asset_count") or 0)
            return f"已输入 {visual_asset_count} 张图纸图片给视觉模型"
        if trace_key == "answer":
            if self._should_direct_answer(state):
                return f"已直接回答\n{self._answer_basis_text(state)}"
            return f"回答已生成\n{self._answer_basis_text(state)}"
        return "已执行"

    def _trace_failed_text(self, trace_key: str) -> str:
        stage_label = {
            "intent": "理解问题",
            "query_decompose": "拆解查询",
            "planner": "规划检索方式",
            "question_understanding": "生成问题理解",
            "policy_resolution": "解析问答策略",
            "retrieval": "检索资料",
            "evidence_judge": "整理证据",
            "query_profile": "生成查询画像",
            "retry_retrieval": "补充检索",
            "visual_reading": "阅读图纸",
            "answer": "生成回答",
        }.get(trace_key, "执行步骤")
        return f"{stage_label}失败，请稍后重试"

    def _retriever_hit_text(self, state: RetrievalGraphState) -> str:
        hits = state.get("retriever_hits", {})
        ordered_names = [name for name in ("page_index", "ripgrep", "milvus", "keyword", "graphrag") if name in hits]
        ordered_names.extend(name for name in hits if name not in ordered_names)
        if not ordered_names:
            return "未命中有效资料"
        return "\n".join(
            f"{RETRIEVER_HIT_LABELS.get(name, name)} 命中 {int(hits.get(name) or 0)} 条" for name in ordered_names
        )

    def _format_retrievers(self, retrievers: list[str], labels: dict[str, str], separator: str) -> str:
        return separator.join(labels.get(item, item) for item in retrievers if item)

    def _answer_shape_label(self, answer_shape: str, query_profile: dict[str, Any]) -> str:
        """生成查询画像中的回答形态展示文案，避免前端出现 raw code。"""

        if (
            answer_shape == "general"
            and str(query_profile.get("knowledge_scope") or "") == "industry"
            and str(query_profile.get("query_type") or "") == "industry_knowledge_qa"
        ):
            return ANSWER_SHAPE_LABELS["industry_explanation"]
        return ANSWER_SHAPE_LABELS.get(answer_shape, answer_shape)

    def _material_scope_label(self, state: RetrievalGraphState) -> str:
        knowledge_scope = str((state.get("query_profile") or {}).get("knowledge_scope") or "")
        if knowledge_scope == "industry":
            return "行业基础知识库"
        if knowledge_scope == "project_with_industry":
            return "项目资料 + 授权行业知识库"
        return "项目资料" if state.get("chat_type") == "project_chat" else "基础知识库"

    def _answer_basis_text(self, state: RetrievalGraphState) -> str:
        if self._should_direct_answer(state):
            if state.get("direct_answer_type") == "greeting":
                return "未检索知识库，直接回复问候"
            return "未检索知识库，直接回答通用问题"
        action = str(state.get("answer_policy_action") or "")
        if action == AnswerAction.LIMITED_ANSWER.value:
            return "仅基于项目资料中的弱证据输出有限回答"
        if action in {AnswerAction.PARTIAL_ANSWER.value, AnswerAction.PARTIAL_ANSWER_WITH_LLM.value}:
            return "仅基于项目资料中的部分证据输出受限回答"
        if action == AnswerAction.CONFLICT_ANSWER.value:
            return "资料存在冲突，仅输出冲突说明和可核对证据"
        if action == AnswerAction.GENERAL_ANSWER.value:
            return "未引用知识库资料，基于通用知识回答"
        if action == AnswerAction.REFUSAL.value:
            return "项目资料无有效证据，拒绝使用通用知识编造项目事实"
        if action == AnswerAction.ASK_GENERAL_CONFIRM.value:
            return "知识库无有效证据，等待用户确认是否使用通用知识"
        if state.get("chat_type") == "project_chat":
            knowledge_scope = str((state.get("query_profile") or {}).get("knowledge_scope") or "")
            if knowledge_scope == "project_with_industry":
                return "基于项目资料组织答案，行业知识仅作补充解释"
            if int(state.get("visual_asset_count") or 0) > 0:
                return "基于 P&ID 图纸和项目资料组织答案"
            return "基于项目资料组织答案"
        if str((state.get("query_profile") or {}).get("knowledge_scope") or "") == "industry":
            if not state.get("evidences"):
                return "未检索到行业知识库资料，基于模型通用知识回答"
            return "基于行业基础知识库资料组织答案"
        return "基于基础知识库资料组织答案"

    def _evidence_log_summary(self, evidences: list[Evidence]) -> list[dict[str, Any]]:
        """
        生成 Evidence 日志摘要。

        参数:
            evidences: 检索证据列表

        返回:
            保留来源追踪字段的摘要列表
        """

        summary: list[dict[str, Any]] = []
        for evidence in evidences[:5]:
            summary.append(
                {
                    "retriever": evidence.retriever,
                    "score": round(float(evidence.score), 4),
                    "source_type": evidence.source_type,
                    "project_id": evidence.project_id,
                    "knowledge_base_id": evidence.knowledge_base_id,
                    "document_id": evidence.document_id,
                    "drawing_no": evidence.drawing_no,
                    "page_no": evidence.page_number,
                    "chunk_id": evidence.chunk_id,
                    "visual_asset_count": len(evidence.assets),
                    "content_length": len(evidence.content or ""),
                }
            )
        return summary

    def _clip(self, value: Any, limit: int) -> str:
        """
        截断日志文本，避免长内容打爆日志。

        参数:
            value: 待输出值
            limit: 最大字符数

        返回:
            截断后的文本
        """

        text = "" if value is None else str(value).replace("\r", " ").replace("\n", " ")
        if len(text) <= limit:
            return text
        return f"{text[:limit]}..."

    def _text_log_metadata(self, value: Any) -> dict[str, Any]:
        """生成不可逆文本指纹，日志中不得记录问题或知识内容原文。"""

        text = "" if value is None else str(value)
        return {
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
            "length": len(text),
        }

    def _apply_final_answer_filter(
        self,
        state: RetrievalGraphState,
        answer: str | None = None,
    ) -> None:
        """在 trace、日志或响应接触最终答案前执行兜底脱敏。"""

        user = state.get("user")
        if user is None:
            state["answer"] = ""
            return
        service = getattr(self, "sensitive_content_service", None)
        if service is None:
            # 兼容测试和降级构造路径；正式实例仍复用初始化时创建的服务。
            service = SensitiveContentService(getattr(self, "db", None))
        source_answer = state.get("answer") if answer is None else answer
        filtered = service.filter_for_user(str(source_answer or "").strip(), user)
        state["answer"] = filtered.safe_content
        combined_types = set(state.get("redaction_types", [])) | set(filtered.redaction_types)
        state["redaction_types"] = sorted(combined_types)
        state["redaction_count"] = int(state.get("redaction_count") or 0) + filtered.redaction_count
        state["redacted"] = bool(combined_types)
        state["final_answer_redacted"] = bool(state.get("final_answer_redacted") or filtered.redacted)

    def _to_agent_result(self, state: RetrievalGraphState) -> dict[str, Any]:
        """
        转换为旧 AgentExecutor 兼容输出。

        参数:
            state: 最终状态

        返回:
            兼容前端的数据结构
        """

        raw = {
            **state.get("raw", {}),
            "intent": state.get("intent"),
            "intent_type": state.get("intent_type"),
            "answer_policy": state.get("answer_policy"),
            "answer_type": state.get("answer_type"),
            "answer_policy_action": state.get("answer_policy_action"),
            "evidence_status": state.get("evidence_status"),
            "candidate_k": self._candidate_k(state),
            "rerank_top_k": self._rerank_top_k(state),
            "answer_top_k": self._answer_top_k(state),
            "reranker_used": bool(state.get("raw", {}).get("reranker_used") or state.get("rerank_details")),
            "direct_llm_used": bool(state.get("raw", {}).get("direct_llm_used")),
            "kb_grounded": bool(
                state.get("raw", {}).get("kb_grounded")
                or state.get("answer_type")
                in {
                    AnswerAction.NORMAL_ANSWER.value,
                    AnswerAction.PARTIAL_ANSWER.value,
                    AnswerAction.PARTIAL_ANSWER_WITH_LLM.value,
                    AnswerAction.CONFLICT_ANSWER.value,
                }
            ),
            "refused": bool(state.get("raw", {}).get("refused") or state.get("answer_type") == AnswerAction.REFUSAL.value),
            "need_general_confirm": bool(
                state.get("raw", {}).get("need_general_confirm")
                or state.get("answer_type") == AnswerAction.ASK_GENERAL_CONFIRM.value
            ),
        }
        self._apply_final_answer_filter(state)
        answer = str(state.get("answer") or "").strip()
        if not answer:
            answer = PROJECT_REFUSAL_ANSWER if state.get("chat_type") == "project_chat" else BASE_GENERAL_CONFIRM_ANSWER
        return {
            "answer": answer,
            "redacted": bool(state.get("redacted")),
            "redaction_types": list(state.get("redaction_types", [])),
            "redaction_count": int(state.get("redaction_count") or 0),
            "security_notice": SECURITY_NOTICE if state.get("redacted") else None,
            "final_answer_redacted": bool(state.get("final_answer_redacted")),
            "chat_type": state["chat_type"],
            "mode": state["mode"],
            "answer_type": state.get("answer_type"),
            "intent_type": state.get("intent_type"),
            "answer_policy": state.get("answer_policy"),
            "evidence_status": state.get("evidence_status"),
            "need_user_confirm": bool(state.get("need_user_confirm")),
            "pending_action": state.get("pending_action"),
            "query_scope": state.get("query_scope") or "自动判断",
            "used_retrievers": state.get("used_retrievers", []),
            "agent_trace": state.get("trace", []),
            "trace_steps": state.get("trace", []),
            "evidences": state.get("evidences", []),
            "raw": {
                **raw,
                "route": state.get("raw", {}).get("route"),
                "skip_retrieval": bool(state.get("raw", {}).get("skip_retrieval")),
                "direct_answer_type": state.get("direct_answer_type"),
                "route_reason": state.get("raw", {}).get("route_reason"),
                "sub_queries": state.get("sub_queries", []),
                "query_profile": state.get("query_profile", {}),
                "question_understanding": state.get("question_understanding", {}),
                "policy_resolution": state.get("policy_resolution", {}),
                "resolved_task_type": state.get("resolved_task_type"),
                "resolved_answer_shape": state.get("resolved_answer_shape"),
                "resolved_answer_policy": state.get("resolved_answer_policy"),
                "resolved_knowledge_scope": state.get("resolved_knowledge_scope"),
                "query_features": state.get("query_features", {}),
                "retrieval_plan": state.get("retrieval_plan", {}),
                "planned_retrievers": state.get("planned_retrievers", []),
                "executed_retrievers": state.get("executed_retrievers", []),
                "skipped_retrievers": state.get("skipped_retrievers", []),
                "skip_reasons": state.get("skip_reasons", {}),
                "fallback_ladder": state.get("fallback_ladder", []),
                "fallback_used": state.get("fallback_used", []),
                "fallback_trigger_reason": state.get("fallback_trigger_reason", []),
                "retriever_hits": state.get("retriever_hits", {}),
                "retriever_elapsed_ms": state.get("retriever_elapsed_ms", {}),
                "retriever_top_scores": state.get("retriever_top_scores", {}),
                "rerank_details": state.get("rerank_details", []),
                "evidence_judgement": state.get("evidence_judgement", {}),
                "evidence_evaluation": state.get("evidence_evaluation", {}),
                "answer_policy_gate": state.get("answer_policy_decision", {}),
                "answer_policy_decision": state.get("answer_policy_decision", {}),
                "max_retry": state.get("raw", {}).get("max_retry", 1),
                "retry_count": state.get("raw", {}).get("retry_count", 0),
                "retry_reason": state.get("raw", {}).get("retry_reason"),
                "retry_retrievers": state.get("raw", {}).get("retry_retrievers", []),
                "retry_query_count": state.get("raw", {}).get("retry_query_count", 0),
                "retry_queries": state.get("raw", {}).get("retry_queries", []),
                "model_routes": state.get("model_routes", {}),
                "visual_asset_count": state.get("visual_asset_count", 0),
            },
        }
