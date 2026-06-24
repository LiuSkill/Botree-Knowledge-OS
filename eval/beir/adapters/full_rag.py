"""BEIR adapter for the real full RAG graph."""

from eval.beir.adapters.business_rag import FullRAGBusinessAdapter


class FullRAGRetrieverAdapter(FullRAGBusinessAdapter):
    """Run the real retrieval graph and optionally generate final answers."""
