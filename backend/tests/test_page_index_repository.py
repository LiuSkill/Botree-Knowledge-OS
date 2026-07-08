from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models import Base, Document, DocumentChunk, DocumentPage, KnowledgeBase, PageIndex  # noqa: E402
from app.repositories.page_index_repository import PageIndexRepository  # noqa: E402


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_factory()


def test_searchable_page_index_rows_do_not_require_document_indexed_status() -> None:
    db = make_session()
    try:
        db.add(KnowledgeBase(id=1, name="Base KB", code="base-kb", type="base"))
        db.flush()

        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="Na2SO4 Process Flow Diagram.pdf",
            file_type="pdf",
            file_size=128,
            storage_path="/tmp/na2so4-pfd.pdf",
            document_name="Na2SO4 Process Flow Diagram.pdf",
            review_status="approved",
            index_status="not_indexed",
            version_no=1,
            current_version=True,
            is_current_version=True,
            security_level="public",
        )
        db.add(document)
        db.flush()

        chunk = DocumentChunk(
            knowledge_base_id=1,
            document_id=document.id,
            knowledge_type="base",
            version_no=1,
            chunk_status="active",
            chunk_index=0,
            content="Na2SO4 evaporation flow is described on this page.",
            page_number=1,
            security_level="public",
        )
        db.add(chunk)
        db.flush()

        page = DocumentPage(
            knowledge_base_id=1,
            document_id=document.id,
            version_no=1,
            page_no=1,
            page_text="Na2SO4 evaporation flow page text",
            security_level="public",
        )
        db.add(page)
        db.flush()

        page_index = PageIndex(
            knowledge_base_id=1,
            document_id=document.id,
            page_id=page.id,
            chunk_id=chunk.id,
            version_no=1,
            page_no=1,
            index_text="Na2SO4 evaporation flow diagram",
            status="published",
            security_level="public",
        )
        db.add(page_index)
        db.commit()

        rows = PageIndexRepository(db).list_searchable_index_rows(
            ["public"],
            knowledge_type="base",
            query_terms=["Na2SO4", "flow"],
        )

        assert len(rows) == 1
        matched_page_index, matched_document, matched_chunk = rows[0]
        assert matched_page_index.id == page_index.id
        assert matched_document.id == document.id
        assert matched_document.index_status == "not_indexed"
        assert matched_chunk.id == chunk.id
    finally:
        db.close()


def test_publish_document_indexes_updates_only_target_document() -> None:
    db = make_session()
    try:
        db.add(KnowledgeBase(id=1, name="Base KB", code="base-kb", type="base"))
        db.flush()

        target_document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="target.pdf",
            file_type="pdf",
            file_size=128,
            storage_path="/tmp/target.pdf",
            document_name="target.pdf",
            review_status="approved",
            index_status="building",
            version_no=1,
            current_version=True,
            is_current_version=True,
            security_level="public",
        )
        other_document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="other.pdf",
            file_type="pdf",
            file_size=128,
            storage_path="/tmp/other.pdf",
            document_name="other.pdf",
            review_status="approved",
            index_status="indexed",
            version_no=1,
            current_version=True,
            is_current_version=True,
            security_level="public",
        )
        db.add_all([target_document, other_document])
        db.flush()

        old_page = DocumentPage(
            knowledge_base_id=1,
            document_id=target_document.id,
            version_no=0,
            page_no=1,
            page_text="old page",
            security_level="public",
        )
        current_page_1 = DocumentPage(
            knowledge_base_id=1,
            document_id=target_document.id,
            version_no=1,
            page_no=1,
            page_text="current page 1",
            security_level="public",
        )
        current_page_2 = DocumentPage(
            knowledge_base_id=1,
            document_id=target_document.id,
            version_no=1,
            page_no=2,
            page_text="current page 2",
            security_level="public",
        )
        other_page = DocumentPage(
            knowledge_base_id=1,
            document_id=other_document.id,
            version_no=1,
            page_no=1,
            page_text="other page",
            security_level="public",
        )
        db.add_all([old_page, current_page_1, current_page_2, other_page])
        db.flush()

        old_index = PageIndex(
            knowledge_base_id=1,
            document_id=target_document.id,
            page_id=old_page.id,
            version_no=0,
            page_no=1,
            index_text="old published text",
            status="published",
            security_level="public",
        )
        current_index_1 = PageIndex(
            knowledge_base_id=1,
            document_id=target_document.id,
            page_id=current_page_1.id,
            version_no=1,
            page_no=1,
            index_text="new staging text 1",
            status="staging",
            security_level="public",
        )
        current_index_2 = PageIndex(
            knowledge_base_id=1,
            document_id=target_document.id,
            page_id=current_page_2.id,
            version_no=1,
            page_no=2,
            index_text="new staging text 2",
            status="staging",
            security_level="public",
        )
        other_index = PageIndex(
            knowledge_base_id=1,
            document_id=other_document.id,
            page_id=other_page.id,
            version_no=1,
            page_no=1,
            index_text="other published text",
            status="published",
            security_level="public",
        )
        db.add_all([old_index, current_index_1, current_index_2, other_index])
        db.commit()

        published_count = PageIndexRepository(db).publish_document_indexes(target_document.id, 1)
        db.commit()

        assert published_count == 2
        assert db.get(PageIndex, old_index.id).status == "obsolete"
        assert db.get(PageIndex, current_index_1.id).status == "published"
        assert db.get(PageIndex, current_index_2.id).status == "published"
        assert db.get(PageIndex, other_index.id).status == "published"
    finally:
        db.close()
