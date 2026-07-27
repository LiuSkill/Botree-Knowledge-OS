import pytest

from app.core.exceptions import AppException
from app.services.knowledge_base_rebuild_service import KnowledgeBaseRebuildService, RebuildSourceSnapshot


def test_rebuild_rejects_source_snapshot_drift() -> None:
    before = RebuildSourceSnapshot("abc", (1, 2))
    after = RebuildSourceSnapshot("changed", (1, 2))

    with pytest.raises(AppException, match="源快照发生变化"):
        KnowledgeBaseRebuildService.ensure_unchanged(before, after)
