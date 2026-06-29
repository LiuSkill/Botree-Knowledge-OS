"""
Retrieval LangGraph

负责：
1. 编排在线问答中的意图识别、查询拆解、检索规划、多路检索、证据判断和回答生成
2. 在 langgraph 依赖不可用时提供等价的顺序执行器
3. 输出前端可展示的 trace_steps 和后端可审计的 raw 调试信息
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterator
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.agent.answer_generator import AnswerGenerator, PROJECT_REFUSAL_TEXT
from app.langgraph.state import RetrievalGraphState
from app.models.user import User
from app.retrieval.merger import EvidenceMerger
from app.retrieval.router import RetrievalRouter
from app.retrieval.schemas import Evidence
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
        allow_reranker_fallback: bool = False,
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
            "LangGraph预处理开始: run_id=%s user_id=%s chat_type=%s mode=%s project_id=%s question=%s",
            state.get("raw", {}).get("run_id"),
            getattr(user, "id", None),
            chat_type,
            mode,
            project_id,
            self._clip(question, 300),
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
        allow_reranker_fallback: bool = False,
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
            "LangGraph预处理流开始: run_id=%s user_id=%s chat_type=%s mode=%s project_id=%s question=%s",
            state.get("raw", {}).get("run_id"),
            getattr(user, "id", None),
            chat_type,
            mode,
            project_id,
            self._clip(question, 300),
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

        final_state = self._append_answer_trace(state, answer, elapsed_ms, trace_sequence)
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
        allow_reranker_fallback: bool = False,
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
            "LangGraph问答开始: run_id=%s user_id=%s chat_type=%s mode=%s project_id=%s question=%s",
            run_id,
            getattr(user, "id", None),
            chat_type,
            mode,
            project_id,
            self._clip(question, 300),
        )
        if self._compiled_graph is not None:
            final_state = self._compiled_graph.invoke(state)
        else:
            final_state = self._run_sequential(state)
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
                "candidate_k": int(candidate_k) if candidate_k is not None else 100,
                "rerank_top_k": int(rerank_top_k) if rerank_top_k is not None else 30,
                "eval_top_k": int(eval_top_k) if eval_top_k is not None else 100,
                "answer_top_k": int(answer_top_k) if answer_top_k is not None else 10,
                "retrieval_mode": str(retrieval_mode or "full"),
                "require_real_reranker": bool(require_real_reranker),
                "allow_reranker_fallback": bool(allow_reranker_fallback),
                "reranker_score_order": str(reranker_score_order or "desc"),
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
            raw["require_real_reranker"] = True
            raw["allow_reranker_fallback"] = False
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
                    "快速门控命中无效输入: run_id=%s chat_type=%s question=%s skip_retrieval=true",
                    raw.get("run_id"),
                    state.get("chat_type"),
                    self._clip(state.get("question", ""), 120),
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
            limit = 5
        return max(1, min(limit, 200))

    def _candidate_k(self, state: RetrievalGraphState) -> int:
        raw = state.get("raw", {})
        raw_limit = raw.get("candidate_k") or raw.get("retrieval_limit")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 100
        return max(1, min(limit, 200))

    def _rerank_top_k(self, state: RetrievalGraphState) -> int:
        if state.get("intent") == "project_overview":
            return 6
        raw = state.get("raw", {})
        raw_limit = raw.get("rerank_top_k") or raw.get("candidate_k") or raw.get("retrieval_limit")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 100
        return max(1, min(limit, 200))

    def _eval_top_k(self, state: RetrievalGraphState) -> int:
        raw = state.get("raw", {})
        raw_limit = raw.get("eval_top_k") or raw.get("retrieval_limit")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 100
        return max(1, min(limit, 200))

    def _answer_top_k(self, state: RetrievalGraphState) -> int:
        raw_limit = state.get("raw", {}).get("answer_top_k")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
        if limit != 10:
            logger.warning("answer_top_k=%s 当前真实答案生成链路固定使用Top10", limit)
        return 10

    def _retrieval_mode(self, state: RetrievalGraphState) -> str:
        mode = str(state.get("raw", {}).get("retrieval_mode") or "full").strip().lower()
        return mode if mode in {"fast", "smart", "full"} else "full"

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
        if metadata.get("policy_matrix_used"):
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

    def _record_answer_context(self, state: RetrievalGraphState) -> list[Evidence]:
        """Record the fixed Top10 answer context without changing eval_top_k evidences."""

        answer_top_k = self._answer_top_k(state)
        answer_evidences = list(state.get("evidences", []))[:answer_top_k]
        raw = state.setdefault("raw", {})
        raw["answer_top_k"] = answer_top_k
        raw["answer_context_count"] = len(answer_evidences)
        raw["answer_context_doc_ids"] = [self._evidence_debug_id(evidence) for evidence in answer_evidences]
        raw["final_answer_doc_ids_top10"] = raw["answer_context_doc_ids"][:10]
        return answer_evidences

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
            return candidates[:limit]

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

            state["answer"] = answer
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
            state["sub_queries"] = self.qwen.decompose_query(state["question"], state["intent"])
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
            max_sub_queries = 2 if effective_task_type == "project_overview" else 3
            sub_queries = state.get("sub_queries", [state["question"]])[:max_sub_queries]
            candidate_k = self._candidate_k(state)
            rerank_top_k = self._rerank_top_k(state)
            eval_top_k = self._eval_top_k(state)
            merge_limit = max(eval_top_k, rerank_top_k, candidate_k)

            for sub_query_index, sub_query in enumerate(sub_queries, start=1):
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
                for name, reason in retrieval.get("skip_reasons", {}).items():
                    skip_reasons.setdefault(name, reason)

                logger.info(
                    "LangGraph子查询完成: run_id=%s step=retrieval implementation=router status=success intent=%s sub_query_index=%s sub_query_total=%s query=%s executed_retrievers=%s skipped_retrievers=%s fallback_used=%s fallback_trigger_reason=%s retriever_hits=%s retriever_elapsed_ms=%s",
                    state.get("raw", {}).get("run_id"),
                    effective_task_type or state.get("intent"),
                    sub_query_index,
                    len(sub_queries),
                    self._clip(sub_query, 300),
                    retrieval.get("executed_retrievers", []),
                    retrieval.get("skipped_retrievers", []),
                    retrieval.get("fallback_used", []),
                    self._clip(str(retrieval.get("fallback_trigger_reason", [])), 1200),
                    retrieval.get("retriever_hits", {}),
                    retrieval.get("retriever_elapsed_ms", {}),
                )

            merged = self.merger.merge(evidence_groups, merge_limit)
            rerank_candidates = merged[:rerank_top_k]
            pre_rerank_guard = self.evidence_access_guard.filter_evidences(
                evidences=rerank_candidates,
                chat_type=str(state.get("chat_type") or ""),
                project_id=state.get("project_id"),
                user=state.get("user"),
                audit_action="RAG证据权限过滤",
            )
            rerank_candidates = pre_rerank_guard.evidences
            raw_before_doc_ids = [self._evidence_debug_id(evidence) for evidence in rerank_candidates]
            raw_before_scores = [float(evidence.score) for evidence in rerank_candidates]
            rerank_started_at = time.perf_counter()
            evidences = self._rerank_evidences(state, rerank_candidates, eval_top_k)
            rerank_elapsed_ms = int((time.perf_counter() - rerank_started_at) * 1000)
            evidences = evidences[:eval_top_k]
            metadata_evidence_count = sum(1 for evidence in evidences if evidence.metadata.get("metadata_only"))
            if metadata_evidence_count:
                evidences = [evidence for evidence in evidences if not evidence.metadata.get("metadata_only")]
            evidences = self.visual_evidence_service.enrich(
                state["question"],
                evidences,
                state.get("query_features", {}),
            )
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
            state["raw"]["retrieval_limit"] = eval_top_k
            state["raw"]["candidate_k"] = candidate_k
            state["raw"]["rerank_top_k"] = rerank_top_k
            state["raw"]["eval_top_k"] = eval_top_k
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
            raw = state.setdefault("raw", {})
            eval_top_k = self._eval_top_k(state)
            before_doc_ids = [self._evidence_debug_id(evidence) for evidence in state.get("evidences", [])]
            raw["evidence_before_judge_doc_ids"] = before_doc_ids[:eval_top_k]
            if bool(raw.get("eval_mode")) or self._retrieval_mode(state) in {"fast", "smart"}:
                state["evidences"] = list(state.get("evidences", []))[:eval_top_k]
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
                raw["llm_evidence_judge_ms"] = 0
                raw["lightweight_filter_ms"] = 0
                state.setdefault("model_routes", {})["evidence_judge"] = {
                    "task": "evidence_judge",
                    "source": "lightweight",
                    "reason": "BEIR/fast/smart evaluation uses non-LLM evidence filter",
                }
                return state
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
            state["evidences"] = list(state.get("evidences", []))[:eval_top_k]
            raw["evidence_judgement"] = state["evidence_judgement"]
            raw["evidence_after_judge_doc_ids"] = [self._evidence_debug_id(evidence) for evidence in state.get("evidences", [])]
            self._record_answer_context(state)
            state.setdefault("model_routes", {})["evidence_judge"] = self.qwen.model_routes.get("evidence_judge", {})
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
            retry_skip_reason = self._retry_skip_reason(state, judgement, retry_count, pre_retry_status)
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

            raw["max_retry"] = 1
            raw["retry_count"] = retry_count + 1
            raw["retry_allowed"] = True
            raw["retry_reason"] = retry_reason
            raw["retry_retrievers"] = retry_retrievers
            raw["retry_queries"] = retry_queries
            raw["retry_query_count"] = len(retry_queries)
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
            retry_executed: list[str] = []
            retry_skipped: list[str] = []
            retry_skip_reasons: dict[str, str] = {}
            query_scope = state.get("query_scope") or ""
            effective_mode = state["mode"]
            retrieval_limit = self._retrieval_limit(state)
            retry_rerank_top_k = min(10, self._rerank_top_k(state))
            merge_limit = max(10, retrieval_limit * 2)

            for index, retry_query in enumerate(retry_queries, start=1):
                retrieval = self.retrieval_router.execute_planned(
                    query=retry_query,
                    mode=state["mode"],
                    project_id=state["project_id"],
                    user=state["user"],
                    retriever_names=retry_retrievers,
                    limit=retrieval_limit,
                    chat_type=state["chat_type"],
                    fallback_retrievers=[],
                    fallback_ladder=[retry_retrievers],
                    query_features=state.get("query_features", {}),
                    skip_reasons=state.get("skip_reasons", {}),
                    run_id=raw.get("run_id"),
                    intent=state.get("intent"),
                    sub_query_index=index,
                    sub_query_total=len(retry_queries),
                    knowledge_scope=str((state.get("query_profile") or {}).get("knowledge_scope") or ""),
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

            merged = self._merge_evidences_by_source([state.get("evidences", []), *retry_groups], merge_limit)
            rerank_started_at = time.perf_counter()
            evidences = self._rerank_evidences(
                state,
                merged[:retry_rerank_top_k],
                self._eval_top_k(state),
            )
            retry_rerank_elapsed_ms = int((time.perf_counter() - rerank_started_at) * 1000)
            evidences = self.visual_evidence_service.enrich(
                state["question"],
                evidences,
                state.get("query_features", {}),
            )
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
            state.setdefault("model_routes", {})["evidence_judge_retry"] = self.qwen.model_routes.get("evidence_judge", {})
            state["model_routes"]["evidence_judge"] = self.qwen.model_routes.get("evidence_judge", {})

            raw["retry_hits"] = retry_hits
            raw["retry_elapsed_ms"] = retry_elapsed
            raw["retry_top_scores"] = retry_top_scores
            raw["retry_executed_retrievers"] = list(dict.fromkeys(retry_executed))
            raw["executed_retrievers"] = state["executed_retrievers"]
            raw["skipped_retrievers"] = state["skipped_retrievers"]
            raw["skip_reasons"] = state["skip_reasons"]
            raw["retriever_hits"] = state.get("retriever_hits", {})
            raw["retriever_elapsed_ms"] = state.get("retriever_elapsed_ms", {})
            raw["retriever_top_scores"] = state.get("retriever_top_scores", {})
            raw["rerank_details"] = state.get("rerank_details", [])
            raw["retry_rerank_elapsed_ms"] = retry_rerank_elapsed_ms
            raw["retry_rerank_top_k"] = retry_rerank_top_k
            raw["evidence_judgement"] = state["evidence_judgement"]
            raw["visual_asset_count"] = visual_asset_count
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
    ) -> str | None:
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
        if state.get("intent") == "project_overview":
            return "PROJECT_OVERVIEW_INSUFFICIENT_NO_HEAVY_RETRY"
        if retry_count >= 1:
            return "RETRY_LIMIT"
        return None

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

    def _retry_strategy_for_status(
        self,
        evidence_status: str,
        judgement: dict[str, Any],
        state: RetrievalGraphState,
    ) -> tuple[list[str], list[str], str]:
        """按证据状态选择一次性补检索策略。"""

        suggested_retrievers = list(judgement.get("suggested_retrievers") or [])
        if evidence_status == EVIDENCE_EMPTY:
            default_retrievers = ["ripgrep", "keyword", "milvus", "project_metadata", "page_index"]
        elif evidence_status == EVIDENCE_WEAK_ONLY:
            default_retrievers = ["page_index", "ripgrep", "milvus", "keyword"]
        elif evidence_status == EVIDENCE_PARTIAL:
            default_retrievers = ["milvus", "ripgrep", "page_index", "keyword"]
        elif evidence_status == EVIDENCE_CONFLICTED:
            default_retrievers = ["project_metadata", "ripgrep", "page_index", "keyword"]
        else:
            return [], [], "evidence_enough"

        retry_retrievers = self._filter_available_retrievers([*suggested_retrievers, *default_retrievers])
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
        missing_aspects = [str(item).strip() for item in (judgement.get("missing_aspects") or []) if str(item).strip()]
        candidates: list[str] = []
        candidates.extend(suggested_queries)
        candidates.extend(f"{state['question']} {aspect}" for aspect in missing_aspects[:3])
        if evidence_status == EVIDENCE_EMPTY:
            profile = state.get("query_profile", {}) or {}
            profile_terms = [
                *list(profile.get("project_name_candidates") or [])[:3],
                *list(profile.get("entities") or [])[:6],
                *list(profile.get("keywords") or [])[:8],
            ]
            candidates.append(state["question"])
            if profile_terms:
                candidates.append(" ".join(str(item) for item in profile_terms))
            candidates.extend(state.get("sub_queries", [])[:2])
        elif evidence_status == EVIDENCE_WEAK_ONLY:
            candidates.append(f"{state['question']} 正文 参数 流程 设备关系")
            candidates.extend(state.get("sub_queries", [])[:2])
        elif evidence_status == EVIDENCE_PARTIAL:
            candidates.append(state["question"])
        elif evidence_status == EVIDENCE_CONFLICTED:
            candidates.append(f"{state['question']} 版本 审核状态 来源 发布时间 优先级")
        if not candidates:
            candidates = self._build_retry_queries([], state)
        return list(dict.fromkeys(item for item in candidates if item))[:4]

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
        if not candidates:
            candidates.append(state["question"])
            candidates.extend(state.get("sub_queries", [])[:2])
        profile = state.get("query_profile", {}) or {}
        profile_terms = [*list(profile.get("entities") or [])[:6], *list(profile.get("keywords") or [])[:8]]
        if profile_terms and len(candidates) < 4:
            candidates.append(" ".join(str(item) for item in profile_terms))
        limit = 1 if state.get("intent") == "project_overview" else 4
        return list(dict.fromkeys(item for item in candidates if item))[:limit]

    def _merge_evidences_by_source(self, evidence_groups: list[list[Evidence]], limit: int) -> list[Evidence]:
        """按文档、chunk、页码和图号去重，保留最高分证据。"""

        by_source: dict[tuple[int, int, int | None, str | None], Evidence] = {}
        for group in evidence_groups:
            for evidence in group:
                key = (evidence.document_id, evidence.chunk_id, evidence.page_number, evidence.drawing_no)
                existing = by_source.get(key)
                if existing is None or evidence.score > existing.score:
                    by_source[key] = evidence
        return sorted(by_source.values(), key=lambda item: item.score, reverse=True)[:limit]

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
            "question": self._clip(state.get("question", ""), 300),
            "chat_type": state.get("chat_type"),
            "mode": state.get("mode"),
            "project_id": state.get("project_id"),
            "user_id": getattr(user, "id", None),
            "intent": state.get("intent"),
            "route": raw.get("route"),
            "skip_retrieval": bool(raw.get("skip_retrieval")),
            "direct_answer_type": state.get("direct_answer_type"),
            "reason": raw.get("route_reason"),
            "sub_queries": [self._clip(item, 160) for item in state.get("sub_queries", [])],
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
            "sub_queries": [self._clip(item, 160) for item in state.get("sub_queries", [])],
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
            "rerank_details": self._clip(str(state.get("rerank_details", [])), 1000),
            "evidence_judgement": state.get("evidence_judgement", {}),
            "evidence_evaluation": state.get("evidence_evaluation", {}),
            "answer_policy_gate": state.get("answer_policy_decision", {}),
            "answer_policy_decision": state.get("answer_policy_decision", {}),
            "retry_count": state.get("raw", {}).get("retry_count", 0),
            "retry_retrievers": state.get("raw", {}).get("retry_retrievers", []),
            "retry_query_count": state.get("raw", {}).get("retry_query_count", 0),
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
            "reason": self._clip(str(profile.get("reason") or ""), 240),
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
            "query_rewrites": data.get("query_rewrites", [])[:8],
            "confidence": data.get("confidence"),
            "reason": self._clip(str(data.get("reason") or ""), 240),
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
            "conflict_reason": self._clip(str(data.get("conflict_reason") or ""), 240),
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
            "evidence_judgement": state.get("evidence_judgement", {}),
            "evidence_evaluation": state.get("evidence_evaluation", {}),
            "answer_policy_gate": state.get("answer_policy_decision", {}),
            "answer_policy_decision": state.get("answer_policy_decision", {}),
            "retry_count": state.get("raw", {}).get("retry_count", 0),
            "retry_reason": state.get("raw", {}).get("retry_reason"),
            "retry_retrievers": state.get("raw", {}).get("retry_retrievers", []),
            "retry_query_count": state.get("raw", {}).get("retry_query_count", 0),
            "model_route": self._model_route_for_trace_key(state, trace_key or self._infer_trace_key(step, "")),
            "evidence": self._evidence_log_summary(state.get("evidences", [])),
            "visual_asset_count": state.get("visual_asset_count", 0),
            "answer_preview": self._clip(state.get("answer", ""), 300),
        }

    def _model_route_for_trace_key(self, state: RetrievalGraphState, trace_key: str) -> dict[str, Any]:
        """按 trace_key 取当前节点的模型路由信息。"""

        model_routes = state.get("model_routes", {})
        return model_routes.get(trace_key, {})

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
                    "content_preview": self._clip(evidence.content, 160),
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
        answer = str(state.get("answer") or "").strip()
        if not answer:
            answer = PROJECT_REFUSAL_ANSWER if state.get("chat_type") == "project_chat" else BASE_GENERAL_CONFIRM_ANSWER
        return {
            "answer": answer,
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
