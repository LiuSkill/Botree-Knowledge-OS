from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import AppException
from app.models import Base, Document, KnowledgeBase
from app.models.page_index import IndexPublicationManifest
from app.repositories.index_publication_repository import IndexPublicationRepository
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


def test_resume_selects_only_documents_not_published_for_current_generation() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        db.add(KnowledgeBase(id=1, name="Base KB", code="base-kb", type="base"))
        documents = [
            Document(
                knowledge_base_id=1,
                knowledge_type="base",
                file_name=f"doc-{index}.pdf",
                file_type="pdf",
                file_size=1,
                storage_path=f"/tmp/doc-{index}.pdf",
                document_name=f"doc-{index}.pdf",
                version_no=1,
                current_version=True,
                is_current_version=True,
            )
            for index in range(2)
        ]
        db.add_all(documents)
        db.flush()
        db.add(
            IndexPublicationManifest(
                knowledge_base_id=1,
                document_id=documents[0].id,
                version_no=1,
                index_generation="vl-current",
                publication_token="published-token",
                status="published",
                coverage=1.0,
                partial_coverage=False,
                required_json="{}",
                completed_json="{}",
                missing_json="{}",
            )
        )
        db.commit()

        published = IndexPublicationRepository(db).published_document_ids(
            [(document.id, document.version_no) for document in documents],
            index_generation="vl-current",
        )

        assert published == {documents[0].id}
