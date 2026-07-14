"""
Retrieval Router

负责：
1. 统一执行权限校验和检索范围计算
2. 按 Planner 结果分阶段执行 Retriever，并在低质量时触发 fallback
3. 输出结构化检索日志、trace 字段和可审计的执行摘要
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import logging
import threading
import time
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.exceptions import AppException
from app.core.security_levels import allowed_security_levels, user_max_security_level
from app.models.document import Document, DocumentChunk
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User
from app.retrieval.base import DEFAULT_RETRIEVER_TOP_K
from app.retrieval.merger import EvidenceMerger
from app.retrieval.query_utils import (
    boilerplate_multiplier,
    has_structured_lookup_anchor_support,
    is_structured_list_lookup_query,
    is_table_like_content,
)
from app.retrieval.retrievers.graph_retriever import GraphRAGRetriever
from app.retrieval.retrievers.keyword_retriever import KeywordRetriever
from app.retrieval.retrievers.milvus_retriever import MilvusHybridRetriever
from app.retrieval.retrievers.page_index_retriever import PageIndexRetriever
from app.retrieval.retrievers.project_metadata_retriever import ProjectMetadataRetriever
from app.retrieval.retrievers.ripgrep_retriever import RipgrepRetriever
from app.retrieval.schemas import Evidence
from app.retrieval.scope import normalize_retrieval_scope
from app.services.project_access_service import ProjectAccessService
from app.services.project_service import ProjectService
from app.services.evidence_access_guard_service import EvidenceAccessGuardService
from app.services.reranker_service import RerankerService

logger = logging.getLogger(__name__)

LOW_QUALITY_SCORE_THRESHOLD = 0.58
LOW_QUALITY_VALUABLE_EVIDENCE_THRESHOLD = 2
FUSED_EVIDENCE_TOP_K = 20
RERANKED_EVIDENCE_TOP_K = 10


class RetrievalRouter:
    """
    检索路由器

    职责：
    - 统一封装检索范围与权限控制
    - 执行 Planner 驱动的多阶段检索
    - 汇总 Retriever 执行明细和 fallback 结果
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.retrievers = self._enabled_retrievers(db)
        self.retriever_map = {retriever.name: retriever for retriever in self.retrievers}
        self.merger = EvidenceMerger()
        self.reranker = RerankerService(db)
        self.evidence_access_guard = EvidenceAccessGuardService(db)
        self._retriever_executor_max_workers = 6

    def search(
        self,
        query: str,
        mode: str,
        project_id: int | None,
        user: User,
        limit: int = DEFAULT_RETRIEVER_TOP_K,
        chat_type: str | None = None,
        execution_mode: str = "planner",
    ) -> dict[str, Any]:
        """
        执行检索入口。

        参数:
            query: 查询文本
            mode: 检索模式
            project_id: 项目ID
            user: 当前用户
            limit: 返回数量
            chat_type: 问答类型
            execution_mode: planner/all

        返回:
            检索结果与 Planner/执行 trace 信息
        """

        if execution_mode == "all":
            return self.search_all(query, mode, project_id, user, limit, chat_type)

        raise AppException("Planner 模式已由 RetrievalService 统一编排，请改用 RetrievalService.search()", status_code=500)

    def search_all(
        self,
        query: str,
        mode: str,
        project_id: int | None,
        user: User,
        limit: int = DEFAULT_RETRIEVER_TOP_K,
        chat_type: str | None = None,
    ) -> dict[str, Any]:
        """
        显式执行所有已启用 Retriever。

        参数:
            query: 查询文本
            mode: 检索模式
            project_id: 项目ID
            user: 当前用户
            limit: 返回数量
            chat_type: 问答类型

        返回:
            全量执行后的检索结果
        """

        effective_mode = self._prepare_scope(mode, project_id, chat_type, user)
        retriever_names = self.available_retrievers()
        (
            groups,
            retriever_hits,
            retriever_elapsed,
            retriever_top_scores,
            executed_retrievers,
            retriever_errors,
            retriever_timeouts,
        ) = self._execute_retrievers(
            query=query,
            effective_mode=effective_mode,
            project_id=project_id,
            user=user,
            retriever_names=retriever_names,
            limit=limit,
            planned_order=1,
            fallback_used=False,
            fallback_stage=0,
            fallback_trigger_reason="execution_mode=all",
            query_features=None,
        )
        finalized = self.finalize_retrieval(
            query=query,
            evidences=[item for group in groups for item in group],
            limit=limit,
            chat_type=chat_type,
            effective_mode=effective_mode,
            project_id=project_id,
            user=user,
        )
        return {
            "mode": effective_mode,
            "query_scope": self._scope_text(effective_mode),
            "planned_retrievers": retriever_names,
            "used_retrievers": list(dict.fromkeys(executed_retrievers)),
            "executed_retrievers": list(dict.fromkeys(executed_retrievers)),
            "skipped_retrievers": [],
            "skip_reasons": {},
            "fallback_ladder": [retriever_names],
            "fallback_used": [],
            "fallback_trigger_reason": [],
            "retriever_hits": retriever_hits,
            "retriever_elapsed_ms": retriever_elapsed,
            "retriever_top_scores": retriever_top_scores,
            "retriever_errors": retriever_errors,
            "retriever_timeouts": retriever_timeouts,
            "retrieval_plan": {
                "selected_retrievers": retriever_names,
                "fallback_retrievers": [],
                "fallback_ladder": [retriever_names],
                "reason": "execution_mode=all 显式执行全部 Retriever",
                "confidence": 1.0,
                "qwen_used": False,
                "strategy": "all",
                "rule_id": "all",
                "skipped_retrievers": [],
                "skip_reasons": {},
                "query_features": {},
            },
            **finalized,
        }

    def finalize_retrieval(
        self,
        query: str,
        evidences: list[Evidence],
        limit: int,
        *,
        chat_type: str | None,
        effective_mode: str,
        project_id: int | None,
        user: User,
    ) -> dict[str, Any]:
        """
        为 `/retrieval/*` 链路统一做合并去重、权限过滤和真实 reranker 重排。
        """

        merge_limit = FUSED_EVIDENCE_TOP_K
        merged_evidences = self._top_scored_evidences(self.merger.merge([evidences], merge_limit), merge_limit)
        rerank_candidates = self._top_scored_evidences(merged_evidences, FUSED_EVIDENCE_TOP_K)
        rerank_candidates, guard_details = self._guard_before_rerank(
            rerank_candidates,
            chat_type=chat_type,
            effective_mode=effective_mode,
            project_id=project_id,
            user=user,
        )
        rerank_candidates = self._top_scored_evidences(rerank_candidates, FUSED_EVIDENCE_TOP_K)
        reranked = self._top_scored_evidences(
            self.reranker.rerank(query, rerank_candidates, min(limit, RERANKED_EVIDENCE_TOP_K)),
            RERANKED_EVIDENCE_TOP_K,
        )
        return {
            "evidences": reranked,
            "rerank_details": self.reranker.last_details,
            "pre_rerank_guard": guard_details,
        }

    def execute_planned(
        self,
        query: str,
        mode: str,
        project_id: int | None,
        user: User,
        retriever_names: list[str],
        limit: int = DEFAULT_RETRIEVER_TOP_K,
        fallback_retrievers: list[str] | None = None,
        fallback_ladder: list[list[str]] | None = None,
        chat_type: str | None = None,
        query_features: dict[str, Any] | None = None,
        skip_reasons: dict[str, str] | None = None,
        run_id: str | None = None,
        intent: str | None = None,
        sub_query_index: int | None = None,
        sub_query_total: int | None = None,
        knowledge_scope: str | None = None,
        remaining_budget_ms: int | None = None,
        min_stage_budget_ms: int | None = None,
        retrieval_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        按 Planner 结果分阶段执行检索。

        参数:
            query: 子查询文本
            mode: 检索模式
            project_id: 项目ID
            user: 当前用户
            retriever_names: Planner 选中的 Retriever
            limit: 单路返回数量
            fallback_retrievers: fallback Retriever 列表
            fallback_ladder: 分阶段执行顺序
            chat_type: 问答类型
            query_features: Planner 识别出的查询特征
            skip_reasons: Planner 预先给出的 skip reason
            run_id: 当前 LangGraph run_id
            intent: 当前意图
            sub_query_index: 子查询序号
            sub_query_total: 子查询总数

        返回:
            未重排的检索结果和执行明细
        """

        effective_mode = self._prepare_scope(mode, project_id, chat_type, user, knowledge_scope=knowledge_scope)
        planned_retrievers = self._filter_retriever_names(retriever_names)
        fallback_names = self._filter_retriever_names(fallback_retrievers or [])
        normalized_ladder = self._normalize_execution_ladder(planned_retrievers, fallback_names, fallback_ladder)
        runtime_skip_reasons = dict(skip_reasons or {})
        normalized_retrieval_scope = normalize_retrieval_scope(retrieval_scope)

        groups: list[list[Evidence]] = []
        retriever_hits: dict[str, int] = {}
        retriever_elapsed: dict[str, int] = {}
        retriever_top_scores: dict[str, float] = {}
        retriever_errors: dict[str, str] = {}
        retriever_timeouts: dict[str, bool] = {}
        executed_retrievers: list[str] = []
        fallback_used: list[str] = []
        fallback_trigger_reason: list[dict[str, Any]] = []
        execution_started_at = time.perf_counter()
        effective_min_stage_budget_ms = max(
            0,
            int(
                min_stage_budget_ms
                if min_stage_budget_ms is not None
                else getattr(self.settings, "retrieval_min_stage_budget_ms", 1200) or 1200
            ),
        )
        self._log_base_scope_diagnostics(effective_mode, project_id, user, intent)

        for stage_index, stage_retrievers in enumerate(normalized_ladder, start=1):
            stage_names = [name for name in stage_retrievers if name not in executed_retrievers]
            if not stage_names:
                continue
            stage_budget_ms = self._remaining_budget_ms(remaining_budget_ms, execution_started_at)
            if stage_budget_ms is not None and stage_budget_ms <= 0:
                fallback_trigger_reason.append(
                    {
                        "stage": stage_index,
                        "stage_retrievers": stage_names,
                        "reason": "budget_exhausted",
                        "hits": 0,
                        "top_raw_score": 0.0,
                        "valuable_evidence_count": 0,
                    }
                )
                self._mark_remaining_stage_skips(
                    normalized_ladder=normalized_ladder,
                    current_stage_index=stage_index - 1,
                    runtime_skip_reasons=runtime_skip_reasons,
                    executed_retrievers=executed_retrievers,
                )
                break
            if stage_budget_ms is not None and stage_budget_ms < effective_min_stage_budget_ms:
                fallback_trigger_reason.append(
                    {
                        "stage": stage_index,
                        "stage_retrievers": stage_names,
                        "reason": "budget_too_low",
                        "hits": 0,
                        "top_raw_score": 0.0,
                        "valuable_evidence_count": 0,
                    }
                )
                self._mark_remaining_stage_skips(
                    normalized_ladder=normalized_ladder,
                    current_stage_index=stage_index - 1,
                    runtime_skip_reasons=runtime_skip_reasons,
                    executed_retrievers=executed_retrievers,
                )
                break

            (
                stage_groups,
                stage_hits,
                stage_elapsed,
                stage_top_scores,
                stage_executed,
                stage_errors,
                stage_timeouts,
            ) = self._execute_retrievers(
                query=query,
                effective_mode=effective_mode,
                project_id=project_id,
                user=user,
                retriever_names=stage_names,
                limit=limit,
                planned_order=stage_index,
                fallback_used=stage_index > 1,
                fallback_stage=stage_index - 1,
                fallback_trigger_reason="planner_stage_execution",
                run_id=run_id,
                intent=intent,
                sub_query_index=sub_query_index,
                sub_query_total=sub_query_total,
                query_features=query_features,
                remaining_budget_ms=stage_budget_ms,
                retrieval_scope=normalized_retrieval_scope,
            )
            groups.extend(stage_groups)
            retriever_hits.update(stage_hits)
            retriever_elapsed.update(stage_elapsed)
            retriever_top_scores.update(stage_top_scores)
            retriever_errors.update(stage_errors)
            retriever_timeouts.update(stage_timeouts)
            executed_retrievers.extend(stage_executed)
            if stage_index > 1:
                fallback_used.extend(stage_executed)

            stage_evidences = [item for group in stage_groups for item in group]
            quality = self._assess_stage_quality(query, stage_evidences)
            should_continue, reason_text = self._should_continue_fallback(
                quality,
                stage_index,
                len(normalized_ladder),
                remaining_budget_ms=self._remaining_budget_ms(remaining_budget_ms, execution_started_at),
                min_remaining_budget_ms=effective_min_stage_budget_ms,
            )
            if should_continue:
                fallback_trigger_reason.append(
                    {
                        "stage": stage_index,
                        "stage_retrievers": stage_names,
                        "reason": reason_text,
                        "hits": quality["hits"],
                        "top_raw_score": quality["top_raw_score"],
                        "valuable_evidence_count": quality["valuable_evidence_count"],
                        "structured_anchor_support_count": quality.get("structured_anchor_support_count", 0),
                        "table_like_without_anchor_count": quality.get("table_like_without_anchor_count", 0),
                    }
                )
                continue

            self._mark_remaining_stage_skips(
                normalized_ladder=normalized_ladder,
                current_stage_index=stage_index,
                runtime_skip_reasons=runtime_skip_reasons,
                executed_retrievers=executed_retrievers,
            )
            break

        skipped_retrievers = [
            name for name in self.available_retrievers() if name not in list(dict.fromkeys(executed_retrievers))
        ]
        for retriever_name in skipped_retrievers:
            runtime_skip_reasons.setdefault(retriever_name, "未进入当前执行阶段")

        evidences = [item for group in groups for item in group]
        execution_elapsed_ms = int((time.perf_counter() - execution_started_at) * 1000)
        return {
            "mode": effective_mode,
            "query_scope": self._scope_text(effective_mode),
            "planned_retrievers": planned_retrievers,
            "used_retrievers": list(dict.fromkeys(executed_retrievers)),
            "executed_retrievers": list(dict.fromkeys(executed_retrievers)),
            "skipped_retrievers": skipped_retrievers,
            "skip_reasons": runtime_skip_reasons,
            "fallback_ladder": normalized_ladder,
            "fallback_used": list(dict.fromkeys(fallback_used)),
            "fallback_trigger_reason": fallback_trigger_reason,
            "evidences": evidences,
            "retriever_hits": retriever_hits,
            "retriever_elapsed_ms": retriever_elapsed,
            "retriever_top_scores": retriever_top_scores,
            "retriever_errors": retriever_errors,
            "retriever_timeouts": retriever_timeouts,
            "execution_elapsed_ms": execution_elapsed_ms,
            "retrieval_scope": self._compact_retrieval_scope(normalized_retrieval_scope),
        }

    def available_retrievers(self) -> list[str]:
        """
        获取当前环境可用 Retriever 名称。

        返回:
            按执行优先级排序的 Retriever 列表
        """

        return [retriever.name for retriever in self.retrievers]

    def prepare_scope(
        self,
        mode: str,
        project_id: int | None,
        chat_type: str | None,
        user: User,
        knowledge_scope: str | None = None,
    ) -> str:
        """对外暴露统一的检索范围校验入口。"""

        return self._prepare_scope(mode, project_id, chat_type, user, knowledge_scope=knowledge_scope)

    def _evidence_score(self, evidence: Evidence) -> float:
        try:
            return float(evidence.score)
        except (TypeError, ValueError):
            return 0.0

    def _top_scored_evidences(self, evidences: list[Evidence], limit: int) -> list[Evidence]:
        if limit <= 0:
            return []
        return sorted(evidences, key=self._evidence_score, reverse=True)[:limit]

    def _guard_before_rerank(
        self,
        evidences: list[Evidence],
        *,
        chat_type: str | None,
        effective_mode: str,
        project_id: int | None,
        user: User,
    ) -> tuple[list[Evidence], dict[str, Any]]:
        guard_chat_type = self._guard_chat_type(chat_type, effective_mode)
        result = self.evidence_access_guard.filter_evidences(
            evidences=evidences,
            chat_type=guard_chat_type,
            project_id=project_id,
            user=user,
        )
        if result.rejected:
            logger.info(
                "pre_rerank_evidence_guard: accepted=%s rejected=%s primary_reason=%s chat_type=%s mode=%s project_id=%s",
                len(result.evidences),
                len(result.rejected),
                result.primary_reason,
                guard_chat_type,
                effective_mode,
                project_id,
            )
        return result.evidences, result.to_dict()

    def _guard_chat_type(self, chat_type: str | None, effective_mode: str) -> str:
        normalized = (chat_type or effective_mode or "").strip()
        if normalized in {"project_chat", "base_chat"}:
            return normalized
        if normalized == "project":
            return "project_chat"
        if normalized in {"base", "industry"}:
            return "base_chat"
        return "project_chat" if effective_mode == "project" else "base_chat"

    def _execute_retrievers(
        self,
        query: str,
        effective_mode: str,
        project_id: int | None,
        user: User,
        retriever_names: list[str],
        limit: int,
        planned_order: int,
        fallback_used: bool,
        fallback_stage: int,
        fallback_trigger_reason: str,
        run_id: str | None = None,
        intent: str | None = None,
        sub_query_index: int | None = None,
        sub_query_total: int | None = None,
        query_features: dict[str, Any] | None = None,
        remaining_budget_ms: int | None = None,
        retrieval_scope: dict[str, Any] | None = None,
    ) -> tuple[
        list[list[Evidence]],
        dict[str, int],
        dict[str, int],
        dict[str, float],
        list[str],
        dict[str, str],
        dict[str, bool],
    ]:
        """
        执行一组 Retriever，并输出结构化日志。

        参数:
            query: 查询文本
            effective_mode: 生效检索模式
            project_id: 项目ID
            user: 当前用户
            retriever_names: 本阶段待执行 Retriever
            limit: 单路返回数量
            planned_order: 当前阶段顺序
            fallback_used: 是否为 fallback 阶段
            fallback_stage: fallback 阶段编号
            fallback_trigger_reason: 本阶段触发原因
            run_id: LangGraph run_id
            intent: 当前意图
            sub_query_index: 子查询序号
            sub_query_total: 子查询总数

        返回:
            分组结果、命中数、耗时、最高分和实际执行 Retriever
        """

        return self._run_async_blocking(
            self._execute_retrievers_async(
                query=query,
                effective_mode=effective_mode,
                project_id=project_id,
                user=user,
                retriever_names=retriever_names,
                limit=limit,
                planned_order=planned_order,
                fallback_used=fallback_used,
                fallback_stage=fallback_stage,
                fallback_trigger_reason=fallback_trigger_reason,
                run_id=run_id,
                intent=intent,
                sub_query_index=sub_query_index,
                sub_query_total=sub_query_total,
                query_features=query_features,
                remaining_budget_ms=remaining_budget_ms,
                retrieval_scope=retrieval_scope,
            )
        )

    async def _execute_retrievers_async(
        self,
        query: str,
        effective_mode: str,
        project_id: int | None,
        user: User,
        retriever_names: list[str],
        limit: int,
        planned_order: int,
        fallback_used: bool,
        fallback_stage: int,
        fallback_trigger_reason: str,
        run_id: str | None,
        intent: str | None,
        sub_query_index: int | None,
        sub_query_total: int | None,
        query_features: dict[str, Any] | None,
        remaining_budget_ms: int | None,
        retrieval_scope: dict[str, Any] | None,
    ) -> tuple[
        list[list[Evidence]],
        dict[str, int],
        dict[str, int],
        dict[str, float],
        list[str],
        dict[str, str],
        dict[str, bool],
    ]:
        enabled_names = [name for name in retriever_names if name in self.retriever_map]
        disabled_names = [name for name in retriever_names if name not in self.retriever_map]
        for name in disabled_names:
            logger.warning("Planner selected disabled retriever: run_id=%s retriever=%s query=%s", run_id, name, query[:160])

        logger.info(
            "Retriever stage parallel execution: run_id=%s intent=%s planned_order=%s retrievers=%s query=%s",
            run_id,
            intent,
            planned_order,
            enabled_names,
            query[:160],
        )
        if not enabled_names:
            return ([], {}, {}, {}, [], {}, {})
        user_snapshot = self._snapshot_user(user)
        stage_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self._stage_executor_max_workers(len(enabled_names)),
            thread_name_prefix=f"retriever-stage-{planned_order}",
        )
        try:
            results = await asyncio.gather(
                *[
                    self._execute_one_retriever_async(
                        executor=stage_executor,
                        name=name,
                        query=query,
                        effective_mode=effective_mode,
                        project_id=project_id,
                        user=user_snapshot,
                        limit=limit,
                        planned_order=planned_order,
                        fallback_used=fallback_used,
                        fallback_stage=fallback_stage,
                        fallback_trigger_reason=fallback_trigger_reason,
                        run_id=run_id,
                        intent=intent,
                        sub_query_index=sub_query_index,
                        sub_query_total=sub_query_total,
                        query_features=query_features,
                        remaining_budget_ms=remaining_budget_ms,
                        retrieval_scope=retrieval_scope,
                    )
                    for name in enabled_names
                ],
                return_exceptions=True,
            )
        finally:
            stage_executor.shutdown(wait=False, cancel_futures=True)

        groups: list[list[Evidence]] = []
        retriever_hits: dict[str, int] = {}
        retriever_elapsed: dict[str, int] = {}
        retriever_top_scores: dict[str, float] = {}
        retriever_errors: dict[str, str] = {}
        retriever_timeouts: dict[str, bool] = {}
        executed_retrievers: list[str] = []
        for name, result in zip(enabled_names, results, strict=True):
            if isinstance(result, Exception):
                retriever_hits[name] = 0
                retriever_elapsed[name] = 0
                retriever_top_scores[name] = 0.0
                retriever_errors[name] = result.__class__.__name__
                retriever_timeouts[name] = False
                executed_retrievers.append(name)
                logger.error(
                    "Retriever parallel task failed unexpectedly: run_id=%s retriever=%s error=%s",
                    run_id,
                    name,
                    result,
                )
                continue

            group = result["group"]
            groups.append(group)
            retriever_hits[name] = result["hits"]
            retriever_elapsed[name] = result["elapsed_ms"]
            retriever_top_scores[name] = result["top_score"]
            retriever_timeouts[name] = result["timeout"]
            if result["error"]:
                retriever_errors[name] = result["error"]
            executed_retrievers.append(name)

        return (
            groups,
            retriever_hits,
            retriever_elapsed,
            retriever_top_scores,
            executed_retrievers,
            retriever_errors,
            retriever_timeouts,
        )

    async def _execute_one_retriever_async(
        self,
        executor: concurrent.futures.Executor,
        name: str,
        query: str,
        effective_mode: str,
        project_id: int | None,
        user: User,
        limit: int,
        planned_order: int,
        fallback_used: bool,
        fallback_stage: int,
        fallback_trigger_reason: str,
        run_id: str | None,
        intent: str | None,
        sub_query_index: int | None,
        sub_query_total: int | None,
        query_features: dict[str, Any] | None,
        remaining_budget_ms: int | None,
        retrieval_scope: dict[str, Any] | None,
    ) -> dict[str, Any]:
        timeout_ms = self._retriever_timeout_ms(name)
        if remaining_budget_ms is not None:
            timeout_ms = min(timeout_ms, max(int(remaining_budget_ms), 1))
        started_at = time.perf_counter()
        timeout = False
        error = ""
        group: list[Evidence] = []
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            executor,
            self._search_with_isolated_retriever,
            name,
            query,
            effective_mode,
            project_id,
            user,
            limit,
            retrieval_scope,
        )
        try:
            group = await asyncio.wait_for(future, timeout=max(timeout_ms, 1) / 1000)
        except asyncio.TimeoutError:
            timeout = True
            error = f"timeout>{timeout_ms}ms"
            future.cancel()
            logger.warning("Retriever timed out: run_id=%s retriever=%s timeout_ms=%s query=%s", run_id, name, timeout_ms, query[:160])
        except Exception as exc:  # noqa: BLE001
            error = exc.__class__.__name__
            logger.exception("Retriever execution failed: run_id=%s retriever=%s query=%s error=%s", run_id, name, query[:160], exc)

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        top_score = max((float(item.score) for item in group), default=0.0)
        logger.info(
            "Retriever execution completed: run_id=%s query=%s intent=%s retriever=%s planned_order=%s hits=%s top_score=%.4f post_filter_hits=%s fallback_used=%s fallback_stage=%s fallback_trigger_reason=%s elapsed_ms=%s timeout=%s error=%s sub_query_index=%s sub_query_total=%s query_features=%s retrieval_scope=%s",
            run_id,
            query[:160],
            intent,
            name,
            planned_order,
            len(group),
            top_score,
            len(group),
            fallback_used,
            fallback_stage,
            fallback_trigger_reason,
            elapsed_ms,
            timeout,
            error or None,
            sub_query_index,
            sub_query_total,
            self._compact_query_features(query_features),
            self._compact_retrieval_scope(retrieval_scope),
        )
        return {
            "group": group,
            "hits": len(group),
            "elapsed_ms": elapsed_ms,
            "top_score": round(top_score, 4),
            "timeout": timeout,
            "error": error,
        }

    def _stage_executor_max_workers(self, stage_size: int) -> int:
        configured_workers = getattr(self, "_retriever_executor_max_workers", None)
        if configured_workers is None:
            executor = getattr(self, "_retriever_executor", None)
            configured_workers = getattr(executor, "_max_workers", None)
        try:
            max_workers = int(configured_workers or 6)
        except (TypeError, ValueError):
            max_workers = 6
        return max(1, min(max_workers, max(stage_size, 1)))

    def _run_async_blocking(self, coroutine: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)

        result: dict[str, Any] = {}

        def runner() -> None:
            try:
                result["value"] = asyncio.run(coroutine)
            except Exception as exc:  # noqa: BLE001
                result["error"] = exc

        thread = threading.Thread(target=runner, name="retrieval-router-async", daemon=True)
        thread.start()
        thread.join()
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def _search_with_isolated_retriever(
        self,
        name: str,
        query: str,
        effective_mode: str,
        project_id: int | None,
        user: User,
        limit: int,
        retrieval_scope: dict[str, Any] | None = None,
    ) -> list[Evidence]:
        retriever = self.retriever_map[name]
        if not self._uses_real_db_session(retriever):
            return self._call_retriever_search(retriever, query, effective_mode, project_id, user, limit, retrieval_scope)

        with SessionLocal() as db:
            isolated_retriever = self._build_retriever_for_session(name, db)
            return self._call_retriever_search(isolated_retriever, query, effective_mode, project_id, user, limit, retrieval_scope)

    def _call_retriever_search(
        self,
        retriever: Any,
        query: str,
        effective_mode: str,
        project_id: int | None,
        user: User,
        limit: int,
        retrieval_scope: dict[str, Any] | None,
    ) -> list[Evidence]:
        if retrieval_scope and self._retriever_accepts_scope(retriever):
            return retriever.search(
                query,
                effective_mode,
                project_id,
                user,
                limit,
                retrieval_scope=retrieval_scope,
            )
        return retriever.search(query, effective_mode, project_id, user, limit)

    def _retriever_accepts_scope(self, retriever: Any) -> bool:
        try:
            parameters = inspect.signature(retriever.search).parameters
        except (TypeError, ValueError):
            return False
        return "retrieval_scope" in parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        )

    def _uses_real_db_session(self, retriever: Any) -> bool:
        return isinstance(
            retriever,
            (
                PageIndexRetriever,
                ProjectMetadataRetriever,
                MilvusHybridRetriever,
                RipgrepRetriever,
                GraphRAGRetriever,
                KeywordRetriever,
            ),
        )

    def _build_retriever_for_session(self, name: str, db: Session) -> Any:
        if name == "page_index":
            return PageIndexRetriever(db)
        if name == "project_metadata":
            return ProjectMetadataRetriever(db)
        if name == "milvus":
            return MilvusHybridRetriever(db)
        if name == "ripgrep":
            return RipgrepRetriever(db)
        if name == "graphrag":
            return GraphRAGRetriever(db)
        if name == "keyword":
            return KeywordRetriever(db)
        raise ValueError(f"unknown retriever: {name}")

    def _snapshot_user(self, user: User) -> User:
        if user is None:
            return user
        roles: list[Any] = []
        for role in list(getattr(user, "roles", []) or []):
            permissions = [
                SimpleNamespace(
                    id=getattr(permission, "id", None),
                    code=getattr(permission, "code", ""),
                )
                for permission in list(getattr(role, "permissions", []) or [])
            ]
            roles.append(
                SimpleNamespace(
                    id=getattr(role, "id", None),
                    code=getattr(role, "code", ""),
                    name=getattr(role, "name", ""),
                    enabled=getattr(role, "enabled", True),
                    security_level=getattr(role, "security_level", None),
                    data_scope=getattr(role, "data_scope", None),
                    permissions=permissions,
                )
            )
        return SimpleNamespace(
            id=getattr(user, "id", None),
            username=getattr(user, "username", ""),
            department=getattr(user, "department", None),
            department_id=getattr(user, "department_id", None),
            roles=roles,
        )

    def _retriever_timeout_ms(self, name: str) -> int:
        settings = getattr(self, "settings", None)
        base_timeout_ms = int(getattr(settings, "retrieval_retriever_timeout_ms", 4500) or 4500)
        if name == "milvus":
            milvus_timeout_ms = int(getattr(settings, "retrieval_milvus_timeout_ms", 15000) or 15000)
            return max(base_timeout_ms, milvus_timeout_ms)
        if name == "ripgrep":
            # ripgrep 内部 subprocess 已使用 RIPGREP_TIMEOUT_MS，Router 外层需要额外留出权限过滤和结果映射时间，
            # 否则会出现 rg 本体未超时、但整个 retriever 被外层 wait_for 提前判超时的误报。
            ripgrep_timeout_ms = int(getattr(settings, "ripgrep_timeout_ms", 1500) or 1500)
            return max(base_timeout_ms, ripgrep_timeout_ms + 1000)
        return base_timeout_ms

    def __del__(self) -> None:
        executor = getattr(self, "_retriever_executor", None)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def _compact_retrieval_scope(self, retrieval_scope: dict[str, Any] | None) -> dict[str, Any]:
        if not retrieval_scope:
            return {}
        page_numbers_by_document = retrieval_scope.get("page_numbers_by_document") or {}
        page_count = 0
        if isinstance(page_numbers_by_document, dict):
            page_count = sum(len(pages or []) for pages in page_numbers_by_document.values())
        return {
            "document_count": len(retrieval_scope.get("document_ids") or []),
            "chunk_count": len(retrieval_scope.get("chunk_ids") or []),
            "page_scope_document_count": len(page_numbers_by_document) if isinstance(page_numbers_by_document, dict) else 0,
            "page_count": page_count,
        }

    def _compact_query_features(self, query_features: dict[str, Any] | None) -> dict[str, Any]:
        if not query_features:
            return {}
        keys = [
            "has_exact_token",
            "has_doc_code",
            "has_page_hint",
            "has_section_hint",
            "has_table_hint",
            "has_value_hint",
            "has_table_value_lookup",
            "has_graph_relation",
            "has_project_name",
            "knowledge_scope",
            "resolved_task_type",
            "answer_policy",
        ]
        compact = {key: query_features.get(key) for key in keys if query_features.get(key)}
        if query_features.get("retrieval_needs"):
            compact["retrieval_needs"] = query_features.get("retrieval_needs")
        if query_features.get("query_rewrites"):
            compact["query_rewrite_count"] = len(query_features.get("query_rewrites") or [])
        profile = query_features.get("query_profile") or {}
        if profile:
            compact["query_type"] = profile.get("query_type")
            compact["answer_shape"] = profile.get("answer_shape")
        return compact

    def _log_base_scope_diagnostics(
        self,
        effective_mode: str,
        project_id: int | None,
        user: User,
        intent: str | None,
    ) -> None:
        if effective_mode != "base_chat" or intent not in {"industry_knowledge_qa", "knowledge_qa"}:
            return
        if getattr(self, "db", None) is None or user is None:
            return
        try:
            policy = KeywordRetriever(self.db)
            base_kb_ids = list(
                self.db.scalars(
                    select(KnowledgeBase.id).where(KnowledgeBase.type == "base", KnowledgeBase.enabled.is_(True))
                ).all()
            )
            allowed_kb_ids = [
                kb_id
                for kb_id in base_kb_ids
                if policy._base_knowledge_allowed(kb_id, project_id, user, strict_external=False)
            ]
            total_base_docs = int(
                self.db.scalar(
                    select(func.count(Document.id)).where(
                        Document.knowledge_type == "base",
                        Document.review_status == "approved",
                        Document.index_status == "indexed",
                    )
                )
                or 0
            )
            user_level = user_max_security_level(user)
            allowed_levels = allowed_security_levels(user_level)
            allowed_docs = 0
            active_chunks = 0
            if allowed_kb_ids:
                allowed_docs = int(
                    self.db.scalar(
                        select(func.count(Document.id)).where(
                            Document.knowledge_type == "base",
                            Document.knowledge_base_id.in_(allowed_kb_ids),
                            Document.review_status == "approved",
                            Document.index_status == "indexed",
                            Document.security_level.in_(allowed_levels),
                        )
                    )
                    or 0
                )
                active_chunks = int(
                    self.db.scalar(
                        select(func.count(DocumentChunk.id))
                        .join(Document, Document.id == DocumentChunk.document_id)
                        .where(
                            Document.knowledge_type == "base",
                            Document.knowledge_base_id.in_(allowed_kb_ids),
                            Document.review_status == "approved",
                            Document.index_status == "indexed",
                            Document.security_level.in_(allowed_levels),
                            DocumentChunk.security_level.in_(allowed_levels),
                            DocumentChunk.chunk_status == "active",
                            DocumentChunk.version_no == Document.version_no,
                        )
                    )
                    or 0
                )
            logger.info(
                "Base knowledge scope diagnostics: intent=%s user_id=%s allowed_scopes=%s allowed_project_ids=%s allowed_knowledge_base_ids=%s approved_document_count=%s allowed_document_count=%s active_chunk_count=%s user_security_level=%s",
                intent,
                getattr(user, "id", None),
                ["base"],
                [],
                allowed_kb_ids,
                total_base_docs,
                allowed_docs,
                active_chunks,
                user_level,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Base knowledge scope diagnostics failed: intent=%s error=%s", intent, exc)

    def _normalize_execution_ladder(
        self,
        planned_retrievers: list[str],
        fallback_retrievers: list[str],
        fallback_ladder: list[list[str]] | None,
    ) -> list[list[str]]:
        """
        规范化阶段执行顺序。

        参数:
            planned_retrievers: 主计划 Retriever
            fallback_retrievers: fallback Retriever
            fallback_ladder: Planner 输出的阶段顺序

        返回:
            规范化后的阶段顺序
        """

        if fallback_ladder:
            normalized: list[list[str]] = []
            seen: set[str] = set()
            for stage in fallback_ladder:
                current_stage: list[str] = []
                for name in self._filter_retriever_names(stage):
                    if name in seen:
                        continue
                    current_stage.append(name)
                    seen.add(name)
                if current_stage:
                    normalized.append(current_stage)
            if normalized:
                return normalized

        normalized_planned = self._filter_retriever_names(planned_retrievers)
        normalized_fallback = [name for name in self._filter_retriever_names(fallback_retrievers) if name not in normalized_planned]
        ladder: list[list[str]] = []
        if normalized_planned:
            ladder.append(normalized_planned)
        for name in normalized_fallback:
            ladder.append([name])
        return ladder

    def _assess_stage_quality(self, query: str, evidences: list[Evidence]) -> dict[str, Any]:
        """
        评估单个阶段的命中质量。

        参数:
            evidences: 当前阶段召回证据

        返回:
            命中数量、最高分和有效证据数量
        """

        top_raw_score = max((float(item.score) for item in evidences), default=0.0)
        valuable_evidences = [item for item in evidences if boilerplate_multiplier(item.content) >= 0.45]
        quality = {
            "hits": len(evidences),
            "top_raw_score": round(top_raw_score, 4),
            "valuable_evidence_count": len(valuable_evidences),
        }
        if is_structured_list_lookup_query(query):
            structured_anchor_support_count = 0
            table_like_without_anchor_count = 0
            for item in valuable_evidences:
                evidence_text = self._structured_quality_text(item)
                has_anchor = has_structured_lookup_anchor_support(evidence_text, query)
                if has_anchor:
                    structured_anchor_support_count += 1
                elif is_table_like_content(evidence_text):
                    table_like_without_anchor_count += 1
            quality.update(
                {
                    "structured_list_query": True,
                    "structured_anchor_support_count": structured_anchor_support_count,
                    "table_like_without_anchor_count": table_like_without_anchor_count,
                }
            )
        return quality

    def _should_continue_fallback(
        self,
        quality: dict[str, Any],
        stage_index: int,
        stage_count: int,
        *,
        remaining_budget_ms: int | None = None,
        min_remaining_budget_ms: int = 0,
    ) -> tuple[bool, str]:
        """
        判断是否继续执行下一层 fallback。

        参数:
            quality: 当前阶段质量评估结果
            stage_index: 当前阶段序号
            stage_count: 总阶段数

        返回:
            是否继续 fallback，以及触发原因
        """

        if stage_index >= stage_count:
            return False, "already_last_stage"
        if remaining_budget_ms is not None and int(remaining_budget_ms) <= 0:
            return False, "budget_exhausted"
        if remaining_budget_ms is not None and int(remaining_budget_ms) < max(int(min_remaining_budget_ms), 0):
            return False, "budget_too_low"
        if int(quality["hits"]) == 0:
            return True, "hits==0"
        if bool(quality.get("structured_list_query")) and int(quality.get("structured_anchor_support_count", 0)) <= 0:
            return True, "structured_anchor_support_count==0"
        if float(quality["top_raw_score"]) < LOW_QUALITY_SCORE_THRESHOLD:
            return True, f"top_raw_score<{LOW_QUALITY_SCORE_THRESHOLD}"
        if int(quality["valuable_evidence_count"]) < LOW_QUALITY_VALUABLE_EVIDENCE_THRESHOLD:
            return True, f"valuable_evidence_count<{LOW_QUALITY_VALUABLE_EVIDENCE_THRESHOLD}"
        return False, "quality_enough"

    def _structured_quality_text(self, evidence: Evidence) -> str:
        metadata = evidence.metadata or {}
        return " ".join(
            str(part)
            for part in (
                evidence.file_name,
                metadata.get("document_name"),
                metadata.get("document_type"),
                metadata.get("discipline"),
                evidence.content,
            )
            if part
        )

    def _remaining_budget_ms(self, total_budget_ms: int | None, started_at: float) -> int | None:
        if total_budget_ms is None:
            return None
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        return max(int(total_budget_ms) - elapsed_ms, 0)

    def _mark_remaining_stage_skips(
        self,
        normalized_ladder: list[list[str]],
        current_stage_index: int,
        runtime_skip_reasons: dict[str, str],
        executed_retrievers: list[str],
        default_reason: str | None = None,
    ) -> None:
        """
        在提前结束 fallback 时，为剩余阶段补齐 skip reason。

        参数:
            normalized_ladder: 当前执行梯子
            current_stage_index: 已完成的阶段序号
            runtime_skip_reasons: 运行时 skip reason 容器
            executed_retrievers: 已执行 Retriever 列表
        """

        for stage_position in range(current_stage_index, len(normalized_ladder)):
            for retriever_name in normalized_ladder[stage_position]:
                if retriever_name in executed_retrievers:
                    continue
                runtime_skip_reasons.setdefault(
                    retriever_name,
                    f"前一阶段结果质量已满足要求，未继续执行stage_{stage_position + 1}",
                )

    def _filter_retriever_names(self, retriever_names: list[str]) -> list[str]:
        """
        过滤未知或重复 Retriever 名称。

        参数:
            retriever_names: 原始 Retriever 名称列表

        返回:
            过滤后的 Retriever 名称列表
        """

        result: list[str] = []
        for name in retriever_names:
            if name in self.retriever_map and name not in result:
                result.append(name)
        return result

    def _prepare_scope(
        self,
        mode: str,
        project_id: int | None,
        chat_type: str | None,
        user: User,
        knowledge_scope: str | None = None,
    ) -> str:
        """
        计算并校验检索范围。

        参数:
            mode: 请求模式
            project_id: 项目ID
            chat_type: 问答类型
            user: 当前用户

        返回:
            生效检索模式
        """

        effective_mode = self._effective_mode(mode, project_id, chat_type, knowledge_scope=knowledge_scope)
        if effective_mode in {"project_only", "hybrid", "project_chat", "project_with_industry"}:
            if project_id is None:
                raise AppException("项目知识问答必须选择项目")
            if effective_mode == "project_chat":
                ProjectAccessService(self.db).ensure_project_access(project_id, user, permission_codes=("project:chat",))
            else:
                ProjectService(self.db).ensure_project_access(project_id, user)
        if effective_mode == "base_chat" and self._is_external_user(user):
            raise AppException("外部用户默认不能访问基础问答", status_code=403, code=403)
        return effective_mode

    def _effective_mode(
        self,
        mode: str,
        project_id: int | None,
        chat_type: str | None = None,
        knowledge_scope: str | None = None,
    ) -> str:
        """
        计算实际检索模式。

        参数:
            mode: 请求模式
            project_id: 项目ID
            chat_type: 问答类型

        返回:
            生效检索模式
        """

        if chat_type == "project_chat":
            return "project_chat"
        if chat_type == "base_chat":
            return "base_chat"
        if knowledge_scope == "industry":
            return "base_only"
        if knowledge_scope == "project_with_industry":
            return "project_with_industry"
        if knowledge_scope == "project":
            return "project_only"
        if mode == "auto":
            return "hybrid" if project_id is not None else "base_only"
        if mode not in {"base_only", "project_only", "hybrid", "project_chat", "base_chat", "project_with_industry"}:
            raise AppException("不支持的问答模式")
        return mode

    def _scope_text(self, mode: str) -> str:
        """
        获取检索范围说明。

        参数:
            mode: 生效检索模式

        返回:
            中文范围说明
        """

        return {
            "base_only": "基础知识",
            "project_only": "项目知识",
            "hybrid": "基础知识 + 项目知识",
            "project_with_industry": "所选项目资料 + 授权行业基础知识",
            "project_chat": "所选项目资料",
            "base_chat": "当前用户有权限访问的基础知识库资料",
        }.get(mode, "自动判断")

    def _is_external_user(self, user: User) -> bool:
        """
        判断是否为外部用户。

        参数:
            user: 当前登录用户

        返回:
            True 表示外部用户
        """

        return any(role.code == "external" or "外部" in role.name for role in user.roles)

    def _enabled_retrievers(self, db: Session) -> list[Any]:
        """
        获取当前真正启用的 Retriever 实例。

        参数:
            db: 数据库会话

        返回:
            Retriever 实例列表
        """

        retrievers: list[Any] = [ProjectMetadataRetriever(db), PageIndexRetriever(db)]
        if self.settings.milvus_enabled:
            retrievers.append(MilvusHybridRetriever(db))
        else:
            logger.info("未配置Milvus，检索链路将跳过 milvus retriever")
        retrievers.append(RipgrepRetriever(db))
        retrievers.append(GraphRAGRetriever(db))
        retrievers.append(KeywordRetriever(db))
        return retrievers
