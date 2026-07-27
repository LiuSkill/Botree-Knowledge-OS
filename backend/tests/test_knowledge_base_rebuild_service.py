from types import SimpleNamespace

import pytest

from app.core.exceptions import AppException
from app.repositories.knowledge_base_rebuild_repository import KnowledgeBaseRebuildRepository
from app.services.knowledge_base_rebuild_service import KnowledgeBaseRebuildService, RebuildSourceSnapshot


def test_rebuild_rejects_source_snapshot_drift() -> None:
    before = RebuildSourceSnapshot("abc", (1, 2))
    after = RebuildSourceSnapshot("changed", (1, 2))

    with pytest.raises(AppException, match="源快照发生变化"):
        KnowledgeBaseRebuildService.ensure_unchanged(before, after)


def test_source_snapshot_ignores_rebuild_managed_state() -> None:
    document = SimpleNamespace(
        id=7,
        version_no=2,
        storage_path="documents/7.pdf",
        review_status="approved",
        security_level="internal",
        is_current_version=True,
        index_status="pending",
    )
    page = SimpleNamespace(
        page_no=1,
        source_hash="source-v1",
        correction_status="confirmed",
        corrected_text="正文",
        clean_content="正文",
        index_admission_status="waiting_correction",
    )
    repository = KnowledgeBaseRebuildRepository.__new__(KnowledgeBaseRebuildRepository)
    repository.list_pages = lambda _document: [page]
    before = repository.snapshot_digest([document])

    document.index_status = "indexed"
    page.index_admission_status = "text_indexed"

    assert repository.snapshot_digest([document]) == before
