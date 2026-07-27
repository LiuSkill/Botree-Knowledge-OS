from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.document import Document
from app.services.verified_retrieval_scope_service import VerifiedRetrievalScopeService


def test_verified_scope_only_contains_current_published_documents() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                Document(id=1, knowledge_base_id=2, knowledge_type="project", project_id=5, file_name="ok.pdf", file_type="pdf", storage_path="ok", review_status="approved", index_status="indexed", version_no=1, is_current_version=True, security_level="public"),
                Document(id=2, knowledge_base_id=2, knowledge_type="project", project_id=5, file_name="draft.pdf", file_type="pdf", storage_path="draft", review_status="draft", index_status="not_indexed", version_no=1, is_current_version=True, security_level="public"),
            ]
        )
        db.commit()
        service = VerifiedRetrievalScopeService(db, ttl_seconds=30)
        snapshot = service.create("project_only", 5, SimpleNamespace(id=8, roles=[]))

    assert snapshot["document_ids"] == [1]
    assert snapshot["verified"] is True
    assert snapshot["expires_at"] > snapshot["verified_at"]


def test_governance_invalidation_forces_new_snapshot() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    service = VerifiedRetrievalScopeService(db, ttl_seconds=30)
    user = SimpleNamespace(id=9, roles=[])

    first = service.create("base_only", None, user)
    service.invalidate(user_id=9)
    second = service.create("base_only", None, user)

    assert first["snapshot_id"] != second["snapshot_id"]
    db.close()
