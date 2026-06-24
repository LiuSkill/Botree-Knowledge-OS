"""BEIR adapter for the real agentic router path."""

from eval.beir.adapters.business_rag import AgenticRouterBusinessAdapter


class AgenticRouterRetrieverAdapter(AgenticRouterBusinessAdapter):
    """Run intent, planner and real retrieval graph without final answer generation."""
