"""PageIndex BEIR adapter placeholder."""

from eval.beir.adapters.unsupported import UnsupportedProjectRetrieverAdapter


class PageIndexRetrieverAdapter(UnsupportedProjectRetrieverAdapter):
    """PageIndex needs a BEIR doc_id mapping in the business index before use."""

    def __init__(self) -> None:
        super().__init__("pageindex")
