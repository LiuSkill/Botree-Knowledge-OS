"""Explicit placeholders for project retrievers that are not BEIR-ready yet."""

from __future__ import annotations

from eval.beir.adapters.base import AdapterContext, UnsupportedRetrieverError
from eval.beir.types import SearchHit


class UnsupportedProjectRetrieverAdapter:
    """Adapter that fails loudly for retrievers without BEIR doc_id mapping."""

    def __init__(self, name: str) -> None:
        self.name = name

    def prepare(self, context: AdapterContext) -> None:
        del context
        raise UnsupportedRetrieverError(
            f"Retriever '{self.name}' has no BEIR adapter yet. "
            "Current online PageIndex/GraphRAG/agentic/full_rag flows depend on project documents, "
            "permissions, chunk IDs and graph metadata that are not populated by the BEIR Milvus eval collection. "
            "Ingest BEIR corpus into the corresponding business index with a stable BEIR doc_id mapping before enabling it."
        )

    def search(self, query_id: str, query: str, top_k: int) -> list[SearchHit]:
        del query_id, query, top_k
        raise UnsupportedRetrieverError(f"Retriever '{self.name}' has no BEIR adapter yet.")

    def query_embedding_latency_ms(self, query_id: str) -> int:
        del query_id
        return 0
