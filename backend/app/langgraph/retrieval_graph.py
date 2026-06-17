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

from app.agent.answer_generator import AnswerGenerator
from app.langgraph.state import RetrievalGraphState
from app.models.user import User
from app.retrieval.merger import EvidenceMerger
from app.retrieval.router import RetrievalRouter
from app.retrieval.schemas import Evidence
from app.services.qwen_orchestration_service import QwenOrchestrationService
from app.services.reranker_service import RerankerService
from app.services.retrieval_planner_service import RetrievalPlannerService
from app.services.visual_evidence_service import VisualEvidenceService

logger = logging.getLogger(__name__)

TRACE_NODE_STEPS = {
    "intent": "Qwen意图识别",
    "query_decompose": "Qwen查询拆解",
    "planner": "Retrieval Planner检索规划",
    "retrieval": "计划检索执行与Reranker重排",
    "evidence_judge": "Qwen证据判断",
    "visual_reading": "视觉图纸阅读",
    "answer": "Qwen回答生成",
}

INTENT_LABELS = {
    "project_qa": "项目资料问答",
    "knowledge_qa": "知识问答",
    "project_overview": "项目概览问答",
    "exact_lookup": "精确定位问答",
    "page_location": "页级定位问答",
    "graph_reasoning": "图谱推理问答",
}

RETRIEVER_PLAN_LABELS = {
    "milvus": "语义检索",
    "keyword": "关键词检索",
    "page_index": "页级检索",
    "graphrag": "图谱检索",
}

