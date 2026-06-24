"""Shared BEIR evaluation types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


BeirCorpus = dict[str, dict[str, str]]
BeirQueries = dict[str, str]
BeirQrels = dict[str, dict[str, int]]
BeirResults = dict[str, dict[str, float]]


@dataclass
class SearchHit:
    """A single retrieval hit using BEIR original document IDs."""

    doc_id: str
    score: float
    rank: int
    retriever: str
    metadata: dict[str, Any] = field(default_factory=dict)
    title: str = ""
    text: str = ""

    @property
    def source(self) -> str:
        """Compatibility alias used by the unified retrieval adapter contract."""

        return self.retriever

    def to_dict(self) -> dict[str, Any]:
        """Serialize a hit for JSONL/CSV reports."""

        return {
            "doc_id": self.doc_id,
            "score": float(self.score),
            "rank": int(self.rank),
            "source": self.retriever,
            "title": self.title,
            "text": self.text,
            "metadata": self.metadata,
        }


@dataclass
class QueryTrace:
    """Per-query trace persisted to reports and logs."""

    query_id: str
    query: str
    elapsed_ms: int
    top_docs: list[str]
    rankings: list[dict[str, Any]]
    qrels_doc_ids: list[str]
    hit_qrels: list[str]
    retriever: str
    rerank: bool

    @property
    def qrels_hit(self) -> bool:
        """Whether the retrieved TopK contains at least one relevant qrels doc."""

        return bool(self.hit_qrels)
