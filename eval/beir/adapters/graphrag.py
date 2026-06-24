"""GraphRAG BEIR adapter placeholder."""

from eval.beir.adapters.unsupported import UnsupportedProjectRetrieverAdapter


class GraphRAGRetrieverAdapter(UnsupportedProjectRetrieverAdapter):
    """GraphRAG needs BEIR documents in the graph store before use."""

    def __init__(self) -> None:
        super().__init__("graphrag")
