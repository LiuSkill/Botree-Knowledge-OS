"""Public schemas for BEIR evaluation integrations."""

from eval.beir.adapters.base import AdapterContext, RetrievalAdapter, UnsupportedRetrieverError
from eval.beir.types import BeirCorpus, BeirQrels, BeirQueries, BeirResults, QueryTrace, SearchHit

RetrievalHit = SearchHit

__all__ = [
    "AdapterContext",
    "RetrievalAdapter",
    "UnsupportedRetrieverError",
    "BeirCorpus",
    "BeirQrels",
    "BeirQueries",
    "BeirResults",
    "QueryTrace",
    "SearchHit",
    "RetrievalHit",
]
