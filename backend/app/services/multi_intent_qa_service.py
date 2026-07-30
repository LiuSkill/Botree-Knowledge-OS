"""多意图问答业务编排服务。"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.repositories.multi_intent_repository import MultiIntentRepository
from app.retrieval.schemas import Evidence
from app.services.multi_intent_models import (
    IntentExecution,
    QuestionIntent,
    QuestionIntentPlan,
    SubQuestionExecution,
)

logger = logging.getLogger(__name__)


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
        plan: QuestionIntentPlan,
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
        plan: QuestionIntentPlan,
        chat_type: str,
        mode: str,
        project_id: int | None,
        user: Any,
        *,
        business_id: str | int | None = None,
        **options: Any,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """按真实完成顺序产出安全进度，最终结果仍按原始意图顺序聚合。"""

        timeout_seconds = max(0.01, float(getattr(self.settings, "multi_intent_timeout_seconds", 90) or 90))
        executor = ThreadPoolExecutor(max_workers=len(plan.intents), thread_name_prefix="qa-intent")
        futures: dict[Future[IntentExecution], QuestionIntent] = {}
        deadlines: dict[Future[IntentExecution], float] = {}
        executions: dict[str, IntentExecution] = {}
        try:
            for intent in plan.intents:
                yield "progress", self._progress_event(intent, len(plan.intents), "running")
                future = executor.submit(
                    self._execute_intent,
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
                    execution = IntentExecution(
                        intent=intent,
                        status="timeout",
                        elapsed_ms=int(timeout_seconds * 1000),
                        answer="该部分处理超时，暂未获得结果。",
                        failure_reason="timeout",
                    )
                    executions[intent.id] = execution
                    pending.remove(future)
                    logger.warning(
                        "问答意图执行超时: business_id=%s intent_id=%s status=timeout elapsed_ms=%s",
                        business_id,
                        intent.id,
                        execution.elapsed_ms,
                    )
                    yield "progress", self._progress_event(intent, len(plan.intents), "failed", "该部分处理超时")
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
                            "问答意图执行异常: business_id=%s intent_id=%s status=failed elapsed_ms=%s exception_type=%s",
                            business_id,
                            intent.id,
                            execution.elapsed_ms,
                            type(exc).__name__,
                        )
                    executions[intent.id] = execution
                    progress_status = "failed" if execution.status != "success" else "success"
                    detail = "该部分暂未获得结果" if progress_status == "failed" else "该部分已处理完成"
                    yield "progress", self._progress_event(intent, len(plan.intents), progress_status, detail)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        ordered = [executions[intent.id] for intent in plan.intents]
        yield "result", self._combine_results(
            question,
            plan,
            ordered,
            chat_type,
            mode,
            user,
            business_id=business_id,
            response_language=str(options.get("response_language") or "zh-CN"),
        )

    def _execute_intent(
        self,
        intent: QuestionIntent,
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
                        **options,
                    )
                    sub_results.append(
                        SubQuestionExecution(
                            sub_question=sub_question,
                            status="success",
                            elapsed_ms=int((time.perf_counter() - sub_started_at) * 1000),
                            answer=str(result.get("answer") or "").strip(),
                            result=result,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    elapsed_ms = int((time.perf_counter() - sub_started_at) * 1000)
                    logger.exception(
                        "问答子问题执行失败: business_id=%s intent_id=%s sub_question_id=%s status=failed elapsed_ms=%s exception_type=%s",
                        business_id,
                        intent.id,
                        sub_question.id,
                        elapsed_ms,
                        type(exc).__name__,
                    )
                    sub_results.append(
                        SubQuestionExecution(
                            sub_question=sub_question,
                            status="failed",
                            elapsed_ms=elapsed_ms,
                            answer="该子问题暂未获得结果。",
                            failure_reason="execution_error",
                        )
                    )
            successful = [item for item in sub_results if item.status == "success"]
            status = "success" if successful else "failed"
            answer_parts = [f"### {item.sub_question.question}\n{item.answer}" for item in sub_results]
            answer_parts.append(
                f"小结：已完成 {len(successful)}/{len(sub_results)} 个子问题。"
            )
            return IntentExecution(
                intent=intent,
                status=status,
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
                sub_results=sub_results,
                answer="\n\n".join(answer_parts),
                failure_reason="partial_failure" if successful and len(successful) != len(sub_results) else (None if successful else "execution_error"),
            )

    @staticmethod
    def _failed_intent(intent: QuestionIntent, reason: str) -> IntentExecution:
        return IntentExecution(
            intent=intent,
            status="failed",
            elapsed_ms=0,
            answer="该部分暂未获得结果。",
            failure_reason=reason,
        )

    def _combine_results(
        self,
        question: str,
        plan: QuestionIntentPlan,
        executions: list[IntentExecution],
        chat_type: str,
        mode: str,
        user: Any,
        *,
        business_id: str | int | None,
        response_language: str = "zh-CN",
    ) -> dict[str, Any]:
        evidences: list[Evidence] = []
        evidence_keys: set[tuple[Any, ...]] = set()
        used_retrievers: list[str] = []
        traces: list[dict[str, Any]] = []
        intent_results: list[dict[str, Any]] = []
        risk_messages: list[str] = []
        first_result: dict[str, Any] | None = None

        for execution in executions:
            citation_ids: list[str] = []
            audit_sub_results: list[dict[str, Any]] = []
            for sub_result in execution.sub_results:
                result = sub_result.result
                if first_result is None and result:
                    first_result = result
                for evidence in result.get("evidences", []):
                    key = self._evidence_key(evidence)
                    citation_ids.append(":".join(str(part) for part in key))
                    if key not in evidence_keys:
                        evidence_keys.add(key)
                        evidences.append(evidence)
                for retriever in result.get("used_retrievers", []):
                    if retriever not in used_retrievers:
                        used_retrievers.append(retriever)
                for trace in result.get("agent_trace", []):
                    traces.append(
                        {
                            **trace,
                            "intent_id": execution.intent.id,
                            "sub_question_id": sub_result.sub_question.id,
                        }
                    )
                raw = result.get("raw", {})
                audit_sub_results.append(
                    {
                        "sub_question_id": sub_result.sub_question.id,
                        "order": sub_result.sub_question.order,
                        "status": sub_result.status,
                        "elapsed_ms": sub_result.elapsed_ms,
                        "retrieval_plan": raw.get("retrieval_plan", {}),
                        "evidence_evaluation": raw.get("evidence_evaluation", {}),
                        "failure_reason": sub_result.failure_reason,
                    }
                )
                if str(result.get("answer_type") or "") not in {"normal_answer", "general_llm", "preset"}:
                    risk_messages.append("部分子问题资料不足")
            if execution.status != "success" or execution.failure_reason:
                risk_messages.append("部分任务未完整处理")
            intent_results.append(
                {
                    "id": execution.intent.id,
                    "name": execution.intent.name,
                    "order": execution.intent.order,
                    "status": "success" if execution.status == "success" else "failed",
                    "elapsed_ms": execution.elapsed_ms,
                    "original_target": execution.intent.original_target,
                    "sub_questions": [item.question for item in execution.intent.sub_questions],
                    "dependencies": {item.id: item.depends_on for item in execution.intent.sub_questions},
                    "citation_ids": list(dict.fromkeys(citation_ids)),
                    "failure_reason": execution.failure_reason,
                    "audit": {"sub_results": audit_sub_results},
                }
            )

        uses_english = response_language == "en-US"
        if plan.omitted_targets:
            risk_messages.append(
                f"{len(plan.omitted_targets)} additional target(s) were not processed due to the execution budget"
                if uses_english
                else f"另有 {len(plan.omitted_targets)} 个目标因执行预算未处理"
            )
        intent_answers = [
            {"name": execution.intent.name, "answer": execution.answer}
            for execution in executions
        ]
        try:
            synthesis = (
                self.graph.answer_generator.synthesize_multi_intent(
                    question,
                    intent_answers,
                    {"response_language": response_language},
                )
                if uses_english
                else self.graph.answer_generator.synthesize_multi_intent(question, intent_answers)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "多意图综合结论生成失败，使用安全降级: business_id=%s status=fallback exception_type=%s",
                business_id,
                type(exc).__name__,
            )
            synthesis = (
                "The results above are based on the currently available materials."
                if uses_english
                else "以上为各项任务基于当前可用资料得到的结果。"
            )
            risk_messages.append("The synthesis used a fallback response" if uses_english else "综合结论使用了降级表达")

        calculation_hints = ("合计", "汇总", "总计", "平均", "差值", "比例", "换算")
        if risk_messages and any(hint in question for hint in calculation_hints):
            synthesis = f"{synthesis}\n计算口径：上述结果属于可用信息汇总值。"
        answer_parts = []
        if plan.understanding:
            answer_parts.append(plan.understanding)
        answer_parts.extend(f"## {execution.intent.name}\n{execution.answer}" for execution in executions)
        answer_parts.append(f"## {'Summary' if uses_english else '综合结论'}\n{synthesis}")
        if risk_messages:
            answer_parts.append(
                f"Note: {'; '.join(dict.fromkeys(risk_messages))}. This answer is based on the currently available information."
                if uses_english
                else f"说明：{'；'.join(dict.fromkeys(risk_messages))}。以上内容基于当前可用信息回答。"
            )
        answer = "\n\n".join(answer_parts)

        traces.append(
            {
                "sequence": len(traces) + 1,
                "step": "多意图执行汇总",
                "implementation": "multi_intent_orchestration",
                "status": "success",
                "elapsed_ms": sum(item.elapsed_ms for item in executions),
                "details": {
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
            "raw": {**base.get("raw", {}), "intent_results": intent_results},
            "user": user,
        }
        self.graph.apply_final_answer_filter(combined, answer)
        combined.pop("user", None)
        return combined

    @staticmethod
    def _evidence_key(evidence: Evidence) -> tuple[Any, ...]:
        return (
            evidence.source_type,
            evidence.knowledge_base_id,
            evidence.document_id,
            evidence.chunk_id,
            evidence.page_number,
        )

    @staticmethod
    def _progress_event(
        intent: QuestionIntent,
        total: int,
        status: str,
        detail: str | None = None,
    ) -> dict[str, Any]:
        return {
            "visible": True,
            "stage": "retrieving",
            "title": intent.name,
            "status": status,
            "detail": detail or f"正在处理 {intent.order}/{total}",
            "sequence": intent.order,
            "intent_id": intent.id,
            "intent_name": intent.name,
            "intent_order": intent.order,
            "intent_total": total,
        }
