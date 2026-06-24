"""Unified BEIR evaluation runner."""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eval.beir.adapters import AdapterContext, UnsupportedRetrieverError, make_retrieval_adapter
from eval.beir.bootstrap import ensure_backend_path
from eval.beir.datasets import load_beir_dataset
from eval.beir.fusion import fuse_hits, hits_to_beir_results
from eval.beir.metrics import evaluate_beir_results
from eval.beir.milvus_store import BeirMilvusStore
from eval.beir.report_writer import write_compare_report, write_eval_reports
from eval.beir.rerank import BeirReranker
from eval.beir.types import BeirCorpus, BeirQrels, BeirQueries, SearchHit

logger = logging.getLogger(__name__)

LOCAL_EMBEDDING_PROVIDERS = {"local", "local_qwen", "qwen_local"}
REPORT_HIT_KS = (1, 3, 5, 10, 50, 100)
COMPARE_STRATEGIES = ("bm25", "milvus", "hybrid", "hybrid_reranker", "agentic_router", "full_rag")
MILVUS_RETRIEVER = "milvus"


@dataclass(frozen=True)
class BeirEvalConfig:
    """Configuration for a BEIR evaluation run."""

    dataset: str
    retriever: str
    top_k: int
    rerank: bool
    collection_name: str
    data_dir: Path
    reports_dir: Path
    mode: str = "eval"
    retrievers: tuple[str, ...] = ()
    fusion: str = "rrf"
    weights: dict[str, float] = field(default_factory=dict)
    candidate_k: int = 100
    rerank_top_k: int = 100
    eval_top_k: int = 100
    answer_top_k: int = 10
    final_top_k: int | None = None
    retrieval_mode: str = "smart"
    require_real_reranker: bool = True
    allow_reranker_fallback: bool = False
    split: str = "test"
    k_values: tuple[int, ...] = REPORT_HIT_KS
    keyword_adapter: str = "bm25"
    batch_size: int = 32
    embedding_batch_size: int = 32
    query_batch_size: int = 32
    force_reindex: bool = False
    skip_index: bool = False
    limit_queries: int | None = None
    max_queries: int | None = None
    include_answer: bool = False
    enable_online_answer: bool = False
    business_project_code: str = ""
    business_user_id: str = "beir_eval_user"
    business_index_targets: tuple[str, ...] = ("milvus", "bm25", "ripgrep")
    eval_mode: bool = True
    force_business_reindex: bool = False
    reranker_score_order: str = "desc"
    output_dir: Path | None = None
    verbose: bool = False

    @property
    def effective_output_dir(self) -> Path:
        """Return the directory for the current run's reports."""

        return self.output_dir or self.reports_dir

    @property
    def effective_max_queries(self) -> int | None:
        """Support both the old limit_queries and new max_queries option."""

        return self.max_queries if self.max_queries is not None else self.limit_queries

    @property
    def corpus_batch_size(self) -> int:
        """Document embedding batch size."""

        return self.embedding_batch_size or self.batch_size

    @property
    def effective_eval_top_k(self) -> int:
        """Maximum retrieval result count retained for BEIR metrics."""

        return max(1, int(self.eval_top_k or self.top_k or 100))

    @property
    def effective_answer_top_k(self) -> int:
        """Final evidence count fed to answer LLM."""

        return max(1, int(self.answer_top_k or 10))


@dataclass(frozen=True)
class IndexPlan:
    """Corpus indexing decision for Milvus evaluation."""

    should_index: bool
    reason: str
    collection_exists: bool
    existing_count: int | None


@dataclass(frozen=True)
class RetrievalPlan:
    """Resolved retrieval strategy for one evaluation run."""

    name: str
    retrievers: tuple[str, ...]
    fusion: str
    rerank: bool


