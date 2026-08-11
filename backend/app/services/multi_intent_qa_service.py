"""多意图问答业务编排服务。"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.repositories.multi_intent_repository import MultiIntentRepository
from app.retrieval.schemas import Evidence
from app.services.multi_intent_models import IntentExecution, QuestionIntent, QuestionIntentPlan, SubQuestionExecution
from app.services.turn_execution_models import PlannedIntent, TurnExecutionPlan, plan_from_question_intent_plan

logger = logging.getLogger(__name__)

_ANSWERABILITY_FROM_ANSWER_TYPE = {
    "normal_answer": "answered",
    "general_llm": "answered",
    "preset": "answered",
    "limited_answer": "partially_answered",
    "partial_answer": "partially_answered",
    "partial_answer_with_llm": "partially_answered",
    "conflict_answer": "partially_answered",
    "refusal": "insufficient_evidence",
    "ask_general_confirm": "insufficient_evidence",
    "clarify": "unavailable",
    "cancelled": "unavailable",
}


class MultiIntentQaService:
    """负责多意图预算、执行边界、聚合和审计，不侵入单意图检索图。"""

    def __init__(self, graph: Any, db: Session | None) -> None:
        self.graph = graph
        self.db = db
        self.settings = get_settings()
        self.repository = MultiIntentRepository(db)

    def execute(
        self,
        question: str,
        plan: TurnExecutionPlan | QuestionIntentPlan,
        chat_type: str,
        mode: str,
        project_id: int | None,
        user: Any,
        *,
        business_id: str | int | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        """执行完整多意图问答并返回最终聚合结果。"""

        final_result: dict[str, Any] | None = None
        for event_name, payload in self.execute_events(
            question,
            plan,
            chat_type,
            mode,
            project_id,
            user,
            business_id=business_id,
            **options,
        ):
            if event_name == "result":
                final_result = payload
        if final_result is None:
            raise RuntimeError("multi_intent_result_missing")
        return final_result

    def execute_events(
        self,
        question: str,
        plan: TurnExecutionPlan | QuestionIntentPlan,
        chat_type: str,
        mode: str,
        project_id: int | None,
        user: Any,
        *,
        business_id: str | int | None = None,
        **options: Any,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """按真实完成顺序产出进度，最终结果仍按计划顺序聚合。"""

        resolved_plan = self._coerce_plan(question, plan, options)
        timeout_seconds = max(0.01, float(getattr(self.settings, "multi_intent_timeout_seconds", 90) or 90))
        progress_events: list[dict[str, Any]] = []
        sequence = 0

        def emit(event: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            progress_events.append(event)
            return "progress", event

        sequence += 1
        yield emit(self._turn_progress_event(resolved_plan, "turn.planned", "planning", sequence, status="success"))

        executor = ThreadPoolExecutor(max_workers=len(resolved_plan.intents), thread_name_prefix="qa-intent")
        futures: dict[Future[IntentExecution], PlannedIntent] = {}
        deadlines: dict[Future[IntentExecution], float] = {}
        executions: dict[str, IntentExecution] = {}
        try:
            for intent in resolved_plan.intents:
                sequence += 1
                yield emit(self._intent_progress_event(resolved_plan, intent, "intent.started", "understanding", sequence))
                sequence += 1
                yield emit(self._intent_progress_event(resolved_plan, intent, "intent.retrieving", "retrieving", sequence))
                future = executor.submit(
                    self._execute_intent,
                    resolved_plan,
                    intent,
                    chat_type,
                    mode,
                    project_id,
                    user,
                    business_id,
                    options,
                )
                futures[future] = intent
                deadlines[future] = time.monotonic() + timeout_seconds

            pending = set(futures)
            while pending:
                now = time.monotonic()
                expired = [future for future in pending if deadlines[future] <= now]
                for future in expired:
                    intent = futures[future]
                    future.cancel()
                    execution = self._timed_out_intent(intent, timeout_seconds)
                    executions[intent.id] = execution
                    pending.remove(future)
                    logger.warning(
                        "问答意图执行超时: business_id=%s turn_id=%s plan_version=%s intent_id=%s status=timeout elapsed_ms=%s",
                        business_id,
                        resolved_plan.turn_id,
                        resolved_plan.plan_version,
                        intent.id,
                        execution.elapsed_ms,
                    )
                    sequence += 1
                    yield emit(
                        self._intent_progress_event(
                            resolved_plan,
                            intent,
                            "intent.completed",
                            "filtering",
                            sequence,
                            execution_status="timeout",
                            answerability_status="unavailable",
                            status="failed",
                        )
                    )
                if not pending:
                    break
                wait_seconds = max(0.0, min(deadlines[future] for future in pending) - time.monotonic())
                completed, _ = wait(pending, timeout=wait_seconds, return_when=FIRST_COMPLETED)
                for future in completed:
                    intent = futures[future]
                    pending.remove(future)
                    try:
                        execution = future.result()
                    except Exception as exc:  # noqa: BLE001
                        execution = self._failed_intent(intent, "execution_error")
                        logger.exception(
                            "问答意图执行异常: business_id=%s turn_id=%s plan_version=%s intent_id=%s status=failed elapsed_ms=%s exception_type=%s",
                            business_id,
                            resolved_plan.turn_id,
                            resolved_plan.plan_version,
                            intent.id,
                            execution.elapsed_ms,
                            type(exc).__name__,
                        )
                    executions[intent.id] = execution
                    sequence += 1
                    yield emit(
                        self._intent_progress_event(
                            resolved_plan,
                            intent,
                            "intent.evidence_evaluated",
                            "filtering",
                            sequence,
                            execution_status=execution.status,
                            answerability_status=execution.answerability_status,
                            status="success" if execution.status == "completed" else "failed",
                        )
                    )
                    sequence += 1
                    yield emit(
                        self._intent_progress_event(
                            resolved_plan,
                            intent,
                            "intent.completed",
                            "filtering",
                            sequence,
                            execution_status=execution.status,
                            answerability_status=execution.answerability_status,
                            status="success" if execution.status == "completed" else "failed",
                        )
                    )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        sequence += 1
        yield emit(self._turn_progress_event(resolved_plan, "answer.composing", "answering", sequence))
        ordered = [executions[intent.id] for intent in resolved_plan.intents]
        combined = self._combine_results(
            question,
            resolved_plan,
            ordered,
            chat_type,
            mode,
            user,
            progress_events=progress_events,
            business_id=business_id,
            response_language=str(options.get("response_language") or "zh-CN"),
        )
        sequence += 1
        completed_event = self._turn_progress_event(
            resolved_plan,
            "answer.completed",
            "answering",
            sequence,
            status="success",
            execution_status="completed",
            answerability_status=str(combined.get("answerability_status") or "unavailable"),
        )
        progress_events.append(completed_event)
        combined["progress_events"] = list(progress_events)
        yield "result", combined

    def _execute_intent(
        self,
        plan: TurnExecutionPlan,
        intent: PlannedIntent,
        chat_type: str,
        mode: str,
        project_id: int | None,
        user: Any,
        business_id: str | int | None,
        options: dict[str, Any],
    ) -> IntentExecution:
        started_at = time.perf_counter()
        with self.repository.isolated_session() as child_db:
            graph = self.graph
            if child_db is not None:
                graph = type(self.graph)(child_db)
            sub_results: list[SubQuestionExecution] = []
            for sub_question in sorted(intent.sub_questions, key=lambda item: item.order):
                sub_started_at = time.perf_counter()
                try:
                    result = graph.run_single_intent(
                        sub_question.question,
                        chat_type,
                        mode,
                        project_id,
                        user,
                        turn_plan=plan,
                        planned_intent=intent,
                        **options,
                    )
                    sub_results.append(
                        self._successful_sub_result(
                            sub_question,
                            result,
                            elapsed_ms=int((time.perf_counter() - sub_started_at) * 1000),
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    elapsed_ms = int((time.perf_counter() - sub_started_at) * 1000)
                    logger.exception(
                        "问答子问题执行失败: business_id=%s turn_id=%s plan_version=%s intent_id=%s sub_question_id=%s status=failed elapsed_ms=%s exception_type=%s",
                        business_id,
                        plan.turn_id,
                        plan.plan_version,
                        intent.id,
                        sub_question.id,
                        elapsed_ms,
                        type(exc).__name__,
                    )
                    sub_results.append(
                        SubQuestionExecution(
                            sub_question=sub_question,
                            status="failed",
                            answerability_status="unavailable",
                            elapsed_ms=elapsed_ms,
                            answer="该子问题暂未获得结果。",
                            failure_reason="execution_error",
                        )
                    )
            return self._aggregate_intent_execution(intent, sub_results, int((time.perf_counter() - started_at) * 1000))

    def _successful_sub_result(
        self,
        sub_question: Any,
        result: dict[str, Any],
        *,
        elapsed_ms: int,
    ) -> SubQuestionExecution:
        answerability_status = self._answerability_status(
            str(result.get("answer_type") or ""),
            str(result.get("evidence_status") or ""),
        )
        citations = self._citation_ids_from_result(result)
        evidence_evaluation = self._evidence_evaluation(result)
        missing_information = [
            str(item)
            for item in evidence_evaluation.get("missing_aspects", [])
            if str(item).strip()
        ]
        risk_notices = self._risk_notices(answerability_status, str(result.get("answer_type") or ""), str(result.get("evidence_status") or ""))
        return SubQuestionExecution(
            sub_question=sub_question,
            status="completed",
            answerability_status=answerability_status,
            elapsed_ms=elapsed_ms,
            answer=str(result.get("answer") or "").strip(),
            evidence_summary=str(evidence_evaluation.get("reason") or result.get("evidence_status") or "").strip() or None,
            missing_information=list(dict.fromkeys(missing_information)),
            citations=citations,
            risk_notices=risk_notices,
            result=result,
        )

    def _aggregate_intent_execution(
        self,
        intent: PlannedIntent,
        sub_results: list[SubQuestionExecution],
        elapsed_ms: int,
    ) -> IntentExecution:
        completed_subs = [item for item in sub_results if item.status == "completed"]
        if completed_subs:
            status = "completed"
        elif any(item.status == "timeout" for item in sub_results):
            status = "timeout"
        else:
            status = "failed"

        answerability_status = self._aggregate_answerability_status(sub_results, status)
        answer_parts = self._merge_similar_values(
            ([item.answer] for item in completed_subs),
            similarity_threshold=0.92,
        )
        if not answer_parts:
            answer_parts = [self._default_execution_message(status)]
        missing_information = self._merge_similar_values(
            (item.missing_information for item in sub_results),
            similarity_threshold=0.68,
        )
        citations = self._merge_string_lists(item.citations for item in sub_results)
        risk_notices = self._merge_string_lists(item.risk_notices for item in sub_results)
        if status in {"failed", "timeout"} and completed_subs:
            risk_notices = list(dict.fromkeys([*risk_notices, "部分子问题执行未完成"]))
        return IntentExecution(
            intent=QuestionIntent(
                id=intent.id,
                order=intent.order,
                name=intent.name,
                original_target=intent.original_target,
                question=intent.question,
                sub_questions=[item.model_copy(deep=True) for item in intent.sub_questions],
            ),
            status=status,
            answerability_status=answerability_status,
            elapsed_ms=elapsed_ms,
            sub_results=sub_results,
            answer="\n".join(answer_parts),
            evidence_summary=self._first_non_empty(item.evidence_summary for item in sub_results),
            missing_information=missing_information,
            citations=citations,
            risk_notices=risk_notices,
            failure_reason=None if status == "completed" else status,
        )

    @staticmethod
    def _timed_out_intent(intent: PlannedIntent, timeout_seconds: float) -> IntentExecution:
        return IntentExecution(
            intent=QuestionIntent(
                id=intent.id,
                order=intent.order,
                name=intent.name,
                original_target=intent.original_target,
                question=intent.question,
                sub_questions=[item.model_copy(deep=True) for item in intent.sub_questions],
            ),
            status="timeout",
            answerability_status="unavailable",
            elapsed_ms=int(timeout_seconds * 1000),
            answer="该部分处理超时，暂未获得结果。",
            failure_reason="timeout",
        )

    @staticmethod
    def _failed_intent(intent: PlannedIntent, reason: str) -> IntentExecution:
        return IntentExecution(
            intent=QuestionIntent(
                id=intent.id,
                order=intent.order,
                name=intent.name,
                original_target=intent.original_target,
                question=intent.question,
                sub_questions=[item.model_copy(deep=True) for item in intent.sub_questions],
            ),
            status="failed",
            answerability_status="unavailable",
            elapsed_ms=0,
            answer="该部分暂未获得结果。",
            failure_reason=reason,
        )

    def _combine_results(
        self,
        question: str,
        plan: TurnExecutionPlan,
        executions: list[IntentExecution],
        chat_type: str,
        mode: str,
        user: Any,
        *,
        progress_events: list[dict[str, Any]],
        business_id: str | int | None,
        response_language: str = "zh-CN",
    ) -> dict[str, Any]:
        evidences: list[Evidence] = []
        evidence_keys: set[tuple[Any, ...]] = set()
        used_retrievers: list[str] = []
        traces: list[dict[str, Any]] = []
        intent_results: list[dict[str, Any]] = []
        first_result: dict[str, Any] | None = None

        for execution in executions:
            audit_sub_results: list[dict[str, Any]] = []
            for sub_result in execution.sub_results:
                result = sub_result.result
                if first_result is None and result:
                    first_result = result
                for evidence in result.get("evidences", []):
                    key = self._evidence_key(evidence)
                    if key not in evidence_keys:
                        evidence_keys.add(key)
                        evidences.append(evidence)
                for retriever in result.get("used_retrievers", []):
                    if retriever not in used_retrievers:
                        used_retrievers.append(retriever)
                for trace in result.get("agent_trace", []):
                    original_node_id = str(trace.get("node_id") or trace.get("step") or "node")
                    traces.append(
                        {
                            **trace,
                            "node_id": f"{execution.intent.id}:{sub_result.sub_question.id}:{original_node_id}",
                            "parent_node_id": f"sub-question:{sub_result.sub_question.id}",
                            "depends_on": [
                                f"sub-question:{item}" for item in sub_result.sub_question.depends_on
                            ],
                            "parallel_group_id": f"turn:{plan.turn_id}:intents",
                            "turn_id": plan.turn_id,
                            "plan_version": plan.plan_version,
                            "intent_id": execution.intent.id,
                            "intent_name": execution.intent.name,
                            "sub_question_id": sub_result.sub_question.id,
                        }
                    )
                raw = result.get("raw", {})
                audit_sub_results.append(
                    {
                        "sub_question_id": sub_result.sub_question.id,
                        "order": sub_result.sub_question.order,
                        "status": sub_result.status,
                        "answerability_status": sub_result.answerability_status,
                        "elapsed_ms": sub_result.elapsed_ms,
                        "retrieval_plan": raw.get("retrieval_plan", {}),
                        "evidence_evaluation": raw.get("evidence_evaluation", {}),
                        "failure_reason": sub_result.failure_reason,
                    }
                )
            intent_results.append(
                {
                    "id": execution.intent.id,
                    "name": execution.intent.name,
                    "order": execution.intent.order,
                    "status": execution.status,
                    "answerability_status": execution.answerability_status,
                    "elapsed_ms": execution.elapsed_ms,
                    "original_target": execution.intent.original_target,
                    "sub_questions": [item.question for item in execution.intent.sub_questions],
                    "sub_question_outcomes": [
                        {
                            "id": item.sub_question.id,
                            "order": item.sub_question.order,
                            "question": item.sub_question.question,
                            "depends_on": item.sub_question.depends_on,
                            "status": item.status,
                            "answerability_status": item.answerability_status,
                            "conclusion": item.answer,
                            "evidence_summary": item.evidence_summary,
                            "missing_information": item.missing_information,
                            "citations": item.citations,
                            "risk_notices": item.risk_notices,
                            "elapsed_ms": item.elapsed_ms,
                            "failure_reason": item.failure_reason,
                        }
                        for item in execution.sub_results
                    ],
                    "conclusion": execution.answer,
                    "evidence_summary": execution.evidence_summary,
                    "missing_information": execution.missing_information,
                    "citations": execution.citations,
                    "citation_ids": execution.citations,
                    "risk_notices": execution.risk_notices,
                    "failure_reason": execution.failure_reason,
                    "audit": {"sub_results": audit_sub_results},
                }
            )

        planned_intent_ids = list(plan.planned_intent_ids)
        executed_intent_ids = [item["id"] for item in intent_results]
        displayed_intent_ids = [item["id"] for item in intent_results if item["id"] in planned_intent_ids]
        answered_intent_ids = list(displayed_intent_ids)
        unexpected_intent_ids = [item for item in executed_intent_ids if item not in planned_intent_ids]
        if unexpected_intent_ids:
            logger.warning(
                "问答意图集合不一致，已移除额外意图: business_id=%s turn_id=%s plan_version=%s unexpected_intent_ids=%s",
                business_id,
                plan.turn_id,
                plan.plan_version,
                ",".join(unexpected_intent_ids),
            )
            intent_results = [item for item in intent_results if item["id"] in planned_intent_ids]
            progress_events[:] = [
                item
                for item in progress_events
                if item.get("intent_id") is None or item.get("intent_id") in planned_intent_ids
            ]
            displayed_intent_ids = [item["id"] for item in intent_results]
            answered_intent_ids = list(displayed_intent_ids)

        answerability_status = self._aggregate_top_level_answerability(executions)
        answer = self._render_final_answer(question, executions, plan, response_language=response_language)

        traces.append(
            {
                "sequence": len(traces) + 1,
                "step": "多意图执行汇总",
                "implementation": "multi_intent_orchestration",
                "status": "success",
                "elapsed_ms": sum(item.elapsed_ms for item in executions),
                "details": {
                    "plan_version": plan.plan_version,
                    "planned_intent_ids": planned_intent_ids,
                    "executed_intent_ids": executed_intent_ids,
                    "displayed_intent_ids": displayed_intent_ids,
                    "answered_intent_ids": answered_intent_ids,
                    "unexpected_intent_ids": unexpected_intent_ids,
                    "intent_results": intent_results,
                    "omitted_targets": plan.omitted_targets,
                },
            }
        )

        base = first_result or {
            "query_scope": "自动判断",
            "answer_policy": None,
            "evidence_status": "ERROR",
            "raw": {},
        }
        combined = {
            **base,
            "answer": answer,
            "chat_type": chat_type,
            "mode": mode,
            "answer_type": "multi_intent_answer",
            "intent_type": "multi_intent",
            "answerability_status": answerability_status,
            "query_scope": "；".join(
                dict.fromkeys(
                    str(sub_result.result.get("query_scope") or "自动判断")
                    for execution in executions
                    for sub_result in execution.sub_results
                    if sub_result.result
                )
            ) or "自动判断",
            "used_retrievers": used_retrievers,
            "agent_trace": traces,
            "trace_steps": traces,
            "evidences": evidences,
            "intent_results": intent_results,
            "raw": {
                **base.get("raw", {}),
                "plan_version": plan.plan_version,
                "turn_id": plan.turn_id,
                "memory_mode": plan.memory_mode,
                "memory_decision_reason": plan.memory_decision_reason,
                "inherited_context_ids": plan.referenced_context_ids,
                "planned_intent_ids": planned_intent_ids,
                "executed_intent_ids": executed_intent_ids,
                "displayed_intent_ids": displayed_intent_ids,
                "answered_intent_ids": answered_intent_ids,
                "unexpected_intent_ids": unexpected_intent_ids,
                "intent_results": intent_results,
            },
            "user": user,
        }
        self.graph.apply_final_answer_filter(combined, answer)
        combined.pop("user", None)
        return combined

    def _render_final_answer(
        self,
        question: str,
        executions: list[IntentExecution],
        plan: TurnExecutionPlan,
        *,
        response_language: str,
    ) -> str:
        if len(executions) == 1:
            return self._render_single_intent_answer(executions[0], response_language=response_language)

        all_insufficient = all(item.answerability_status == "insufficient_evidence" for item in executions)
        if all_insufficient:
            missing = self._merge_string_lists(item.missing_information for item in executions)
            lines = ["当前资料不足，未获得明确答案。"]
            if missing:
                lines.append(f"缺少资料：{'；'.join(missing)}。")
            lines.append("请补充相关资料后重试。")
            return "\n".join(lines)

        sections = [
            f"## {execution.intent.name}\n{self._render_single_intent_answer(execution, response_language=response_language)}"
            for execution in executions
        ]
        unresolved = [
            execution.intent.name
            for execution in executions
            if execution.answerability_status in {"partially_answered", "insufficient_evidence", "unavailable"}
        ]
        if plan.omitted_targets:
            unresolved.extend(plan.omitted_targets)
        if unresolved:
            sections.append(f"说明：未完整回答项包括 {'；'.join(dict.fromkeys(unresolved))}。")
        return "\n\n".join(sections)

    def _render_single_intent_answer(self, execution: IntentExecution, *, response_language: str) -> str:
        answer = execution.answer.strip() or self._default_execution_message(execution.status)
        if execution.answerability_status == "insufficient_evidence":
            if execution.missing_information:
                return f"{answer}\n缺少资料：{'；'.join(execution.missing_information)}。"
            return answer
        if execution.answerability_status == "partially_answered":
            if execution.missing_information:
                return f"{answer}\n未回答部分：{'；'.join(execution.missing_information)}。"
            if execution.status in {"failed", "timeout"}:
                return f"{answer}\n说明：部分子问题执行未完成。"
            return answer
        if execution.answerability_status == "unavailable" and execution.status in {"failed", "timeout"}:
            return self._default_execution_message(execution.status)
        return answer

    def _coerce_plan(
        self,
        question: str,
        plan: TurnExecutionPlan | QuestionIntentPlan,
        options: dict[str, Any],
    ) -> TurnExecutionPlan:
        if isinstance(plan, TurnExecutionPlan):
            return plan
        turn_context = options.get("turn_context")
        return plan_from_question_intent_plan(
            plan,
            turn_id=getattr(turn_context, "turn_id", None),
            original_question=str(getattr(turn_context, "original_question", question) or question),
            effective_question=str(getattr(turn_context, "effective_question", question) or question),
            memory_mode=str(getattr(turn_context, "memory_mode", getattr(turn_context, "memory_trigger_mode", "skip")) or "skip"),
            stable_scope=dict(getattr(turn_context, "stable_scope", {}) or {}),
            referenced_context_ids=list(getattr(turn_context, "memory_referenced_context_ids", []) or []),
            topic_shift=dict((getattr(turn_context, "memory_trace", {}) or {}).get("topic_shift") or {}),
            memory_decision_reason=str((getattr(turn_context, "memory_trace", {}) or {}).get("decision_reason") or ""),
        )

    def _turn_progress_event(
        self,
        plan: TurnExecutionPlan,
        event_type: str,
        stage: str,
        sequence: int,
        *,
        status: str = "running",
        execution_status: str = "completed",
        answerability_status: str = "unavailable",
    ) -> dict[str, Any]:
        title = "正在整理回答内容" if stage == "answering" else "正在规划资料检索方式"
        if event_type == "turn.planned":
            title = "正在规划资料检索方式"
        detail = {
            "turn.planned": "已建立本轮执行计划",
            "answer.composing": "正在整理回答内容",
            "answer.completed": "已完成回答整理",
        }.get(event_type, "")
        return {
            "visible": True,
            "event_type": event_type,
            "turn_id": plan.turn_id,
            "plan_version": plan.plan_version,
            "stage": stage,
            "title": title,
            "status": status,
            "detail": detail,
            "sequence": sequence,
            "execution_status": execution_status,
            "answerability_status": answerability_status,
        }

    def _intent_progress_event(
        self,
        plan: TurnExecutionPlan,
        intent: PlannedIntent,
        event_type: str,
        stage: str,
        sequence: int,
        *,
        execution_status: str = "running",
        answerability_status: str = "unavailable",
        status: str = "running",
    ) -> dict[str, Any]:
        detail = "正在处理该意图"
        if event_type == "intent.retrieving":
            detail = "正在检索相关资料"
        elif event_type == "intent.evidence_evaluated":
            detail = self._answerability_detail(answerability_status)
        elif event_type == "intent.completed":
            detail = self._completion_detail(execution_status, answerability_status)
        return {
            "visible": True,
            "event_type": event_type,
            "turn_id": plan.turn_id,
            "plan_version": plan.plan_version,
            "intent_id": intent.id,
            "intent_name": intent.name,
            "intent_order": intent.order,
            "intent_total": len(plan.intents),
            "stage": stage,
            "title": intent.name,
            "status": status,
            "detail": detail,
            "sequence": sequence,
            "execution_status": execution_status,
            "answerability_status": answerability_status,
        }

    @staticmethod
    def _answerability_status(answer_type: str, evidence_status: str) -> str:
        normalized_answer_type = str(answer_type or "").strip()
        if normalized_answer_type in _ANSWERABILITY_FROM_ANSWER_TYPE:
            return _ANSWERABILITY_FROM_ANSWER_TYPE[normalized_answer_type]
        if evidence_status in {"PARTIAL", "WEAK_ONLY", "CONFLICTED"}:
            return "partially_answered"
        if evidence_status in {"EMPTY", "INVALID_QUERY"}:
            return "insufficient_evidence"
        return "answered" if normalized_answer_type else "unavailable"

    @staticmethod
    def _aggregate_answerability_status(sub_results: list[SubQuestionExecution], execution_status: str) -> str:
        completed = [item for item in sub_results if item.status == "completed"]
        if not completed:
            return "unavailable" if execution_status in {"failed", "timeout"} else "insufficient_evidence"
        answered = [item for item in completed if item.answerability_status == "answered"]
        partial = [item for item in completed if item.answerability_status == "partially_answered"]
        insufficient = [item for item in completed if item.answerability_status == "insufficient_evidence"]
        if len(answered) == len(sub_results) and execution_status == "completed":
            return "answered"
        if answered or partial:
            return "partially_answered"
        if insufficient:
            return "insufficient_evidence"
        return "unavailable"

    @staticmethod
    def _aggregate_top_level_answerability(executions: list[IntentExecution]) -> str:
        if all(item.answerability_status == "answered" for item in executions):
            return "answered"
        if any(item.answerability_status in {"answered", "partially_answered"} for item in executions):
            return "partially_answered"
        if any(item.answerability_status == "insufficient_evidence" for item in executions):
            return "insufficient_evidence"
        return "unavailable"

    @staticmethod
    def _answerability_detail(answerability_status: str) -> str:
        if answerability_status == "answered":
            return "已完成证据判断"
        if answerability_status == "partially_answered":
            return "资料不完整，已获得部分结果"
        if answerability_status == "insufficient_evidence":
            return "资料不足，未获得明确答案"
        return "暂未获得结果"

    @staticmethod
    def _completion_detail(execution_status: str, answerability_status: str) -> str:
        if execution_status == "timeout":
            return "处理超时，暂未获得结果"
        if execution_status == "failed":
            return "处理失败，暂未获得结果"
        if answerability_status == "answered":
            return "已获得答案"
        if answerability_status == "partially_answered":
            return "已获得部分结果"
        if answerability_status == "insufficient_evidence":
            return "资料不足，未获得明确答案"
        return "已处理完成"

    @staticmethod
    def _evidence_evaluation(result: dict[str, Any]) -> dict[str, Any]:
        raw = result.get("raw", {})
        if isinstance(raw.get("evidence_evaluation"), dict):
            return raw.get("evidence_evaluation", {})
        return {}

    def _citation_ids_from_result(self, result: dict[str, Any]) -> list[str]:
        return list(
            dict.fromkeys(
                ":".join(str(part) for part in self._evidence_key(evidence))
                for evidence in result.get("evidences", [])
            )
        )

    @staticmethod
    def _risk_notices(answerability_status: str, answer_type: str, evidence_status: str) -> list[str]:
        notices: list[str] = []
        if answerability_status == "partially_answered":
            notices.append("资料不完整")
        if answerability_status == "insufficient_evidence":
            notices.append("资料不足")
        if evidence_status == "CONFLICTED" or answer_type == "conflict_answer":
            notices.append("证据存在冲突")
        return notices

    @staticmethod
    def _default_execution_message(execution_status: str) -> str:
        if execution_status == "timeout":
            return "该部分处理超时，暂未获得结果。"
        if execution_status == "failed":
            return "该部分暂未获得结果。"
        return "资料不足，未获得明确答案。"

    @staticmethod
    def _merge_string_lists(groups: Any) -> list[str]:
        merged: list[str] = []
        for items in groups:
            for item in items:
                value = str(item).strip()
                if value and value not in merged:
                    merged.append(value)
        return merged

    @classmethod
    def _merge_similar_values(cls, groups: Any, *, similarity_threshold: float) -> list[str]:
        merged: list[str] = []
        for items in groups:
            for item in items:
                value = str(item).strip()
                if not value:
                    continue
                matched = False
                for index, existing in enumerate(merged):
                    if cls._is_similar_text(existing, value, threshold=similarity_threshold):
                        matched = True
                        if cls._preferred_text(value, existing) == value:
                            merged[index] = value
                        break
                if not matched:
                    merged.append(value)
        return merged

    @classmethod
    def _is_similar_text(cls, left: str, right: str, *, threshold: float) -> bool:
        normalized_left = cls._normalize_similarity_text(left)
        normalized_right = cls._normalize_similarity_text(right)
        if not normalized_left or not normalized_right:
            return False
        if normalized_left == normalized_right:
            return True
        if normalized_left in normalized_right or normalized_right in normalized_left:
            return True
        left_tokens = cls._text_tokens(normalized_left)
        right_tokens = cls._text_tokens(normalized_right)
        if not left_tokens or not right_tokens:
            return False
        overlap = len(left_tokens & right_tokens) / max(min(len(left_tokens), len(right_tokens)), 1)
        return overlap >= threshold

    @staticmethod
    def _preferred_text(left: str, right: str) -> str:
        left_score = (len(left), left.count("（") + left.count("("), left.count("：") + left.count(":"))
        right_score = (len(right), right.count("（") + right.count("("), right.count("：") + right.count(":"))
        return left if left_score >= right_score else right

    @staticmethod
    def _normalize_similarity_text(text: str) -> str:
        collapsed = re.sub(r"\s+", "", str(text or ""))
        return re.sub(r"[“”\"'`·,，。；;：:！？!?（）()【】\\[\\]<>《》]", "", collapsed)

    @staticmethod
    def _text_tokens(text: str) -> set[str]:
        ascii_tokens = {item.lower() for item in re.findall(r"[A-Za-z0-9]{2,}", text)}
        chinese_bigrams = {text[index : index + 2] for index in range(max(len(text) - 1, 0)) if re.search(r"[\u4e00-\u9fff]", text[index : index + 2])}
        return {token for token in {*ascii_tokens, *chinese_bigrams} if token}

    @staticmethod
    def _first_non_empty(values: Any) -> str | None:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return None

    @staticmethod
    def _evidence_key(evidence: Evidence) -> tuple[Any, ...]:
        return (
            evidence.source_type,
            evidence.knowledge_base_id,
            evidence.document_id,
            evidence.chunk_id,
            evidence.page_number,
        )
