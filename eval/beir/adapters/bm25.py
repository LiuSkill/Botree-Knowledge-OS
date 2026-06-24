"""BM25 adapter for BEIR evaluation."""

from __future__ import annotations

from eval.beir.adapters.base import AdapterContext
from eval.beir.keyword import BM25KeywordAdapter
from eval.beir.types import SearchHit


class BM25RetrieverAdapter:
    """In-memory BM25 retriever using BEIR corpus text."""

    name = "bm25"

    def __init__(self) -> None:
        self.adapter = BM25KeywordAdapter()

    def prepare(self, context: AdapterContext) -> None:
        self.adapter.index(context.corpus)

    def search(self, query_id: str, query: str, top_k: int) -> list[SearchHit]:
        del query_id
        return self.adapter.search(query, top_k)

    def query_embedding_latency_ms(self, query_id: str) -> int:
        del query_id
        return 0
