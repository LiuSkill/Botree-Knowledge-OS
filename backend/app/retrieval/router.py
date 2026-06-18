"""
Retrieval Router

负责：
1. 统一执行权限校验和检索范围计算
2. 按 Planner 结果分阶段执行 Retriever，并在低质量时触发 fallback
3. 输出结构化检索日志、trace 字段和可审计的执行摘要
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.models.user import User
from app.retrieval.merger import EvidenceMerger
from app.retrieval.query_utils import boilerplate_multiplier
from app.retrieval.retrievers.graph_retriever import GraphRAGRetriever
from app.retrieval.retrievers.keyword_retriever import KeywordRetriever
from app.retrieval.retrievers.milvus_retriever import MilvusHybridRetriever
from app.retrieval.retrievers.page_index_retriever import PageIndexRetriever
from app.retrieval.retrievers.ripgrep_retriever import RipgrepRetriever
from app.retrieval.schemas import Evidence
from app.services.project_service import ProjectService
from app.services.qwen_orchestration_service import QwenOrchestrationService
from app.services.reranker_service import RerankerService
from app.services.retrieval_planner_service import RetrievalPlannerService

logger = logging.getLogger(__name__)

LOW_QUALITY_SCORE_THRESHOLD = 0.58
LOW_QUALITY_VALUABLE_EVIDENCE_THRESHOLD = 2


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

    def search(
        self,
        query: str,
        mode: str,
        project_id: int | None,
        user: User,
        limit: int = 5,
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

        effective_mode = self._prepare_scope(mode, project_id, chat_type, user)
        qwen = QwenOrchestrationService(self.db)
        intent = qwen.detect_intent(query, chat_type or "", effective_mode)
        sub_queries = qwen.decompose_query(query, intent)
        plan = RetrievalPlannerService(self.db).plan(
            query=query,
            sub_queries=sub_queries,
            intent=intent,
            chat_type=chat_type or "",
            mode=effective_mode,
            project_id=project_id,
            available_retrievers=self.available_retrievers(),
        )
        retrieval = self.execute_planned(
            query=query,
            mode=effective_mode,
            project_id=project_id,
            user=user,
            retriever_names=plan.selected_retrievers,
            limit=limit,
            fallback_retrievers=plan.fallback_retrievers,
            fallback_ladder=plan.fallback_ladder,
            chat_type=chat_type,
            query_features=plan.query_features,
            skip_reasons=plan.skip_reasons,
            intent=intent,
        )
        merged_evidences = self.merger.merge([retrieval["evidences"]], max(limit * 3, limit))
        evidences = self.reranker.rerank(query, merged_evidences, limit)
        return {
            **retrieval,
            "intent": intent,
            "sub_queries": sub_queries,
            "retrieval_plan": plan.to_dict(),
            "evidences": evidences,
            "rerank_details": self.reranker.last_details,
        }

    def search_all(
        self,
        query: str,
        mode: str,
        project_id: int | None,
        user: User,
        limit: int = 5,
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
        groups, retriever_hits, retriever_elapsed, retriever_top_scores, executed_retrievers = self._execute_retrievers(
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
        )
        merged_evidences = self.merger.merge(groups, max(limit * 3, limit))
        evidences = self.reranker.rerank(query, merged_evidences, limit)
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
            "evidences": evidences,
            "retriever_hits": retriever_hits,
            "retriever_elapsed_ms": retriever_elapsed,
            "retriever_top_scores": retriever_top_scores,
            "rerank_details": self.reranker.last_details,
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
        }

    def execute_planned(
        self,
        query: str,
        mode: str,
        project_id: int | None,
        user: User,
        retriever_names: list[str],
        limit: int = 5,
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

        groups: list[list[Evidence]] = []
        retriever_hits: dict[str, int] = {}
        retriever_elapsed: dict[str, int] = {}
        retriever_top_scores: dict[str, float] = {}
        executed_retrievers: list[str] = []
        fallback_used: list[str] = []
        fallback_trigger_reason: list[dict[str, Any]] = []

        for stage_index, stage_retrievers in enumerate(normalized_ladder, start=1):
            stage_names = [name for name in stage_retrievers if name not in executed_retrievers]
            if not stage_names:
                continue

            stage_groups, stage_hits, stage_elapsed, stage_top_scores, stage_executed = self._execute_retrievers(
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
            )
            groups.extend(stage_groups)
            retriever_hits.update(stage_hits)
            retriever_elapsed.update(stage_elapsed)
            retriever_top_scores.update(stage_top_scores)
            executed_retrievers.extend(stage_executed)
            if stage_index > 1:
                fallback_used.extend(stage_executed)

            stage_evidences = [item for group in stage_groups for item in group]
            quality = self._assess_stage_quality(stage_evidences)
            should_continue, reason_text = self._should_continue_fallback(quality, stage_index, len(normalized_ladder))
            if should_continue:
                fallback_trigger_reason.append(
                    {
                        "stage": stage_index,
                        "stage_retrievers": stage_names,
                        "reason": reason_text,
                        "hits": quality["hits"],
                        "top_raw_score": quality["top_raw_score"],
                        "valuable_evidence_count": quality["valuable_evidence_count"],
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
        }

    def available_retrievers(self) -> list[str]:
        """
        获取当前环境可用 Retriever 名称。

        返回:
            按执行优先级排序的 Retriever 列表
        """

        return [retriever.name for retriever in self.retrievers]

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
    ) -> tuple[list[list[Evidence]], dict[str, int], dict[str, int], dict[str, float], list[str]]:
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

        groups: list[list[Evidence]] = []
        retriever_hits: dict[str, int] = {}
        retriever_elapsed: dict[str, int] = {}
        retriever_top_scores: dict[str, float] = {}
        executed_retrievers: list[str] = []

        for name in retriever_names:
            retriever = self.retriever_map.get(name)
            if retriever is None:
                logger.warning(
                    "Planner选择了未启用Retriever: run_id=%s retriever=%s query=%s",
                    run_id,
                    name,
                    query[:160],
                )
                continue

            started_at = time.perf_counter()
            group = retriever.search(query, effective_mode, project_id, user, limit)
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            top_score = max((float(item.score) for item in group), default=0.0)

            groups.append(group)
            retriever_hits[retriever.name] = len(group)
            retriever_elapsed[retriever.name] = elapsed_ms
            retriever_top_scores[retriever.name] = round(top_score, 4)
            executed_retrievers.append(retriever.name)

            logger.info(
                "Retriever执行完成: run_id=%s query=%s intent=%s retriever=%s planned_order=%s hits=%s top_score=%.4f post_filter_hits=%s fallback_used=%s fallback_stage=%s fallback_trigger_reason=%s elapsed_ms=%s sub_query_index=%s sub_query_total=%s",
                run_id,
                query[:160],
                intent,
                retriever.name,
                planned_order,
                len(group),
                top_score,
                len(group),
                fallback_used,
                fallback_stage,
                fallback_trigger_reason,
                elapsed_ms,
                sub_query_index,
                sub_query_total,
            )

        return groups, retriever_hits, retriever_elapsed, retriever_top_scores, executed_retrievers

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

    def _assess_stage_quality(self, evidences: list[Evidence]) -> dict[str, Any]:
        """
        评估单个阶段的命中质量。

        参数:
            evidences: 当前阶段召回证据

        返回:
            命中数量、最高分和有效证据数量
        """

        top_raw_score = max((float(item.score) for item in evidences), default=0.0)
        valuable_evidence_count = sum(1 for item in evidences if boilerplate_multiplier(item.content) >= 0.45)
        return {
            "hits": len(evidences),
            "top_raw_score": round(top_raw_score, 4),
            "valuable_evidence_count": valuable_evidence_count,
        }

    def _should_continue_fallback(
        self,
        quality: dict[str, Any],
        stage_index: int,
        stage_count: int,
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
        if int(quality["hits"]) == 0:
            return True, "hits==0"
        if float(quality["top_raw_score"]) < LOW_QUALITY_SCORE_THRESHOLD:
            return True, f"top_raw_score<{LOW_QUALITY_SCORE_THRESHOLD}"
        if int(quality["valuable_evidence_count"]) < LOW_QUALITY_VALUABLE_EVIDENCE_THRESHOLD:
            return True, f"valuable_evidence_count<{LOW_QUALITY_VALUABLE_EVIDENCE_THRESHOLD}"
        return False, "quality_enough"

    def _mark_remaining_stage_skips(
        self,
        normalized_ladder: list[list[str]],
        current_stage_index: int,
        runtime_skip_reasons: dict[str, str],
        executed_retrievers: list[str],
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

        if knowledge_scope == "industry":
            return "base_chat" if chat_type == "base_chat" else "base_only"
        if knowledge_scope == "project_with_industry":
            return "project_with_industry"
        if knowledge_scope == "project":
            return "project_chat" if chat_type == "project_chat" else "project_only"
        if chat_type == "project_chat":
            return "project_chat"
        if chat_type == "base_chat":
            return "base_chat"
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

        retrievers: list[Any] = [PageIndexRetriever(db)]
        if self.settings.milvus_enabled:
            retrievers.append(MilvusHybridRetriever(db))
        else:
            logger.info("未配置Milvus，检索链路将跳过 milvus retriever")
        retrievers.append(RipgrepRetriever(db))
        retrievers.append(GraphRAGRetriever(db))
        retrievers.append(KeywordRetriever(db))
        return retrievers