class BeirEvaluationRunner:
    """Coordinate dataset loading, indexing, retrieval, metrics and reports."""

    def __init__(self, config: BeirEvalConfig) -> None:
        ensure_backend_path()
        self.config = config

    def run(self) -> dict[str, Any]:
        """Execute the configured BEIR mode."""

        from app.core.config import get_settings

        settings = get_settings()
        self._configure_ripgrep_binary(settings)
        total_started_at = time.perf_counter()
        base_latency: dict[str, float] = {}

        if self.config.mode == "check_reranker":
            payload = self._run_check_reranker(total_started_at)
            self._write_reports(self.config.effective_output_dir, payload)
            return payload

        corpus, queries, qrels, dataset_path = self._load_dataset(base_latency)
        query_ids = self._select_query_ids(queries, qrels)
        output_dir = self.config.effective_output_dir

        if self.config.mode == "info":
            payload = self._empty_payload(
                corpus=corpus,
                queries=queries,
                qrels=qrels,
                query_ids=query_ids,
                dataset_path=dataset_path,
                latency=base_latency,
                index_plan=None,
            )
            payload["latency"]["total_ms"] = int((time.perf_counter() - total_started_at) * 1000)
            self._write_reports(output_dir, payload)
            return payload

        if self.config.mode == "business_index":
            db = None
            try:
                if "milvus" in {target.lower() for target in self.config.business_index_targets}:
                    self._configure_embedding_device(settings)
                from app.core.database import SessionLocal, init_database

                init_database()
                db = SessionLocal()
                business_result = self._run_business_index(db, settings, corpus)
                payload = self._empty_payload(
                    corpus=corpus,
                    queries=queries,
                    qrels=qrels,
                    query_ids=query_ids,
                    dataset_path=dataset_path,
                    latency=base_latency,
                    index_plan=None,
                )
                payload["business_index_result"] = business_result
                payload["warnings"] = _unique_preserve_order([*payload.get("warnings", []), *business_result.get("warnings", [])])
                payload["latency"]["business_index_ms"] = float(business_result.get("elapsed_ms", 0))
                payload["latency"]["total_ms"] = int((time.perf_counter() - total_started_at) * 1000)
                self._write_reports(output_dir, payload)
                return payload
            finally:
                if db is not None:
                    db.close()

        plan = self._build_retrieval_plan(self.config.retriever)
        needs_milvus = self.config.mode == "index" or self._plan_uses_milvus(plan) or self.config.mode == "compare"
        needs_business_rag = self._plan_uses_business_rag(plan) or self.config.mode == "compare"
        needs_db = needs_milvus or plan.rerank or needs_business_rag or self.config.mode == "compare"
        db = None
        embedding_service = None
        milvus_store = None

        try:
            if needs_milvus or needs_business_rag:
                self._configure_embedding_device(settings)
            if needs_milvus:
                from app.core.database import SessionLocal
                from app.services.embedding_service import EmbeddingService

                db = SessionLocal()
                embedding_service = EmbeddingService(db)
                milvus_store = BeirMilvusStore(self.config.collection_name, settings=settings)
            elif needs_db:
                from app.core.database import SessionLocal

                db = SessionLocal()

            if self.config.mode == "index":
                if milvus_store is None or embedding_service is None:
                    raise RuntimeError("index mode requires Milvus runtime")
                index_plan, index_latency = self._run_corpus_indexing(milvus_store, corpus, embedding_service)
                base_latency.update(index_latency)
                payload = self._empty_payload(
                    corpus=corpus,
                    queries=queries,
                    qrels=qrels,
                    query_ids=query_ids,
                    dataset_path=dataset_path,
                    latency=base_latency,
                    index_plan=index_plan,
                )
                payload["latency"]["total_ms"] = int((time.perf_counter() - total_started_at) * 1000)
                self._write_reports(output_dir, payload)
                return payload

            if self.config.mode == "compare":
                if milvus_store is None:
                    raise RuntimeError("compare mode requires Milvus runtime for Milvus-based strategies")
                compare_payload = self._run_compare(
                    corpus=corpus,
                    queries=queries,
                    qrels=qrels,
                    query_ids=query_ids,
                    dataset_path=dataset_path,
                    settings=settings,
                    db=db,
                    embedding_service=embedding_service,
                    milvus_store=milvus_store,
                    base_latency=base_latency,
                    total_started_at=total_started_at,
                )
                return compare_payload

            index_plan = None
            if self._plan_uses_milvus(plan):
                if milvus_store is None or embedding_service is None:
                    raise RuntimeError("Milvus plan requires Milvus runtime")
                if self.config.mode == "full":
                    index_plan, index_latency = self._run_corpus_indexing(milvus_store, corpus, embedding_service)
                else:
                    index_plan, index_latency = self._check_collection_for_evaluation(milvus_store, len(corpus))
                base_latency.update(index_latency)
            else:
                logger.info("stage=corpus_indexing status=skipped reason=retriever_does_not_use_milvus plan=%s", plan.name)
                base_latency.update(
                    {
                        "index_check_ms": 0,
                        "corpus_embedding_total_ms": 0,
                        "corpus_embedding_avg_ms": 0,
                        "corpus_upsert_total_ms": 0,
                        "corpus_upsert_avg_ms": 0,
                    }
                )

            payload = self._evaluate_plan(
                plan=plan,
                corpus=corpus,
                queries=queries,
                qrels=qrels,
                query_ids=query_ids,
                dataset_path=dataset_path,
                settings=settings,
                db=db,
                embedding_service=embedding_service,
                milvus_store=milvus_store,
                base_latency=base_latency,
                index_plan=index_plan,
                total_started_at=total_started_at,
            )
            self._write_reports(output_dir, payload)
            return payload
        finally:
            if db is not None:
                db.close()

    def _load_dataset(self, latency: dict[str, float]) -> tuple[BeirCorpus, BeirQueries, BeirQrels, Path]:
        """Load BEIR data and log the dataset_loading stage."""

        logger.info(
            "stage=dataset_loading status=started dataset=%s split=%s data_dir=%s",
            self.config.dataset,
            self.config.split,
            self.config.data_dir,
        )
        started_at = time.perf_counter()
        corpus, queries, qrels, dataset_path = load_beir_dataset(self.config.data_dir, self.config.dataset, self.config.split)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        latency["dataset_load_ms"] = elapsed_ms
        logger.info(
            "stage=dataset_loading status=completed dataset=%s split=%s corpus_count=%s query_count=%s qrels_count=%s data_path=%s elapsed_ms=%s",
            self.config.dataset,
            self.config.split,
            len(corpus),
            len(queries),
            sum(len(items) for items in qrels.values()),
            dataset_path,
            elapsed_ms,
        )
        return corpus, queries, qrels, dataset_path

    def _select_query_ids(self, queries: BeirQueries, qrels: BeirQrels) -> list[str]:
        """Return qrels-backed query ids, optionally capped for smoke tests."""

        query_ids = [query_id for query_id in qrels if query_id in queries]
        if self.config.effective_max_queries is not None:
            query_ids = query_ids[: self.config.effective_max_queries]
        return query_ids

    def _run_business_index(self, db: Any, settings: Any, corpus: BeirCorpus) -> dict[str, Any]:
        """Import BEIR corpus into the real business RAG index."""

        from eval.beir.business_index import BeirBusinessIndexService, BusinessIndexConfig

        logger.info(
            "stage=corpus_indexing status=started mode=business_index dataset=%s split=%s project_code=%s targets=%s batch_size=%s force_business_reindex=%s",
            self.config.dataset,
            self.config.split,
            self.config.business_project_code,
            ",".join(self.config.business_index_targets),
            self.config.corpus_batch_size,
            self.config.force_business_reindex,
        )
        started_at = time.perf_counter()
        service = BeirBusinessIndexService(
            db=db,
            settings=settings,
            config=BusinessIndexConfig(
                dataset=self.config.dataset,
                split=self.config.split,
                business_project_code=self.config.business_project_code,
                business_user_id=self.config.business_user_id,
                business_index_targets=self.config.business_index_targets,
                force_reindex=self.config.force_business_reindex,
                embedding_batch_size=self.config.corpus_batch_size,
            ),
        )
        result = service.run(corpus).to_dict()
        logger.info(
            "stage=corpus_indexing status=completed mode=business_index project_id=%s imported=%s indexed=%s elapsed_ms=%s",
            result.get("project_id"),
            result.get("imported_count"),
            result.get("indexed_count"),
            int((time.perf_counter() - started_at) * 1000),
        )
        return result

    def _run_corpus_indexing(
        self,
        milvus_store: BeirMilvusStore,
        corpus: BeirCorpus,
        embedding_service: Any,
    ) -> tuple[IndexPlan, dict[str, float]]:
        """Run or skip corpus indexing according to collection state."""

        logger.info(
            "stage=corpus_indexing status=started mode=%s dataset=%s split=%s collection=%s corpus_count=%s batch_size=%s force_reindex=%s skip_index=%s",
            self.config.mode,
            self.config.dataset,
            self.config.split,
            self.config.collection_name,
            len(corpus),
            self.config.corpus_batch_size,
            self.config.force_reindex,
            self.config.skip_index,
        )
        check_started_at = time.perf_counter()
        index_plan = self._build_index_plan(milvus_store, len(corpus))
        index_check_ms = int((time.perf_counter() - check_started_at) * 1000)
        logger.info(
            "stage=corpus_indexing action=index_plan should_index=%s reason=%s collection_exists=%s existing_count=%s corpus_count=%s index_check_ms=%s",
            index_plan.should_index,
            index_plan.reason,
            index_plan.collection_exists,
            index_plan.existing_count,
            len(corpus),
            index_check_ms,
        )
        latency = {"index_check_ms": index_check_ms}
        if not index_plan.should_index:
            logger.info("stage=corpus_indexing status=skipped reason=%s", index_plan.reason)
            latency.update(
                {
                    "corpus_embedding_total_ms": 0,
                    "corpus_embedding_avg_ms": 0,
                    "corpus_upsert_total_ms": 0,
                    "corpus_upsert_avg_ms": 0,
                }
            )
            return index_plan, latency

        if self.config.force_reindex:
            milvus_store.drop_collection()

        result = milvus_store.upsert_corpus(
            dataset=self.config.dataset,
            split=self.config.split,
            corpus=corpus,
            embed_texts=embedding_service.embed_texts,
            batch_size=self.config.corpus_batch_size,
        )
        latency.update(
            {
                "corpus_embedding_total_ms": float(result.get("embedding_total_ms", 0)),
                "corpus_embedding_avg_ms": float(result.get("embedding_avg_ms", 0)),
                "corpus_upsert_total_ms": float(result.get("upsert_total_ms", 0)),
                "corpus_upsert_avg_ms": float(result.get("upsert_avg_ms", 0)),
            }
        )
        logger.info(
            "stage=corpus_indexing status=completed reason=%s result=%s",
            index_plan.reason,
            result,
        )
        return index_plan, latency

    def _check_collection_for_evaluation(self, milvus_store: BeirMilvusStore, corpus_count: int) -> tuple[IndexPlan, dict[str, float]]:
        """Verify an existing collection for eval mode without corpus embedding."""

        logger.info(
            "stage=corpus_indexing status=started mode=eval action=check_existing collection=%s dataset=%s skip_index=%s",
            self.config.collection_name,
            self.config.dataset,
            self.config.skip_index,
        )
        started_at = time.perf_counter()
        collection_exists = milvus_store.collection_exists()
        if not collection_exists:
            raise RuntimeError(
                f"Milvus collection does not exist for eval mode: collection={self.config.collection_name}. "
                "Run --mode index or --mode full first."
            )
        existing_count = milvus_store.count_dataset_documents(self.config.dataset)
        index_check_ms = int((time.perf_counter() - started_at) * 1000)
        if existing_count != corpus_count and not self.config.skip_index:
            raise RuntimeError(
                "Milvus collection exists but document count does not match current BEIR corpus; "
                f"collection={self.config.collection_name} dataset={self.config.dataset} "
                f"existing_count={existing_count} corpus_count={corpus_count}. "
                "Run --mode index --force_reindex, or pass --skip_index to use it anyway."
            )
        reason = "skip_index" if self.config.skip_index else "collection_ready"
        logger.info(
            "stage=corpus_indexing status=skipped reason=%s existing_count=%s corpus_count=%s index_check_ms=%s",
            reason,
            existing_count,
            corpus_count,
            index_check_ms,
        )
        return IndexPlan(False, reason, True, existing_count), {
            "index_check_ms": index_check_ms,
            "corpus_embedding_total_ms": 0,
            "corpus_embedding_avg_ms": 0,
            "corpus_upsert_total_ms": 0,
            "corpus_upsert_avg_ms": 0,
        }

    def _build_index_plan(self, milvus_store: Any, corpus_count: int) -> IndexPlan:
        """Decide whether corpus indexing is needed before query evaluation."""

        collection_exists = milvus_store.collection_exists()
        if self.config.skip_index:
            if not collection_exists:
                raise RuntimeError(f"--skip_index requires existing Milvus collection: collection={self.config.collection_name}")
            existing_count = milvus_store.count_dataset_documents(self.config.dataset)
            return IndexPlan(False, "skip_index", collection_exists, existing_count)

        if self.config.force_reindex:
            existing_count = milvus_store.count_dataset_documents(self.config.dataset) if collection_exists else None
            return IndexPlan(True, "force_reindex", collection_exists, existing_count)

        if not collection_exists:
            return IndexPlan(True, "collection_missing", False, 0)

        existing_count = milvus_store.count_dataset_documents(self.config.dataset)
        if existing_count == corpus_count:
            return IndexPlan(False, "collection_ready", True, existing_count)
        raise RuntimeError(
            "Milvus collection exists but document count does not match current BEIR corpus; "
            f"collection={self.config.collection_name} dataset={self.config.dataset} "
            f"existing_count={existing_count} corpus_count={corpus_count}. "
            "Pass --force_reindex to rebuild the collection, or pass --skip_index to evaluate the existing collection."
        )

    def _evaluate_plan(
        self,
        plan: RetrievalPlan,
        corpus: BeirCorpus,
        queries: BeirQueries,
        qrels: BeirQrels,
        query_ids: list[str],
        dataset_path: Path,
        settings: Any,
        db: Any | None,
        embedding_service: Any | None,
        milvus_store: BeirMilvusStore | None,
        base_latency: dict[str, float],
        index_plan: IndexPlan | None,
        total_started_at: float,
    ) -> dict[str, Any]:
        """Evaluate one retrieval plan."""

        logger.info(
            "stage=evaluation status=started action=query_retrieval plan=%s retrievers=%s fusion=%s rerank=%s query_count=%s",
            plan.name,
            ",".join(plan.retrievers),
            plan.fusion,
            plan.rerank,
            len(query_ids),
        )
        if not self._plan_uses_milvus(plan):
            logger.info("stage=query_embedding status=skipped reason=retriever_does_not_require_embedding plan=%s", plan.name)
            logger.info("stage=milvus_search status=skipped reason=retriever_does_not_use_milvus plan=%s", plan.name)
        context = AdapterContext(
            dataset=self.config.dataset,
            split=self.config.split,
            corpus=corpus,
            queries=queries,
            qrels=qrels,
            query_ids=query_ids,
            config=self.config,
            settings=settings,
            embedding_service=embedding_service,
            milvus_store=milvus_store,
            db=db,
        )
        adapters = [make_retrieval_adapter(name) for name in plan.retrievers]
        for adapter in adapters:
            adapter.prepare(context)

        if self.config.require_real_reranker and (plan.rerank or self._plan_uses_business_rag(plan)):
            self._warmup_reranker_for_eval(db)

        reranker = (
            BeirReranker(
                db,
                score_order=self.config.reranker_score_order,
                rerank_top_k=self.config.rerank_top_k,
                require_real_reranker=self.config.require_real_reranker,
                allow_fallback=self.config.allow_reranker_fallback,
            )
            if plan.rerank
            else None
        )
        if reranker is not None:
            logger.info(
                "stage=rerank status=initialized reranker_enabled=true reranker_model_name=%s "
                "reranker_model_provider=%s reranker_model_configured=%s reranker_model_loaded=%s reranker_score_order=%s",
                reranker.model_name,
                reranker.model_provider or "-",
                reranker.model_configured,
                reranker.model_loaded,
                reranker.score_order,
            )
        eval_top_k = self.config.effective_eval_top_k
        candidate_k = max(self.config.candidate_k, self.config.rerank_top_k, eval_top_k)
        query_hits: dict[str, list[SearchHit]] = {}
        query_hits_before_rerank: dict[str, list[SearchHit]] = {}
        traces: list[dict[str, Any]] = []
        rerank_debug_rows: list[dict[str, Any]] = []
        rerank_warnings: list[str] = []
        rerank_candidate_counts: list[int] = []
        reranker_info: dict[str, Any] = {}
        retrieval_started_at = time.perf_counter()

        for index, query_id in enumerate(query_ids, start=1):
            query = queries[query_id]
            query_started_at = time.perf_counter()
            embedding_ms = sum(adapter.query_embedding_latency_ms(query_id) for adapter in adapters)
            retrieval_ms = 0
            fusion_ms = 0
            rerank_ms = 0
            planner_ms = 0
            raw_groups: dict[str, list[SearchHit]] = {}
            candidates: list[SearchHit] = []
            final_hits: list[SearchHit] = []
            before_rerank_hits: list[SearchHit] = []
            rerank_input_samples: list[dict[str, Any]] = []
            business_trace: dict[str, Any] = {}
            error = ""
            try:
                retrieval_started = time.perf_counter()
                for adapter in adapters:
                    raw_groups[adapter.name] = adapter.search(query_id, query, candidate_k)
                retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)
                business_trace = dict(context.extra.get("business_query_traces", {}).get(query_id) or {})
                business_latency = business_trace.get("latency_ms") or {}
                if business_trace:
                    retrieval_ms = int(business_latency.get("retrieval_ms") or retrieval_ms)
                    planner_ms = int(business_latency.get("planner_ms") or planner_ms)
                    rerank_ms = int(business_latency.get("rerank_ms") or rerank_ms)
                    error = str(business_trace.get("error") or "")

                if len(raw_groups) > 1:
                    fusion_started = time.perf_counter()
                    candidates = fuse_hits(raw_groups, plan.fusion, candidate_k, weights=self.config.weights)
                    fusion_ms = int((time.perf_counter() - fusion_started) * 1000)
                else:
                    candidates = next(iter(raw_groups.values()), [])

                before_rerank_hits = self._rerankless_top_hits(candidates, eval_top_k)
                if reranker is not None:
                    expected_doc_ids = {doc_id for doc_id, relevance in qrels.get(query_id, {}).items() if relevance > 0}
                    rerank_started = time.perf_counter()
                    rerank_result = reranker.rerank(
                        query_id=query_id,
                        query=query,
                        hits=candidates[: self.config.rerank_top_k],
                        corpus=corpus,
                        expected_doc_ids=expected_doc_ids,
                        limit=eval_top_k,
                    )
                    rerank_ms = int((time.perf_counter() - rerank_started) * 1000)
                    final_hits = rerank_result.hits
                    rerank_debug_rows.extend(rerank_result.debug_rows)
                    rerank_warnings.extend(rerank_result.warnings)
                    rerank_input_samples = rerank_result.input_samples
                    rerank_candidate_counts.append(rerank_result.candidate_count)
                    reranker_info = {
                        "model_name": rerank_result.model_name,
                        "model_provider": rerank_result.model_provider,
                        "model_configured": rerank_result.model_configured,
                        "model_loaded": rerank_result.model_loaded,
                        "score_order": rerank_result.score_order,
                    }
                    logger.info(
                        "stage=rerank status=completed reranker_enabled=true reranker_model_name=%s "
                        "query_id=%s rerank_candidate_count=%s rerank_total_ms=%s rerank_avg_ms=%.2f",
                        rerank_result.model_name,
                        query_id,
                        rerank_result.candidate_count,
                        rerank_ms,
                        rerank_ms / max(rerank_result.candidate_count, 1),
                    )
                else:
                    final_hits = before_rerank_hits[:eval_top_k]
            except Exception as exc:
                error = str(exc)
                business_trace = dict(context.extra.get("business_query_traces", {}).get(query_id) or {})
                logger.exception(
                    "stage=evaluation action=query_failed query_index=%s/%s query_id=%s plan=%s error=%s",
                    index,
                    len(query_ids),
                    query_id,
                    plan.name,
                    error,
                )

            total_ms = int((time.perf_counter() - query_started_at) * 1000) + int(embedding_ms)
            query_hits[query_id] = final_hits
            if plan.rerank:
                query_hits_before_rerank[query_id] = before_rerank_hits
            latency_payload = {
                "total_ms": total_ms,
                "embedding_ms": embedding_ms,
                "retrieval_ms": retrieval_ms,
                "fusion_ms": fusion_ms,
                "rerank_ms": rerank_ms,
                "planner_ms": planner_ms,
            }
            if business_trace:
                for key, value in (business_trace.get("latency_ms") or {}).items():
                    if key.endswith("_ms") and key != "total_ms":
                        latency_payload[key] = int(value or 0)
            trace = self._build_query_trace(
                query_id=query_id,
                query_text=query,
                final_hits=final_hits,
                raw_groups=raw_groups,
                candidates=candidates,
                before_rerank_hits=before_rerank_hits,
                qrels=qrels,
                plan=plan,
                latency_ms=latency_payload,
                error=error,
                rerank_input_samples=rerank_input_samples,
                reranker_info=reranker_info,
                business_trace=business_trace,
            )
            traces.append(trace)
            logger.info(
                "stage=evaluation action=query_completed dataset=%s query_index=%s/%s query_id=%s plan=%s elapsed_ms=%s hit_qrels=%s first_hit_rank=%s qrels_hit=%s top_docs=%s rankings=%s",
                self.config.dataset,
                index,
                len(query_ids),
                query_id,
                plan.name,
                total_ms,
                trace["hit_qrels"],
                trace["first_hit_rank"],
                bool(trace["hit_qrels"]),
                trace["retrieved_doc_ids"][:eval_top_k],
                trace["rankings"][:eval_top_k],
            )

        retrieval_total_ms = int((time.perf_counter() - retrieval_started_at) * 1000)
        logger.info("stage=evaluation status=completed action=query_retrieval plan=%s elapsed_ms=%s", plan.name, retrieval_total_ms)
        results = hits_to_beir_results(query_hits)
        scoped_qrels = {query_id: qrels[query_id] for query_id in query_ids if query_id in qrels}
        logger.info("stage=evaluation status=started action=metrics query_count=%s", len(scoped_qrels))
        evaluation_started_at = time.perf_counter()
        metrics = self._evaluate_metrics(scoped_qrels, results)
        evaluation_ms = int((time.perf_counter() - evaluation_started_at) * 1000)
        logger.info("stage=evaluation status=completed action=metrics metrics=%s elapsed_ms=%s", metrics.get("flat", {}), evaluation_ms)

        latency = self._aggregate_latency(base_latency, traces, evaluation_ms, total_started_at)
        if plan.rerank:
            logger.info(
                "stage=rerank status=summary reranker_enabled=true reranker_model_name=%s "
                "rerank_candidate_count=%.2f rerank_total_ms=%.2f rerank_avg_ms=%.2f",
                reranker_info.get("model_name", "-"),
                sum(rerank_candidate_counts) / max(len(rerank_candidate_counts), 1),
                latency.get("rerank_total_ms", 0.0),
                latency.get("rerank_avg_ms", 0.0),
            )
        rerank_summary = self._build_rerank_summary(
            plan=plan,
            qrels=scoped_qrels,
            query_hits_before_rerank=query_hits_before_rerank,
            metrics_after=metrics,
            traces=traces,
            reranker_info=reranker_info,
        )
        payload_warnings = self._warnings()
        payload_warnings.extend(context.extra.get("warnings", []))
        payload_warnings.extend(_unique_preserve_order(rerank_warnings))
        if rerank_summary.get("degraded"):
            payload_warnings.append(
                "RERANK_DEGRADED: rerank_after NDCG@10 or MRR@10 dropped by more than 5% compared with rerank_before."
            )
        business_summary = self._business_summary(context, plan)
        failed_queries = [
            {
                "query_id": trace["query_id"],
                "error": trace.get("error") or trace.get("business_trace", {}).get("error", ""),
            }
            for trace in traces
            if trace.get("error") or trace.get("business_trace", {}).get("error")
        ]
        payload = {
            "config": self._config_payload(corpus, queries, qrels, query_ids, dataset_path, plan, index_plan),
            "metrics": metrics,
            "results": results,
            "query_traces": traces,
            "hit_summary": self._hit_summary(traces),
            "latency": latency,
            "warnings": _unique_preserve_order(payload_warnings),
            "errors": [item["error"] for item in failed_queries if item.get("error")],
            "failed_queries": failed_queries,
            "rerank_summary": rerank_summary,
            "rerank_debug_rows": rerank_debug_rows,
            "business_summary": business_summary,
            "unmapped_evidence": context.extra.get("unmapped_evidence", []),
            "answer_details": context.extra.get("answer_details", []),
        }
        return payload

    def _warmup_reranker_for_eval(self, db: Any | None) -> None:
        """Warm up the local reranker once per CLI evaluation process."""

        if db is None:
            return
        from app.services.reranker_service import RerankerService

        started_at = time.perf_counter()
        logger.info("stage=rerank status=started action=warmup_for_eval")
        RerankerService(db).warmup_local_reranker()
        logger.info(
            "stage=rerank status=completed action=warmup_for_eval elapsed_ms=%s",
            int((time.perf_counter() - started_at) * 1000),
        )

    def _run_compare(
        self,
        corpus: BeirCorpus,
        queries: BeirQueries,
        qrels: BeirQrels,
        query_ids: list[str],
        dataset_path: Path,
        settings: Any,
        db: Any | None,
        embedding_service: Any | None,
        milvus_store: BeirMilvusStore,
        base_latency: dict[str, float],
        total_started_at: float,
    ) -> dict[str, Any]:
        """Run standard strategy comparison and write compare_report.md."""

        output_dir = self.config.effective_output_dir
        index_plan = None
        milvus_ready_error = ""
        index_latency: dict[str, float] = {}
        if self.config.force_reindex:
            if embedding_service is None:
                raise RuntimeError("compare --force_reindex requires embedding_service")
            index_plan, index_latency = self._run_corpus_indexing(milvus_store, corpus, embedding_service)
        else:
            try:
                index_plan, index_latency = self._check_collection_for_evaluation(milvus_store, len(corpus))
            except Exception as exc:
                milvus_ready_error = str(exc)
                logger.warning("stage=corpus_indexing status=skipped_for_compare error=%s", milvus_ready_error)

        runs: list[dict[str, Any]] = []
        for strategy in COMPARE_STRATEGIES:
            plan = self._build_retrieval_plan(strategy)
            strategy_output_dir = output_dir / strategy
            if self._plan_uses_milvus(plan) and milvus_ready_error:
                runs.append({"name": strategy, "metrics": {"flat": {}}, "latency": {}, "error": milvus_ready_error})
                continue
            try:
                payload = self._evaluate_plan(
                    plan=plan,
                    corpus=corpus,
                    queries=queries,
                    qrels=qrels,
                    query_ids=query_ids,
                    dataset_path=dataset_path,
                    settings=settings,
                    db=db,
                    embedding_service=embedding_service,
                    milvus_store=milvus_store,
                    base_latency={**base_latency, **index_latency},
                    index_plan=index_plan,
                    total_started_at=time.perf_counter(),
                )
                self._write_reports(strategy_output_dir, payload)
                runs.append(
                    {
                        "name": strategy,
                        "metrics": payload["metrics"],
                        "latency": payload["latency"],
                        "warnings": payload.get("warnings", []),
                        "rerank_summary": payload.get("rerank_summary", {}),
                        "report_dir": str(strategy_output_dir),
                        "error": "",
                    }
                )
            except UnsupportedRetrieverError as exc:
                logger.warning("stage=evaluation action=compare_strategy_unsupported strategy=%s error=%s", strategy, exc)
                runs.append({"name": strategy, "metrics": {"flat": {}}, "latency": {}, "error": str(exc)})
            except Exception as exc:
                logger.exception("stage=evaluation action=compare_strategy_failed strategy=%s error=%s", strategy, exc)
                runs.append({"name": strategy, "metrics": {"flat": {}}, "latency": {}, "error": str(exc)})

        compare_payload = {
            "dataset": self.config.dataset,
            "split": self.config.split,
            "query_count": len(query_ids),
            "corpus_count": len(corpus),
            "runs": runs,
            "latency": {"total_ms": int((time.perf_counter() - total_started_at) * 1000)},
        }
        logger.info("stage=report_writing status=started output_dir=%s mode=compare", output_dir)
        started_at = time.perf_counter()
        compare_path = write_compare_report(output_dir, compare_payload)
        logger.info(
            "stage=report_writing status=completed compare_report=%s elapsed_ms=%s",
            compare_path,
            int((time.perf_counter() - started_at) * 1000),
        )
        compare_payload["compare_report"] = str(compare_path)
        return compare_payload

    def _write_reports(self, output_dir: Path, payload: dict[str, Any]) -> None:
        """Write standard report files with stage logging."""

        logger.info("stage=report_writing status=started output_dir=%s", output_dir)
        payload.setdefault("latency", {})["report_write_ms"] = 0
        started_at = time.perf_counter()
        paths = write_eval_reports(output_dir, payload)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        payload["latency"]["report_write_ms"] = elapsed_ms
        write_eval_reports(output_dir, payload)
        logger.info("stage=report_writing status=completed paths=%s elapsed_ms=%s", paths, elapsed_ms)

    def _build_retrieval_plan(self, retriever: str) -> RetrievalPlan:
        """Resolve CLI retriever/retrievers into a concrete retrieval plan."""

        if self.config.retrievers:
            retrievers = tuple(_normalize_retriever_name(name) for name in self.config.retrievers)
            uses_business = any(name in {"agentic_router", "full_rag"} for name in retrievers)
            return RetrievalPlan(
                name="+".join(retrievers),
                retrievers=retrievers,
                fusion=self.config.fusion,
                rerank=False if uses_business else self.config.rerank,
            )

        normalized = _normalize_retriever_name(retriever)
        if normalized in {"hybrid", "rrf"}:
            return RetrievalPlan(
                name="hybrid",
                retrievers=(MILVUS_RETRIEVER, _normalize_retriever_name(self.config.keyword_adapter)),
                fusion=self.config.fusion,
                rerank=self.config.rerank,
            )
        if normalized == "hybrid_reranker":
            return RetrievalPlan(
                name="hybrid_reranker",
                retrievers=(MILVUS_RETRIEVER, "bm25"),
                fusion=self.config.fusion,
                rerank=True,
            )
        if normalized == "keyword":
            normalized = _normalize_retriever_name(self.config.keyword_adapter)
        if normalized in {"agentic_router", "full_rag"}:
            return RetrievalPlan(name=normalized, retrievers=(normalized,), fusion=self.config.fusion, rerank=False)
        return RetrievalPlan(name=normalized, retrievers=(normalized,), fusion=self.config.fusion, rerank=self.config.rerank)

    def _plan_uses_milvus(self, plan: RetrievalPlan) -> bool:
        """Whether a retrieval plan needs the BEIR Milvus collection."""

        return MILVUS_RETRIEVER in plan.retrievers

    def _plan_uses_business_rag(self, plan: RetrievalPlan) -> bool:
        """Whether a retrieval plan calls the real business RAG graph."""

        return any(name in {"agentic_router", "full_rag"} for name in plan.retrievers)

    def _rerankless_top_hits(self, hits: list[SearchHit], top_k: int) -> list[SearchHit]:
        """Trim and normalize ranks when no reranker is enabled."""

        return [
            SearchHit(
                doc_id=hit.doc_id,
                score=hit.score,
                rank=rank,
                retriever=hit.retriever,
                metadata=hit.metadata,
                title=hit.title,
                text=hit.text,
            )
            for rank, hit in enumerate(hits[:top_k], start=1)
        ]

    def _build_query_trace(
        self,
        query_id: str,
        query_text: str,
        final_hits: list[SearchHit],
        raw_groups: dict[str, list[SearchHit]],
        candidates: list[SearchHit],
        before_rerank_hits: list[SearchHit],
        qrels: BeirQrels,
        plan: RetrievalPlan,
        latency_ms: dict[str, int],
        error: str,
        rerank_input_samples: list[dict[str, Any]] | None = None,
        reranker_info: dict[str, Any] | None = None,
        business_trace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a rich per-query trace for logs and reports."""

        expected_doc_ids = sorted(doc_id for doc_id, relevance in qrels.get(query_id, {}).items() if relevance > 0)
        expected = set(expected_doc_ids)
        retrieved_doc_ids = [hit.doc_id for hit in final_hits]
        before_rerank_doc_ids = [hit.doc_id for hit in before_rerank_hits]
        raw_candidate_doc_ids = [hit.doc_id for hit in candidates]
        eval_top_k = self.config.effective_eval_top_k
        answer_top_k = self.config.effective_answer_top_k
        eval_doc_ids = retrieved_doc_ids[:eval_top_k]
        answer_context_doc_ids = retrieved_doc_ids[:answer_top_k]
        business_raw = (business_trace or {}).get("raw") or {}
        before_judge_doc_ids = list(business_raw.get("rerank_after_doc_ids") or retrieved_doc_ids)
        after_judge_doc_ids = list(business_raw.get("evidence_after_judge_doc_ids") or retrieved_doc_ids)
        trace_before_rerank_doc_ids = list(business_raw.get("retrieval_before_rerank_doc_ids") or raw_candidate_doc_ids)
        trace_before_rerank_scores = list(
            business_raw.get("retrieval_before_rerank_scores") or [hit.score for hit in candidates[: self.config.rerank_top_k]]
        )
        trace_after_rerank_doc_ids = list(business_raw.get("rerank_after_doc_ids") or retrieved_doc_ids)
        trace_after_rerank_scores = list(
            business_raw.get("rerank_after_scores") or [hit.score for hit in final_hits[: self.config.rerank_top_k]]
        )
        real_rerank_enabled = bool(plan.rerank or business_raw.get("rerank_after_doc_ids") or business_raw.get("reranker_runtime"))
        business_reranker_runtime = business_raw.get("reranker_runtime") or {}
        hit_qrels = [doc_id for doc_id in retrieved_doc_ids if doc_id in expected]
        first_hit_rank = _first_hit_rank(retrieved_doc_ids, expected)
        raw_first_hit_rank = _first_hit_rank(raw_candidate_doc_ids, expected)
        before_rerank_first_hit_rank = _first_hit_rank(before_rerank_doc_ids, expected)
        rankings = [
            {
                "rank": rank,
                "doc_id": hit.doc_id,
                "score": hit.score,
                "source": hit.retriever,
                "qrels_hit": hit.doc_id in expected,
                "metadata": hit.metadata,
            }
            for rank, hit in enumerate(final_hits, start=1)
        ]
        return {
            "query_id": query_id,
            "query_text": query_text,
            "candidate_k": self.config.candidate_k,
            "rerank_top_k": self.config.rerank_top_k,
            "eval_top_k": eval_top_k,
            "answer_top_k": answer_top_k,
            "expected_doc_ids": expected_doc_ids,
            "qrels_doc_ids": expected_doc_ids,
            "retrieved_doc_ids": retrieved_doc_ids,
            "eval_doc_ids_top100": eval_doc_ids[:100],
            "final_answer_doc_ids_top10": answer_context_doc_ids[:10],
            "answer_context_doc_ids": answer_context_doc_ids,
            "answer_context_count": len(answer_context_doc_ids),
            "eval_result_count": len(eval_doc_ids),
            "hit_at": {str(k): bool(set(retrieved_doc_ids[:k]) & expected) for k in REPORT_HIT_KS},
            "first_hit_rank": first_hit_rank,
            "raw_first_hit_rank": raw_first_hit_rank,
            "rerank_before_first_hit_rank": before_rerank_first_hit_rank,
            "retrieval_before_rerank_doc_ids": trace_before_rerank_doc_ids[: self.config.rerank_top_k],
            "retrieval_before_rerank_scores": trace_before_rerank_scores[: self.config.rerank_top_k],
            "rerank_after_doc_ids": trace_after_rerank_doc_ids[: self.config.rerank_top_k] if plan.rerank else [],
            "rerank_after_scores": trace_after_rerank_scores[: self.config.rerank_top_k] if plan.rerank else [],
            "evidence_after_judge_doc_ids": after_judge_doc_ids[:eval_top_k],
            "before_rerank_hit_at_10": bool(set(trace_before_rerank_doc_ids[:10]) & expected),
            "after_rerank_hit_at_10": bool(set(retrieved_doc_ids[:10]) & expected) if plan.rerank else bool(set(raw_candidate_doc_ids[:10]) & expected),
            "before_judge_hit_at_10": bool(set(before_judge_doc_ids[:10]) & expected),
            "after_judge_hit_at_10": bool(set(after_judge_doc_ids[:10]) & expected),
            "dropped_qrels_by_judge": sorted((set(before_judge_doc_ids) & expected) - (set(after_judge_doc_ids) & expected)),
            "hit_qrels": hit_qrels,
            "qrels_hit": bool(hit_qrels),
            "retriever_route": ",".join(plan.retrievers),
            "fusion_method": plan.fusion if len(plan.retrievers) > 1 else "",
            "rerank_enabled": real_rerank_enabled,
            "reranker_model_name": (reranker_info or {}).get("model_name", "") or business_reranker_runtime.get("model_name", ""),
            "reranker_model_provider": (reranker_info or {}).get("model_provider", "") or business_reranker_runtime.get("provider", ""),
            "reranker_model_configured": bool((reranker_info or {}).get("model_configured", False) or business_reranker_runtime),
            "reranker_model_loaded": bool((reranker_info or {}).get("model_loaded", False) or business_reranker_runtime.get("model_loaded", False)),
            "reranker_score_order": (reranker_info or {}).get("score_order", "") or business_reranker_runtime.get("score_order", ""),
            "rerank_input_samples": rerank_input_samples or [],
            "latency_ms": latency_ms,
            "adapter_type": (business_trace or {}).get("adapter", plan.name),
            "business_route": (business_trace or {}).get("route", ""),
            "planner_result": (business_trace or {}).get("planner_result", {}),
            "retriever_used": (business_trace or {}).get("retriever_used", []),
            "business_trace": business_trace or {},
            "rankings": rankings,
            "raw_hits": {name: [hit.to_dict() for hit in hits[:100]] for name, hits in raw_groups.items()},
            "fused_hits": [hit.to_dict() for hit in candidates[:100]] if len(raw_groups) > 1 else [],
            "rerank_before_hits": [hit.to_dict() for hit in before_rerank_hits[:100]] if plan.rerank else [],
            "final_hits": [hit.to_dict() for hit in final_hits[:100]],
            "error": error,
        }

    def _evaluate_metrics(self, qrels: BeirQrels, results: dict[str, dict[str, float]]) -> dict[str, Any]:
        """Run BEIR EvaluateRetrieval with configured K values."""

        if not qrels:
            return {"NDCG": {}, "MAP": {}, "Recall": {}, "Precision": {}, "MRR": {}, "flat": {}}
        return evaluate_beir_results(qrels, results, list(self.config.k_values))

    def _build_rerank_summary(
        self,
        plan: RetrievalPlan,
        qrels: BeirQrels,
        query_hits_before_rerank: dict[str, list[SearchHit]],
        metrics_after: dict[str, Any],
        traces: list[dict[str, Any]],
        reranker_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Compare retrieval quality before and after reranking."""

        if not plan.rerank:
            return {"enabled": False}
        before_results = hits_to_beir_results(query_hits_before_rerank)
        before_metrics = self._evaluate_metrics(qrels, before_results)
        before_hit_summary = self._hit_summary_from_hits(query_hits_before_rerank, qrels)
        after_hit_summary = self._hit_summary(traces)
        before_flat = before_metrics.get("flat", {})
        after_flat = metrics_after.get("flat", {})
        before_ndcg = float(before_flat.get("NDCG@10", 0.0))
        after_ndcg = float(after_flat.get("NDCG@10", 0.0))
        before_mrr = float(before_flat.get("MRR@10", 0.0))
        after_mrr = float(after_flat.get("MRR@10", 0.0))
        degraded = _drops_more_than_five_percent(before_ndcg, after_ndcg) or _drops_more_than_five_percent(before_mrr, after_mrr)
        return {
            "enabled": True,
            "status": "RERANK_DEGRADED" if degraded else "ok",
            "degraded": degraded,
            "reranker": reranker_info,
            "before": {
                "NDCG@10": before_ndcg,
                "MRR@10": before_mrr,
                "Recall@100": float(before_flat.get("Recall@100", 0.0)),
                "hit_at_10_count": int(before_hit_summary.get("hit_at_10", {}).get("hit_queries", 0)),
            },
            "after": {
                "NDCG@10": after_ndcg,
                "MRR@10": after_mrr,
                "Recall@100": float(after_flat.get("Recall@100", 0.0)),
                "hit_at_10_count": int(after_hit_summary.get("hit_at_10", {}).get("hit_queries", 0)),
            },
        }

    def _aggregate_latency(
        self,
        base_latency: dict[str, float],
        traces: list[dict[str, Any]],
        evaluation_ms: int,
        total_started_at: float,
    ) -> dict[str, float]:
        """Aggregate run-level latency fields."""

        query_count = len(traces)
        query_embedding_total_ms = sum(trace.get("latency_ms", {}).get("embedding_ms", 0) for trace in traces)
        retrieval_total_ms = sum(trace.get("latency_ms", {}).get("retrieval_ms", 0) for trace in traces)
        fusion_total_ms = sum(trace.get("latency_ms", {}).get("fusion_ms", 0) for trace in traces)
        rerank_total_ms = sum(trace.get("latency_ms", {}).get("rerank_ms", 0) for trace in traces)
        planner_total_ms = sum(trace.get("latency_ms", {}).get("planner_ms", 0) for trace in traces)
        query_total_ms = sum(trace.get("latency_ms", {}).get("total_ms", 0) for trace in traces)
        latency = {
            **base_latency,
            "query_total_ms": float(query_total_ms),
            "avg_total_ms": query_total_ms / max(query_count, 1),
            "query_embedding_total_ms": float(query_embedding_total_ms),
            "query_embedding_avg_ms": query_embedding_total_ms / max(query_count, 1),
            "retrieval_total_ms": float(retrieval_total_ms),
            "retrieval_avg_ms": retrieval_total_ms / max(query_count, 1),
            "fusion_total_ms": float(fusion_total_ms),
            "fusion_avg_ms": fusion_total_ms / max(query_count, 1),
            "rerank_total_ms": float(rerank_total_ms),
            "rerank_avg_ms": rerank_total_ms / max(query_count, 1),
            "planner_total_ms": float(planner_total_ms),
            "planner_avg_ms": planner_total_ms / max(query_count, 1),
            "evaluation_ms": float(evaluation_ms),
            "total_ms": float(int((time.perf_counter() - total_started_at) * 1000)),
        }
        for key in (
            "intent_ms",
            "query_decompose_ms",
            "planner_ms",
            "retrieval_ms",
            "rerank_ms",
            "evidence_judge_ms",
            "lightweight_filter_ms",
            "llm_evidence_judge_ms",
            "answer_ms",
        ):
            total = sum(int(trace.get("latency_ms", {}).get(key, 0) or 0) for trace in traces)
            latency[f"{key.replace('_ms', '')}_avg_ms"] = total / max(query_count, 1)
        return latency

    def _hit_summary(self, traces: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
        """Summarize hit-at-K counts."""

        total = len(traces)
        summary: dict[str, dict[str, float]] = {}
        for k in REPORT_HIT_KS:
            hit_queries = sum(1 for trace in traces if trace.get("hit_at", {}).get(str(k), False))
            summary[f"hit_at_{k}"] = {"hit_queries": hit_queries, "total_queries": total, "hit_rate": hit_queries / max(total, 1)}
        return summary

    def _hit_summary_from_hits(self, query_hits: dict[str, list[SearchHit]], qrels: BeirQrels) -> dict[str, dict[str, float]]:
        """Summarize hit-at-K counts from raw hit lists."""

        total = len(query_hits)
        summary: dict[str, dict[str, float]] = {}
        for k in REPORT_HIT_KS:
            hit_queries = 0
            for query_id, hits in query_hits.items():
                expected = {doc_id for doc_id, relevance in qrels.get(query_id, {}).items() if relevance > 0}
                retrieved = [hit.doc_id for hit in hits[:k]]
                if set(retrieved) & expected:
                    hit_queries += 1
            summary[f"hit_at_{k}"] = {"hit_queries": hit_queries, "total_queries": total, "hit_rate": hit_queries / max(total, 1)}
        return summary

    def _business_summary(self, context: AdapterContext, plan: RetrievalPlan) -> dict[str, Any]:
        """Summarize real business RAG adapter behavior."""

        counts = context.extra.get("business_mapping_counts") or {}
        total = int(counts.get("total", 0) or 0)
        mapped = int(counts.get("mapped", 0) or 0)
        unmapped = int(counts.get("unmapped", 0) or 0)
        uses_business = self._plan_uses_business_rag(plan)
        return {
            "adapter_type": plan.name,
            "uses_business_rag": uses_business,
            "business_project_code": self.config.business_project_code,
            "business_user_id": self.config.business_user_id,
            "business_index_targets": list(self.config.business_index_targets),
            "real_permission_filtering": uses_business,
            "include_answer_requested": self.config.include_answer if "full_rag" in plan.retrievers else False,
            "online_answer_enabled": self.config.enable_online_answer if "full_rag" in plan.retrievers else False,
            "include_answer": bool(self.config.include_answer and self.config.enable_online_answer) if "full_rag" in plan.retrievers else False,
            "candidate_k": self.config.candidate_k,
            "rerank_top_k": self.config.rerank_top_k,
            "eval_top_k": self.config.effective_eval_top_k,
            "answer_top_k": self.config.effective_answer_top_k,
            "retrieval_mode": self.config.retrieval_mode,
            "mapped_evidence_count": mapped,
            "unmapped_evidence_count": unmapped,
            "total_evidence_count": total,
            "evidence_mapping_hit_rate": mapped / max(total, 1) if total else 0.0,
            "unmapped_evidence_path": "unmapped_evidence.jsonl" if unmapped else "",
            "answer_details_path": "answer_details.jsonl" if context.extra.get("answer_details") else "",
        }

    def _config_payload(
        self,
        corpus: BeirCorpus,
        queries: BeirQueries,
        qrels: BeirQrels,
        query_ids: list[str],
        dataset_path: Path,
        plan: RetrievalPlan | None,
        index_plan: IndexPlan | None,
    ) -> dict[str, Any]:
        """Serialize run configuration for reports."""

        return {
            "dataset": self.config.dataset,
            "split": self.config.split,
            "mode": self.config.mode,
            "retriever": plan.name if plan else self.config.retriever,
            "retrievers": list(plan.retrievers) if plan else [],
            "fusion": self.config.fusion,
            "weights": self.config.weights,
            "rerank": plan.rerank if plan else self.config.rerank,
            "reranker_score_order": self.config.reranker_score_order,
            "include_answer": self.config.include_answer,
            "enable_online_answer": self.config.enable_online_answer,
            "business_project_code": self.config.business_project_code,
            "business_user_id": self.config.business_user_id,
            "business_index_targets": list(self.config.business_index_targets),
            "eval_mode": self.config.eval_mode,
            "force_business_reindex": self.config.force_business_reindex,
            "top_k": self.config.top_k,
            "candidate_k": self.config.candidate_k,
            "rerank_top_k": self.config.rerank_top_k,
            "eval_top_k": self.config.effective_eval_top_k,
            "answer_top_k": self.config.effective_answer_top_k,
            "final_top_k": self.config.final_top_k,
            "retrieval_mode": self.config.retrieval_mode,
            "require_real_reranker": self.config.require_real_reranker,
            "allow_reranker_fallback": self.config.allow_reranker_fallback,
            "collection_name": self.config.collection_name,
            "data_dir": str(self.config.data_dir),
            "dataset_path": str(dataset_path),
            "output_dir": str(self.config.effective_output_dir),
            "k_values": list(self.config.k_values),
            "query_count": len(query_ids),
            "corpus_count": len(corpus),
            "total_queries_in_dataset": len(queries),
            "qrels_count": sum(len(items) for items in qrels.values()),
            "embedding_batch_size": self.config.corpus_batch_size,
            "query_batch_size": self.config.query_batch_size,
            "force_reindex": self.config.force_reindex,
            "skip_index": self.config.skip_index,
            "index_plan": self._index_plan_payload(index_plan),
        }

    def _empty_payload(
        self,
        corpus: BeirCorpus,
        queries: BeirQueries,
        qrels: BeirQrels,
        query_ids: list[str],
        dataset_path: Path,
        latency: dict[str, float],
        index_plan: IndexPlan | None,
    ) -> dict[str, Any]:
        """Build a report payload for info/index-only modes."""

        return {
            "config": self._config_payload(corpus, queries, qrels, query_ids, dataset_path, plan=None, index_plan=index_plan),
            "metrics": {"NDCG": {}, "MAP": {}, "Recall": {}, "Precision": {}, "MRR": {}, "flat": {}},
            "results": {},
            "query_traces": [],
            "hit_summary": self._hit_summary([]),
            "latency": latency,
            "warnings": self._warnings(),
            "errors": [],
        }

    def _run_check_reranker(self, total_started_at: float) -> dict[str, Any]:
        """Validate and warm up the real local reranker without loading a BEIR dataset."""

        from app.core.database import SessionLocal, init_database
        from app.services.reranker_service import RerankerService

        logger.info("stage=rerank status=started action=check_reranker require_real_reranker=%s", self.config.require_real_reranker)
        db = None
        try:
            init_database()
            db = SessionLocal()
            service = RerankerService(db)
            runtime_config = service.ensure_real_model()
            started_at = time.perf_counter()
            service.warmup_local_reranker()
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            runtime = service.last_runtime or {}
            result = {
                "status": "ok",
                "provider": getattr(runtime_config, "provider", ""),
                "model_name": runtime.get("model_name") or getattr(runtime_config, "model_name", ""),
                "api_base": getattr(runtime_config, "api_base", ""),
                "model_loaded": True,
                "device": runtime.get("device", ""),
                "backend": runtime.get("backend", ""),
                "elapsed_ms": elapsed_ms,
            }
            logger.info(
                "stage=rerank status=completed action=check_reranker provider=%s model=%s device=%s elapsed_ms=%s",
                result["provider"],
                result["model_name"],
                result["device"],
                elapsed_ms,
            )
            return {
                "config": self._config_payload({}, {}, {}, [], Path(), plan=None, index_plan=None),
                "metrics": {"NDCG": {}, "MAP": {}, "Recall": {}, "Precision": {}, "MRR": {}, "flat": {}},
                "results": {},
                "query_traces": [],
                "hit_summary": self._hit_summary([]),
                "latency": {"reranker_warmup_ms": elapsed_ms, "total_ms": int((time.perf_counter() - total_started_at) * 1000)},
                "warnings": self._warnings(),
                "errors": [],
                "reranker_check": result,
            }
        except Exception as exc:
            logger.exception("stage=rerank status=failed action=check_reranker error=%s", exc)
            raise
        finally:
            if db is not None:
                db.close()

    def _warnings(self) -> list[str]:
        """Build run warnings for report.md."""

        warnings: list[str] = []
        if self.config.top_k < max(self.config.k_values):
            warnings.append(
                f"top_k={self.config.top_k} is smaller than max(k_values)={max(self.config.k_values)}; "
                "metrics above top_k are computed from truncated results and may be equivalent to the largest available rank."
            )
        if self.config.effective_eval_top_k < max(self.config.k_values):
            warnings.append(
                f"eval_top_k={self.config.effective_eval_top_k} is smaller than max(k_values)={max(self.config.k_values)}; "
                "metrics above eval_top_k are invalid because retrieval results are truncated."
            )
        if self.config.effective_answer_top_k != 10:
            warnings.append(
                f"answer_top_k={self.config.effective_answer_top_k} is not 10; current real answer generation chain is fixed to Top10."
            )
        return warnings

    def _index_plan_payload(self, index_plan: IndexPlan | None) -> dict[str, Any] | None:
        """Serialize index plan into reports."""

        if index_plan is None:
            return None
        return {
            "should_index": index_plan.should_index,
            "reason": index_plan.reason,
            "collection_exists": index_plan.collection_exists,
            "existing_count": index_plan.existing_count,
        }

    def _configure_embedding_device(self, settings: Any) -> None:
        """Prefer CUDA for local embedding and warn when only CPU is available."""

        provider = str(getattr(settings, "embedding_provider", "") or "").lower()
        if provider not in LOCAL_EMBEDDING_PROVIDERS:
            logger.info("stage=corpus_indexing action=embedding_device provider=%s mode=remote_or_external", provider)
            return
        try:
            import torch
        except ImportError:
            logger.warning("stage=corpus_indexing action=embedding_device cuda_available=unknown selected_device=%s", settings.embedding_device)
            return

        current_device = str(getattr(settings, "embedding_device", "cpu") or "cpu")
        if torch.cuda.is_available():
            if not current_device.lower().startswith("cuda"):
                previous_device = current_device
                settings.embedding_device = "cuda"
                logger.info(
                    "stage=corpus_indexing action=embedding_device cuda_available=true previous_device=%s selected_device=%s",
                    previous_device,
                    settings.embedding_device,
                )
            else:
                logger.info("stage=corpus_indexing action=embedding_device cuda_available=true selected_device=%s", current_device)
            return
        if current_device.lower().startswith("cuda"):
            previous_device = current_device
            settings.embedding_device = "cpu"
            current_device = settings.embedding_device
            logger.warning(
                "stage=corpus_indexing action=embedding_device cuda_available=false previous_device=%s selected_device=%s message=CUDA is unavailable; CPU embedding will be slow for corpus/query embedding",
                previous_device,
                current_device,
            )
            return
        logger.warning(
            "stage=corpus_indexing action=embedding_device cuda_available=false selected_device=%s message=CPU embedding will be slow for corpus/query embedding",
            current_device,
        )

    def _configure_ripgrep_binary(self, settings: Any) -> None:
        """Resolve ripgrep to an absolute executable path for subprocess calls."""

        current = str(getattr(settings, "ripgrep_binary", "") or "rg")
        resolved = shutil.which(current)
        if resolved:
            if resolved != current:
                settings.ripgrep_binary = resolved
                logger.info(
                    "stage=dataset_loading action=ripgrep_binary status=resolved configured=%s resolved=%s",
                    current,
                    resolved,
                )
            else:
                logger.info("stage=dataset_loading action=ripgrep_binary status=available binary=%s", current)
            return

        path = Path(current)
        if path.exists():
            logger.info("stage=dataset_loading action=ripgrep_binary status=available binary=%s", current)
            return
        logger.warning(
            "stage=dataset_loading action=ripgrep_binary status=unavailable configured=%s message=ripgrep retriever will return no hits until RIPGREP_BINARY points to rg.exe",
            current,
        )


def _normalize_retriever_name(name: str) -> str:
    """Normalize CLI aliases."""

    return name.strip().lower().replace("-", "_")


def _first_hit_rank(doc_ids: list[str], expected: set[str]) -> int | None:
    """Return first relevant rank, or None when missed."""

    for rank, doc_id in enumerate(doc_ids, start=1):
        if doc_id in expected:
            return rank
    return None


def _drops_more_than_five_percent(before: float, after: float) -> bool:
    """Whether a metric dropped by more than 5% relative to the rerank-before value."""

    if before <= 0:
        return False
    return after < before * 0.95


def _unique_preserve_order(values: list[str]) -> list[str]:
    """Deduplicate warnings while preserving first occurrence order."""

    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique
