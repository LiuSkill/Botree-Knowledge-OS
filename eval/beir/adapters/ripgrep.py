"""ripgrep keyword adapter for BEIR evaluation."""

from __future__ import annotations

from eval.beir.adapters.base import AdapterContext
from eval.beir.keyword import RipgrepKeywordAdapter
from eval.beir.types import SearchHit


class RipgrepRetrieverAdapter:
    """ripgrep-backed exact keyword retriever."""

    name = "ripgrep"

    def __init__(self) -> None:
        self.adapter: RipgrepKeywordAdapter | None = None

    def prepare(self, context: AdapterContext) -> None:
        ripgrep_binary = getattr(context.settings, "ripgrep_binary", "rg")
        index_dir = context.config.data_dir / "_keyword_index" / context.dataset / self.name
        self.adapter = RipgrepKeywordAdapter(index_dir=index_dir, ripgrep_binary=ripgrep_binary)
        self.adapter.index(context.corpus)

    def search(self, query_id: str, query: str, top_k: int) -> list[SearchHit]:
        del query_id
        if self.adapter is None:
            raise RuntimeError("ripgrep adapter is not prepared")
        return self.adapter.search(query, top_k)

    def query_embedding_latency_ms(self, query_id: str) -> int:
        del query_id
        return 0
