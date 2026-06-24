"""Factory for BEIR retrieval adapters."""

from __future__ import annotations

from eval.beir.adapters.agentic_router import AgenticRouterRetrieverAdapter
from eval.beir.adapters.base import RetrievalAdapter
from eval.beir.adapters.bm25 import BM25RetrieverAdapter
from eval.beir.adapters.full_rag import FullRAGRetrieverAdapter
from eval.beir.adapters.milvus import MilvusRetrieverAdapter
from eval.beir.adapters.ripgrep import RipgrepRetrieverAdapter
from eval.beir.adapters.unsupported import UnsupportedProjectRetrieverAdapter


SUPPORTED_RETRIEVERS = {"bm25", "keyword", "milvus", "ripgrep", "agentic_router", "full_rag"}
PROJECT_RETRIEVERS = {"pageindex", "graphrag"}


def make_retrieval_adapter(name: str) -> RetrievalAdapter:
    """Create a named BEIR retrieval adapter."""

    normalized = name.lower()
    if normalized in {"bm25", "keyword"}:
        return BM25RetrieverAdapter()
    if normalized == "milvus":
        return MilvusRetrieverAdapter()
    if normalized == "ripgrep":
        return RipgrepRetrieverAdapter()
    if normalized == "agentic_router":
        return AgenticRouterRetrieverAdapter()
    if normalized == "full_rag":
        return FullRAGRetrieverAdapter()
    if normalized in PROJECT_RETRIEVERS:
        return UnsupportedProjectRetrieverAdapter(normalized)
    raise ValueError(f"Unsupported retriever: {name}")
