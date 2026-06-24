"""Base adapter contract for BEIR retrieval evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from eval.beir.types import BeirCorpus, BeirQrels, BeirQueries, SearchHit


class UnsupportedRetrieverError(RuntimeError):
    """Raised when a named project retriever cannot be evaluated on BEIR yet."""


@dataclass
class AdapterContext:
    """Shared runtime context passed to retrieval adapters."""

    dataset: str
    split: str
    corpus: BeirCorpus
    queries: BeirQueries
    qrels: BeirQrels
    query_ids: list[str]
    config: Any
    settings: Any
    embedding_service: Any | None = None
    milvus_store: Any | None = None
    db: Any | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class RetrievalAdapter(Protocol):
    """Unified BEIR retrieval adapter interface."""

    name: str

    def prepare(self, context: AdapterContext) -> None:
        """Prepare indexes, caches or external handles before query evaluation."""

    def search(self, query_id: str, query: str, top_k: int) -> list[SearchHit]:
        """Return TopK hits using original BEIR doc_ids."""

    def query_embedding_latency_ms(self, query_id: str) -> int:
        """Return cached query embedding latency contribution for reports."""

        return 0
