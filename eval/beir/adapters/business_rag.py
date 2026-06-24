"""Adapters that call the real project RAG graph for BEIR evaluation."""

from __future__ import annotations

import logging
import time
from typing import Any

from eval.beir.adapters.base import AdapterContext
from eval.beir.business_mapping import BusinessDocIdMapper, load_doc_id_mapping
from eval.beir.types import SearchHit

logger = logging.getLogger(__name__)

NODE_KEYS = ("intent", "query_decompose", "query_profile", "planner", "retrieval", "evidence_judge", "retry_retrieval", "answer")


class BaseBusinessRAGAdapter:
    """Shared implementation for agentic_router and full_rag BEIR adapters."""

    name = "business_rag"
    include_answer = False

    def __init__(self) -> None:
        self.context: AdapterContext | None = None
        self.graph: Any | None = None
        self.mapper: BusinessDocIdMapper | None = None
        self.project: Any | None = None
        self.user: Any | None = None

    def prepare(self, context: AdapterContext) -> None:
        """Load the business graph, user/project and BEIR mapping."""

        if context.db is None:
            raise RuntimeError(f"{self.name} requires a database session")

        from app.langgraph.retrieval_graph import RetrievalGraph
        from app.repositories.project_repository import ProjectRepository
        from app.repositories.user_repository import UserRepository
        from app.services.project_service import ProjectService

        project_code = str(context.config.business_project_code)
        user_key = str(context.config.business_user_id)
        project = ProjectRepository(context.db).get_by_code(project_code)
        if project is None:
            raise RuntimeError(f"Business eval project does not exist: project_code={project_code}. Run --mode business_index first.")

        user_repository = UserRepository(context.db)
        user = user_repository.get_by_id(int(user_key)) if user_key.isdigit() else user_repository.get_by_username(user_key)
        if user is None:
            raise RuntimeError(f"Business eval user does not exist: user={user_key}. Run --mode business_index first.")
        ProjectService(context.db).ensure_project_access(project.id, user)

        mapper = load_doc_id_mapping(context.dataset, split=context.split)
        if len(mapper) == 0:
            raise RuntimeError(f"BEIR business mapping is empty for dataset={context.dataset}. Run --mode business_index first.")

        self.context = context
        self.graph = RetrievalGraph(context.db)
        self.mapper = mapper
        self.project = project
        self.user = user
        context.extra.setdefault("business_query_traces", {})
        context.extra.setdefault("unmapped_evidence", [])
        context.extra.setdefault("answer_details", [])
        context.extra.setdefault("business_mapping_counts", {"mapped": 0, "unmapped": 0, "total": 0})
        context.extra.setdefault("warnings", [])
        logger.info(
            "stage=evaluation action=business_adapter_prepare status=completed adapter=%s project_id=%s user_id=%s mapping_count=%s",
            self.name,
            project.id,
            user.id,
            len(mapper),
        )

    def search(self, query_id: str, query: str, top_k: int) -> list[SearchHit]:
        """Call the real RAG graph and return BEIR-formatted hits."""

        if self.context is None or self.graph is None or self.mapper is None or self.project is None or self.user is None:
            raise RuntimeError(f"{self.name} adapter is not prepared")

        started_at = time.perf_counter()
        trace: dict[str, Any] = {
            "adapter": self.name,
            "query_id": query_id,
            "route": "",
            "planner_result": {},
            "retriever_used": [],
            "latency_ms": {},
            "error": "",
            "evidence_count": 0,
            "mapped_evidence_count": 0,
            "unmapped_evidence_count": 0,
        }
        try:
            output = self._call_graph(query, top_k)
            evidences, raw, graph_trace, answer = _extract_graph_output(output)
            raw = self._map_raw_trace_doc_ids(raw)
            hits, mapped_count, unmapped_count = self._convert_evidences(query_id, evidences, top_k, raw)
            node_latency = _node_latency(graph_trace, raw)
            trace.update(
                {
                    "route": raw.get("route") or raw.get("intent") or "",
                    "planner_result": raw.get("retrieval_plan") or {},
                    "retriever_used": raw.get("executed_retrievers") or raw.get("used_retrievers") or [],
                    "latency_ms": node_latency,
                    "retriever_hits": raw.get("retriever_hits") or {},
                    "retriever_elapsed_ms": raw.get("retriever_elapsed_ms") or {},
                    "evidence_count": len(evidences),
                    "mapped_evidence_count": mapped_count,
                    "unmapped_evidence_count": unmapped_count,
                    "graph_trace": graph_trace,
                    "raw": _safe_raw(raw),
                    "answer_context_doc_ids": raw.get("answer_context_doc_ids") or raw.get("final_answer_doc_ids_top10") or [],
                    "answer_context_count": raw.get("answer_context_count", 0),
                }
            )
            if answer is not None:
                self.context.extra.setdefault("answer_details", []).append(
                    {
                        "query_id": query_id,
                        "adapter": self.name,
                        "answer": answer,
                        "beir_doc_ids": [hit.doc_id for hit in hits],
                    }
                )
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            trace["latency_ms"]["total_ms"] = max(int(trace["latency_ms"].get("total_ms") or 0), elapsed_ms)
            logger.info(
                "stage=evaluation action=business_query_completed adapter=%s query_id=%s route=%s retriever_used=%s evidence_count=%s mapped=%s unmapped=%s latency_ms=%s",
                self.name,
                query_id,
                trace["route"],
                trace["retriever_used"],
                len(evidences),
                mapped_count,
                unmapped_count,
                elapsed_ms,
            )
            return hits
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            trace["error"] = str(exc)
            trace["latency_ms"] = {"total_ms": elapsed_ms}
            logger.exception(
                "stage=evaluation action=business_query_failed adapter=%s query_id=%s elapsed_ms=%s error=%s",
                self.name,
                query_id,
                elapsed_ms,
                exc,
            )
            return []
        finally:
            self.context.extra.setdefault("business_query_traces", {})[query_id] = trace

    def query_embedding_latency_ms(self, query_id: str) -> int:
        """Query embedding is timed inside the real retrieval graph."""

        return 0

    def _call_graph(self, query: str, top_k: int) -> Any:
        raise NotImplementedError

    def _convert_evidences(
        self,
        query_id: str,
        evidences: list[Any],
        top_k: int,
        raw: dict[str, Any],
    ) -> tuple[list[SearchHit], int, int]:
        assert self.context is not None
        assert self.mapper is not None
        counts = self.context.extra.setdefault("business_mapping_counts", {"mapped": 0, "unmapped": 0, "total": 0})
        hits: list[SearchHit] = []
        seen_doc_ids: set[str] = set()
        mapped_count = 0
        unmapped_count = 0
        for old_rank, evidence in enumerate(evidences, start=1):
            document_id = _attr(evidence, "document_id")
            chunk_id = _attr(evidence, "chunk_id")
            mapping = self.mapper.resolve(document_id, chunk_id)
            counts["total"] = int(counts.get("total", 0)) + 1
            if mapping is None:
                unmapped_count += 1
                counts["unmapped"] = int(counts.get("unmapped", 0)) + 1
                self.context.extra.setdefault("unmapped_evidence", []).append(
                    {
                        "query_id": query_id,
                        "adapter": self.name,
                        "document_id": document_id,
                        "chunk_id": chunk_id,
                        "score": _float(_attr(evidence, "score")),
                        "retriever": _attr(evidence, "retriever"),
                        "file_name": _attr(evidence, "file_name"),
                    }
                )
                continue
            if mapping.beir_doc_id in seen_doc_ids:
                continue
            mapped_count += 1
            counts["mapped"] = int(counts.get("mapped", 0)) + 1
            seen_doc_ids.add(mapping.beir_doc_id)
            hits.append(
                SearchHit(
                    doc_id=mapping.beir_doc_id,
                    score=_float(_attr(evidence, "score")),
                    rank=len(hits) + 1,
                    retriever=self.name,
                    title=mapping.title,
                    text=str(_attr(evidence, "content") or ""),
                    metadata={
                        "business_document_id": mapping.business_document_id,
                        "business_chunk_id": mapping.business_chunk_id,
                        "evidence_document_id": document_id,
                        "evidence_chunk_id": chunk_id,
                        "evidence_retriever": _attr(evidence, "retriever"),
                        "old_rank": old_rank,
                        "route": raw.get("route"),
                        "used_retrievers": raw.get("executed_retrievers") or raw.get("used_retrievers") or [],
                    },
                )
            )
            if len(hits) >= top_k:
                break
        return hits, mapped_count, unmapped_count

    def _map_raw_trace_doc_ids(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map graph debug document ids from business ids back to BEIR doc ids."""

        mapped_raw = dict(raw)
        for key in (
            "retrieval_before_rerank_doc_ids",
            "rerank_after_doc_ids",
            "evidence_before_judge_doc_ids",
            "evidence_after_judge_doc_ids",
            "answer_context_doc_ids",
            "final_answer_doc_ids_top10",
        ):
            if key in mapped_raw:
                mapped_raw[key] = self._map_debug_doc_ids(list(mapped_raw.get(key) or []))
        return mapped_raw

    def _map_debug_doc_ids(self, values: list[Any]) -> list[str]:
        assert self.mapper is not None
        mapped: list[str] = []
        for value in values:
            document_id, chunk_id = _parse_debug_doc_id(value)
            mapping = self.mapper.resolve(document_id, chunk_id)
            if mapping is not None and mapping.beir_doc_id not in mapped:
                mapped.append(mapping.beir_doc_id)
        return mapped


class AgenticRouterBusinessAdapter(BaseBusinessRAGAdapter):
    """Call the real intent/planner/retrieval path without answer generation."""

    name = "agentic_router"
    include_answer = False

    def _call_graph(self, query: str, top_k: int) -> Any:
        assert self.graph is not None and self.project is not None and self.user is not None and self.context is not None
        return self.graph.prepare(
            question=query,
            chat_type="project_chat",
            mode="auto",
            project_id=self.project.id,
            user=self.user,
            eval_mode=bool(self.context.config.eval_mode),
            return_evidence=True,
            retrieval_limit=top_k,
            candidate_k=int(self.context.config.candidate_k),
            rerank_top_k=int(self.context.config.rerank_top_k),
            eval_top_k=int(self.context.config.effective_eval_top_k),
            answer_top_k=int(self.context.config.effective_answer_top_k),
            retrieval_mode=str(self.context.config.retrieval_mode),
            require_real_reranker=bool(self.context.config.require_real_reranker),
            allow_reranker_fallback=bool(self.context.config.allow_reranker_fallback),
            reranker_score_order=str(self.context.config.reranker_score_order),
        )


class FullRAGBusinessAdapter(BaseBusinessRAGAdapter):
    """Call the complete retrieval graph, optionally including answer generation."""

    name = "full_rag"

    def _call_graph(self, query: str, top_k: int) -> Any:
        assert self.graph is not None and self.project is not None and self.user is not None and self.context is not None
        include_answer = bool(self.context.config.include_answer)
        enable_online_answer = bool(getattr(self.context.config, "enable_online_answer", False))
        if include_answer and not enable_online_answer:
            warning = "ONLINE_ANSWER_DISABLED: include_answer=true but enable_online_answer=false, skip online answer LLM."
            warnings = self.context.extra.setdefault("warnings", [])
            if warning not in warnings:
                warnings.append(warning)
            logger.info(
                "stage=evaluation action=online_answer_skipped adapter=%s include_answer=%s enable_online_answer=%s reason=disabled_by_flag",
                self.name,
                include_answer,
                enable_online_answer,
            )
        # BEIR 基准默认只评估 evidence，只有显式开启开关才允许走在线 answer LLM。
        if include_answer and enable_online_answer:
            return self.graph.run(
                question=query,
                chat_type="project_chat",
                mode="auto",
                project_id=self.project.id,
                user=self.user,
                eval_mode=bool(self.context.config.eval_mode),
                return_evidence=True,
                retrieval_limit=top_k,
                candidate_k=int(self.context.config.candidate_k),
                rerank_top_k=int(self.context.config.rerank_top_k),
                eval_top_k=int(self.context.config.effective_eval_top_k),
                answer_top_k=int(self.context.config.effective_answer_top_k),
                retrieval_mode=str(self.context.config.retrieval_mode),
                require_real_reranker=bool(self.context.config.require_real_reranker),
                allow_reranker_fallback=bool(self.context.config.allow_reranker_fallback),
                reranker_score_order=str(self.context.config.reranker_score_order),
            )
        return self.graph.prepare(
            question=query,
            chat_type="project_chat",
            mode="auto",
            project_id=self.project.id,
            user=self.user,
            eval_mode=bool(self.context.config.eval_mode),
            return_evidence=True,
            retrieval_limit=top_k,
            candidate_k=int(self.context.config.candidate_k),
            rerank_top_k=int(self.context.config.rerank_top_k),
            eval_top_k=int(self.context.config.effective_eval_top_k),
            answer_top_k=int(self.context.config.effective_answer_top_k),
            retrieval_mode=str(self.context.config.retrieval_mode),
            require_real_reranker=bool(self.context.config.require_real_reranker),
            allow_reranker_fallback=bool(self.context.config.allow_reranker_fallback),
            reranker_score_order=str(self.context.config.reranker_score_order),
        )


def _extract_graph_output(output: Any) -> tuple[list[Any], dict[str, Any], list[dict[str, Any]], str | None]:
    if isinstance(output, dict) and "raw" in output:
        trace_items = output.get("trace_steps")
        if not isinstance(trace_items, list):
            trace_items = output.get("trace")
        return list(output.get("evidences") or []), dict(output.get("raw") or {}), list(trace_items or []), output.get("answer")
    if isinstance(output, dict):
        trace_items = output.get("trace_steps")
        if not isinstance(trace_items, list):
            trace_items = output.get("trace")
        return list(output.get("evidences") or []), dict(output.get("raw") or {}), list(trace_items or []), output.get("answer")
    return [], {}, [], None


def _node_latency(trace_items: list[dict[str, Any]], raw: dict[str, Any]) -> dict[str, int]:
    latencies = {f"{key}_ms": 0 for key in NODE_KEYS}
    for index, item in enumerate(trace_items):
        key = NODE_KEYS[index] if index < len(NODE_KEYS) else f"node_{index + 1}"
        if key == "query_profile":
            continue
        if key == "retry_retrieval":
            latencies["retrieval_ms"] = latencies.get("retrieval_ms", 0) + int(item.get("elapsed_ms") or 0)
            continue
        latencies[f"{key}_ms"] = latencies.get(f"{key}_ms", 0) + int(item.get("elapsed_ms") or 0)
    rerank_ms = int(raw.get("rerank_elapsed_ms") or 0) + int(raw.get("retry_rerank_elapsed_ms") or 0)
    if rerank_ms > 0:
        latencies["rerank_ms"] = rerank_ms
        latencies["retrieval_ms"] = max(0, int(latencies.get("retrieval_ms") or 0) - rerank_ms)
    else:
        latencies.setdefault("rerank_ms", 0)
    latencies["lightweight_filter_ms"] = int(raw.get("lightweight_filter_ms") or 0)
    latencies["llm_evidence_judge_ms"] = int(raw.get("llm_evidence_judge_ms") or 0)
    latencies["total_ms"] = sum(
        int(value)
        for key, value in latencies.items()
        if key in {"intent_ms", "query_decompose_ms", "planner_ms", "retrieval_ms", "rerank_ms", "evidence_judge_ms", "answer_ms"}
    )
    return latencies


def _safe_raw(raw: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "intent",
        "route",
        "eval_original_route_decision",
        "eval_original_query_profile",
        "sub_queries",
        "query_profile",
        "retrieval_plan",
        "planned_retrievers",
        "executed_retrievers",
        "skipped_retrievers",
        "retriever_hits",
        "retriever_elapsed_ms",
        "rerank_details",
        "reranker_runtime",
        "retrieval_before_rerank_doc_ids",
        "retrieval_before_rerank_scores",
        "rerank_after_doc_ids",
        "rerank_after_scores",
        "evidence_after_judge_doc_ids",
        "answer_context_doc_ids",
        "final_answer_doc_ids_top10",
        "answer_context_count",
        "candidate_k",
        "rerank_top_k",
        "eval_top_k",
        "answer_top_k",
        "retrieval_mode",
        "evidence_judgement",
        "retry_count",
        "retry_reason",
        "model_routes",
    )
    return {key: raw.get(key) for key in keys if key in raw}


def _attr(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_debug_doc_id(value: Any) -> tuple[Any, Any]:
    text = str(value or "")
    if ":" not in text:
        return value, None
    document_id, chunk_id = text.split(":", 1)
    return document_id, chunk_id