RETRIEVER_HIT_LABELS = {
    "milvus": "Milvus",
    "keyword": "Keyword",
    "page_index": "PageIndex",
    "graphrag": "GraphRAG",
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
        self.planner = RetrievalPlannerService(db)
        self.retrieval_router = RetrievalRouter(db)
        self.answer_generator = AnswerGenerator(db)
        self.merger = EvidenceMerger()
        self.reranker = RerankerService(db)
        self.visual_evidence_service = VisualEvidenceService(db)
        self._compiled_graph = self._try_compile_langgraph()

    def prepare(self, question: str, chat_type: str, mode: str, project_id: int | None, user: User) -> RetrievalGraphState:
        """
        先执行到证据判断阶段，为流式回答准备可复用的检索上下文。
        """

        state = self._build_initial_state(question, chat_type, mode, project_id, user, backend="sequential_prepare")
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
    ) -> Iterator[tuple[str, Any]]:
        """
        流式执行检索准备阶段，按 LangGraph 节点产出前端 Thinking 所需的 trace_delta。
        """

        state = self._build_initial_state(question, chat_type, mode, project_id, user, backend="sequential_prepare_stream")
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

            if trace_key == "retrieval":
                for visual_delta in self._visual_reading_trace_deltas(state):
                    yield "trace_delta", visual_delta

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

    def run(self, question: str, chat_type: str, mode: str, project_id: int | None, user: User) -> dict[str, Any]:
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
    ) -> RetrievalGraphState:
        """构建问答图初始状态。"""

        return {
            "question": question,
            "chat_type": chat_type,
            "mode": mode,
            "project_id": project_id,
            "user": user,
            "trace": [],
            "raw": {
                "langgraph_backend": backend,
                "run_id": uuid.uuid4().hex,
            },
        }

    def _prepare_node_specs(self) -> list[tuple[str, Callable[[RetrievalGraphState], RetrievalGraphState]]]:
        """返回检索准备阶段的节点顺序与前端展示阶段标识。"""

        return [
            ("intent", self._intent_node),
            ("query_decompose", self._query_decompose_node),
            ("planner", self._planner_node),
            ("retrieval", self._retrieval_node),
            ("evidence_judge", self._evidence_judge_node),
        ]

    def _sequential_node_specs(self) -> list[tuple[str, Callable[[RetrievalGraphState], RetrievalGraphState]]]:
        """返回完整同步问答阶段的节点顺序与前端展示阶段标识。"""

        return [*self._prepare_node_specs(), ("answer", self._answer_node)]

    def _run_until_evidence_judge(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """按固定顺序运行到证据判断结束。"""

        for trace_key, node in self._prepare_node_specs():
            state.setdefault("raw", {})["active_trace_display_key"] = trace_key
            state = node(state)
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
        return state

    def _append_answer_trace(
        self,
        state: RetrievalGraphState,
        answer: str,
        elapsed_ms: int | None = None,
        trace_sequence: int | None = None,
    ) -> RetrievalGraphState:
        """为流式收敛后的最终答案补写回答节点 trace。"""

        step = "Qwen回答生成"
        implementation = "answer_generator"
        input_summary = self._state_log_context(state)
        state["answer"] = answer
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
            "details": self._trace_details(step, state),
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
            graph.add_node("intent", self._intent_node)
            graph.add_node("query_decompose", self._query_decompose_node)
            graph.add_node("retrieval_planner", self._planner_node)
            graph.add_node("retrieval", self._retrieval_node)
            graph.add_node("evidence_judge", self._evidence_judge_node)
            graph.add_node("answer", self._answer_node)
            graph.set_entry_point("intent")
            graph.add_edge("intent", "query_decompose")
            graph.add_edge("query_decompose", "retrieval_planner")
            graph.add_edge("retrieval_planner", "retrieval")
            graph.add_edge("retrieval", "evidence_judge")
            graph.add_edge("evidence_judge", "answer")
            graph.add_edge("answer", END)
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
                "details": self._trace_details(step, next_state),
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
                "details": self._trace_details(step, state),
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

    def _intent_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        Qwen 意图识别节点。

        参数:
            state: 当前状态

        返回:
            写入 intent 的状态
        """

        def run() -> RetrievalGraphState:
            state["intent"] = self.qwen.detect_intent(state["question"], state["chat_type"], state["mode"])
            return state

        return self._with_trace(state, "Qwen意图识别", "qwen", run)

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
            return state

        return self._with_trace(state, "Qwen查询拆解", "qwen", run)

    def _planner_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        Retrieval Planner 节点。

        参数:
            state: 当前状态

        返回:
            写入 retrieval_plan 和 query_features 的状态
        """

        def run() -> RetrievalGraphState:
            plan = self.planner.plan(
                query=state["question"],
                sub_queries=state.get("sub_queries", [state["question"]]),
                intent=state.get("intent", "knowledge_qa"),
                chat_type=state["chat_type"],
                mode=state["mode"],
                project_id=state["project_id"],
                available_retrievers=self.retrieval_router.available_retrievers(),
            )
            plan_dict = plan.to_dict()
            state["retrieval_plan"] = plan_dict
            state["query_features"] = plan.query_features
            state["planned_retrievers"] = plan.selected_retrievers
            state["skipped_retrievers"] = plan.skipped_retrievers
            state["skip_reasons"] = plan.skip_reasons
            state["fallback_ladder"] = plan.fallback_ladder
            state.setdefault("raw", {})["retrieval_plan"] = plan_dict
            state["raw"]["query_features"] = plan.query_features
            state["raw"]["planned_retrievers"] = plan.selected_retrievers
            state["raw"]["skipped_retrievers"] = plan.skipped_retrievers
            state["raw"]["fallback_ladder"] = plan.fallback_ladder
            logger.info(
                "Retrieval Planner完成: run_id=%s step=retrieval_planner implementation=%s status=success intent=%s rule_id=%s query_features=%s selected_retrievers=%s skipped_retrievers=%s skip_reasons=%s fallback_ladder=%s confidence=%s qwen_used=%s",
                state.get("raw", {}).get("run_id"),
                plan.strategy,
                state.get("intent"),
                plan.rule_id,
                self._clip(str(plan.query_features), 1200),
                plan.selected_retrievers,
                plan.skipped_retrievers,
                self._clip(str(plan.skip_reasons), 1200),
                plan.fallback_ladder,
                plan.confidence,
                plan.qwen_used,
            )
            return state

        return self._with_trace(state, "Retrieval Planner检索规划", "planner", run)

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
            max_sub_queries = 4 if state.get("intent") == "project_overview" else 3
            sub_queries = state.get("sub_queries", [state["question"]])[:max_sub_queries]

            for sub_query_index, sub_query in enumerate(sub_queries, start=1):
                logger.info(
                    "LangGraph子查询开始: run_id=%s step=retrieval implementation=router status=started intent=%s sub_query_index=%s sub_query_total=%s query=%s planned_retrievers=%s fallback_ladder=%s",
                    state.get("raw", {}).get("run_id"),
                    state.get("intent"),
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
                    limit=5,
                    chat_type=state["chat_type"],
                    fallback_retrievers=fallback_retrievers,
                    fallback_ladder=fallback_ladder,
                    query_features=state.get("query_features", {}),
                    skip_reasons=skip_reasons,
                    run_id=state.get("raw", {}).get("run_id"),
                    intent=state.get("intent"),
                    sub_query_index=sub_query_index,
                    sub_query_total=len(sub_queries),
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
                    state.get("intent"),
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

            merged = self.merger.merge(evidence_groups, 15)
            evidences = self.reranker.rerank(state["question"], merged, 5)
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
            state["raw"]["fallback_ladder"] = fallback_ladder
            state["raw"]["fallback_used"] = state["fallback_used"]
            state["raw"]["fallback_trigger_reason"] = fallback_trigger_reason
            state["raw"]["retriever_hits"] = retriever_hits
            state["raw"]["retriever_elapsed_ms"] = retriever_elapsed
            state["raw"]["retriever_top_scores"] = retriever_top_scores
            state["raw"]["visual_asset_count"] = visual_asset_count
            return state

        return self._with_trace(state, "计划检索执行与Reranker重排", "router+reranker", run)

    def _evidence_judge_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        Qwen 证据判断节点。

        参数:
            state: 当前状态

        返回:
            写入 evidence_judgement 的状态
        """

        def run() -> RetrievalGraphState:
            state["evidence_judgement"] = self.qwen.judge_evidence(state["question"], state.get("evidences", []))
            return state

        return self._with_trace(state, "Qwen证据判断", "qwen", run)

    def _answer_node(self, state: RetrievalGraphState) -> RetrievalGraphState:
        """
        回答生成节点。

        参数:
            state: 当前状态

        返回:
            写入 answer 的状态
        """

        def run() -> RetrievalGraphState:
            state["answer"] = self.answer_generator.generate(state["question"], state.get("evidences", []))
            return state

        return self._with_trace(state, "Qwen回答生成", "answer_generator", run)

    def _state_log_context(self, state: RetrievalGraphState) -> dict[str, Any]:
        """
        生成节点输入日志摘要。

        参数:
            state: 当前状态

        返回:
            安全可记录的输入摘要
        """

        user = state.get("user")
        return {
            "question": self._clip(state.get("question", ""), 300),
            "chat_type": state.get("chat_type"),
            "mode": state.get("mode"),
            "project_id": state.get("project_id"),
            "user_id": getattr(user, "id", None),
            "intent": state.get("intent"),
            "sub_queries": [self._clip(item, 160) for item in state.get("sub_queries", [])],
            "query_features": state.get("query_features", {}),
            "retrieval_plan": state.get("retrieval_plan", {}),
            "planned_retrievers": state.get("planned_retrievers", []),
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
            "sub_queries": [self._clip(item, 160) for item in state.get("sub_queries", [])],
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
            "evidence": self._evidence_log_summary(state.get("evidences", [])),
            "visual_asset_count": state.get("visual_asset_count", 0),
            "answer_preview": self._clip(state.get("answer", ""), 300),
        }

    def _trace_details(self, step: str, state: RetrievalGraphState) -> dict[str, Any]:
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
            "sub_queries": [self._clip(item, 160) for item in state.get("sub_queries", [])],
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
            "evidence": self._evidence_log_summary(state.get("evidences", [])),
            "visual_asset_count": state.get("visual_asset_count", 0),
            "answer_preview": self._clip(state.get("answer", ""), 300),
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
            "details": self._trace_details(step, state),
        }
        trace_item["display_text"] = self._trace_success_text("visual_reading", state, trace_item)
        state.setdefault("trace", []).append(trace_item)
        return [running_delta, self.trace_delta_payload(trace_item)]

    def _infer_trace_key(self, step: str, implementation: str) -> str:
        if implementation == "planner":
            return "planner"
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
            return "正在理解问题..."
        if trace_key == "query_decompose":
            return "正在拆解查询..."
        if trace_key == "planner":
            return "正在规划检索方式..."
        if trace_key == "retrieval":
            return f"正在检索{self._material_scope_label(state)}..."
        if trace_key == "evidence_judge":
            return "正在整理证据..."
        if trace_key == "visual_reading":
            return "正在阅读图纸..."
        if trace_key == "answer":
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
            return f"已识别为：{INTENT_LABELS.get(intent, intent)}"
        if trace_key == "query_decompose":
            sub_queries = state.get("sub_queries", []) or [state.get("question", "")]
            query_text = "；".join(self._clip(item, 120) for item in sub_queries)
            return f"生成 {len(sub_queries)} 个检索问题：{query_text}"
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
            return f"合并后保留 {evidence_count} 条有效证据\n关联 {visual_asset_count} 张图纸图片"
        if trace_key == "visual_reading":
            visual_asset_count = int(state.get("visual_asset_count") or 0)
            return f"已输入 {visual_asset_count} 张图纸图片给视觉模型"
        if trace_key == "answer":
            return f"回答已生成\n{self._answer_basis_text(state)}"
        return "已执行"

    def _trace_failed_text(self, trace_key: str) -> str:
        stage_label = {
            "intent": "理解问题",
            "query_decompose": "拆解查询",
            "planner": "规划检索方式",
            "retrieval": "检索资料",
            "evidence_judge": "整理证据",
            "visual_reading": "阅读图纸",
            "answer": "生成回答",
        }.get(trace_key, "执行步骤")
        return f"{stage_label}失败，请稍后重试"

    def _retriever_hit_text(self, state: RetrievalGraphState) -> str:
        hits = state.get("retriever_hits", {})
        ordered_names = [name for name in ("milvus", "keyword", "page_index", "graphrag") if name in hits]
        ordered_names.extend(name for name in hits if name not in ordered_names)
        if not ordered_names:
            return "未命中有效资料"
        return "\n".join(
            f"{RETRIEVER_HIT_LABELS.get(name, name)} 命中 {int(hits.get(name) or 0)} 条" for name in ordered_names
        )

    def _format_retrievers(self, retrievers: list[str], labels: dict[str, str], separator: str) -> str:
        return separator.join(labels.get(item, item) for item in retrievers if item)

    def _material_scope_label(self, state: RetrievalGraphState) -> str:
        return "项目资料" if state.get("chat_type") == "project_chat" else "基础知识库"

    def _answer_basis_text(self, state: RetrievalGraphState) -> str:
        if state.get("chat_type") == "project_chat":
            if int(state.get("visual_asset_count") or 0) > 0:
                return "基于 P&ID 图纸和项目资料组织答案"
            return "基于项目资料组织答案"
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

        return {
            "answer": state["answer"],
            "chat_type": state["chat_type"],
            "mode": state["mode"],
            "query_scope": state.get("query_scope") or "自动判断",
            "used_retrievers": state.get("used_retrievers", []),
            "agent_trace": state.get("trace", []),
            "trace_steps": state.get("trace", []),
            "evidences": state.get("evidences", []),
            "raw": {
                **state.get("raw", {}),
                "intent": state.get("intent"),
                "sub_queries": state.get("sub_queries", []),
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
                "visual_asset_count": state.get("visual_asset_count", 0),
            },
        }
