"""Milvus vector retriever adapter for BEIR evaluation."""

from __future__ import annotations

import logging
import time

from eval.beir.adapters.base import AdapterContext
from eval.beir.types import SearchHit

logger = logging.getLogger(__name__)


class MilvusRetrieverAdapter:
    """Milvus TopK retriever using cached query embeddings."""

    name = "milvus"

    def __init__(self) -> None:
        self.context: AdapterContext | None = None
        self.query_vectors: dict[str, list[float]] = {}
        self.query_embedding_ms: dict[str, int] = {}
        self.total_query_embedding_ms = 0

    def prepare(self, context: AdapterContext) -> None:
        if context.embedding_service is None:
            raise RuntimeError("Milvus retrieval requires embedding_service")
        if context.milvus_store is None:
            raise RuntimeError("Milvus retrieval requires milvus_store")

        self.context = context
        context.milvus_store.load_for_search()
        batch_size = int(getattr(context.config, "query_batch_size", 32) or 32)
        logger.info(
            "stage=query_embedding status=started dataset=%s query_count=%s batch_size=%s",
            context.dataset,
            len(context.query_ids),
            batch_size,
        )
        total_started_at = time.perf_counter()
        for start in range(0, len(context.query_ids), batch_size):
            batch_ids = context.query_ids[start : start + batch_size]
            texts = [context.queries[query_id] for query_id in batch_ids]
            batch_started_at = time.perf_counter()
            vectors = context.embedding_service.embed_texts(texts)
            elapsed_ms = int((time.perf_counter() - batch_started_at) * 1000)
            if len(vectors) != len(batch_ids):
                raise ValueError(f"Query embedding count mismatch: expected={len(batch_ids)} actual={len(vectors)}")
            per_query_ms = int(round(elapsed_ms / max(len(batch_ids), 1)))
            for query_id, vector in zip(batch_ids, vectors, strict=False):
                self.query_vectors[query_id] = [float(value) for value in vector]
                self.query_embedding_ms[query_id] = per_query_ms
            logger.info(
                "stage=query_embedding status=batch_completed dataset=%s embedded=%s total=%s elapsed_ms=%s",
                context.dataset,
                min(start + len(batch_ids), len(context.query_ids)),
                len(context.query_ids),
                elapsed_ms,
            )
        self.total_query_embedding_ms = int((time.perf_counter() - total_started_at) * 1000)
        context.extra["query_embedding_total_ms"] = context.extra.get("query_embedding_total_ms", 0) + self.total_query_embedding_ms
        logger.info(
            "stage=query_embedding status=completed dataset=%s query_count=%s total_elapsed_ms=%s avg_ms=%.2f",
            context.dataset,
            len(context.query_ids),
            self.total_query_embedding_ms,
            self.total_query_embedding_ms / max(len(context.query_ids), 1),
        )

    def search(self, query_id: str, query: str, top_k: int) -> list[SearchHit]:
        del query
        if self.context is None or self.context.milvus_store is None:
            raise RuntimeError("Milvus adapter is not prepared")
        query_vector = self.query_vectors.get(query_id)
        if query_vector is None:
            raise RuntimeError(f"Missing cached query embedding: query_id={query_id}")

        started_at = time.perf_counter()
        logger.info(
            "stage=milvus_search status=started query_id=%s top_k=%s collection=%s",
            query_id,
            top_k,
            self.context.config.collection_name,
        )
        hits = self.context.milvus_store.search(self.context.dataset, query_vector, top_k)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "stage=milvus_search status=completed query_id=%s hit_count=%s top_docs=%s elapsed_ms=%s",
            query_id,
            len(hits),
            [hit.doc_id for hit in hits[:10]],
            elapsed_ms,
        )
        return hits

    def query_embedding_latency_ms(self, query_id: str) -> int:
        return self.query_embedding_ms.get(query_id, 0)
