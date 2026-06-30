"""Knowledge base service tests."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models import Base, Document, DocumentChunk, KnowledgeBase, User  # noqa: E402
from app.services.knowledge_base_service import KnowledgeBaseService  # noqa: E402


def make_session() -> Session:
    """创建独立内存数据库，避免测试之间互相影响。"""

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_factory()


def make_user() -> User:
    """创建授权中心摘要所需的测试用户。"""

    return User(id=1, username="auth-user", password_hash="x", real_name="Auth User")


def test_authorization_summary_uses_aggregated_counts() -> None:
    """授权中心摘要应一次性聚合资料和有效分块数量，避免文档越多接口越慢。"""

    db = make_session()
    try:
        base = KnowledgeBase(name="企业知识库", code="base", type="base", enabled=True, created_by=1)
        empty_base = KnowledgeBase(name="空知识库", code="empty", type="base", enabled=True, created_by=1)
        db.add_all([base, empty_base])
        db.flush()

        active_document = Document(
            knowledge_base_id=base.id,
            knowledge_type="base",
            file_name="active.txt",
            file_type="txt",
            file_size=10,
            storage_path="storage/active.txt",
            review_status="approved",
            index_status="indexed",
        )
        deleted_document = Document(
            knowledge_base_id=base.id,
            knowledge_type="base",
            file_name="deleted.txt",
            file_type="txt",
            file_size=10,
            storage_path="storage/deleted.txt",
            review_status="approved",
            index_status="indexed",
            is_deleted=True,
        )
        db.add_all([active_document, deleted_document])
        db.flush()
        db.add_all(
            [
                DocumentChunk(
                    knowledge_base_id=base.id,
                    document_id=active_document.id,
                    knowledge_type="base",
                    chunk_index=0,
                    content="active",
                    chunk_status="active",
                ),
                DocumentChunk(
                    knowledge_base_id=base.id,
                    document_id=active_document.id,
                    knowledge_type="base",
                    chunk_index=1,
                    content="obsolete",
                    chunk_status="obsolete",
                ),
                DocumentChunk(
                    knowledge_base_id=base.id,
                    document_id=deleted_document.id,
                    knowledge_type="base",
                    chunk_index=0,
                    content="deleted",
                    chunk_status="active",
                ),
            ]
        )
        db.commit()

        statement_count = 0

        @event.listens_for(db.bind, "before_cursor_execute")
        def _count_statement(*_args: Any) -> None:
            nonlocal statement_count
            statement_count += 1

        summary = KnowledgeBaseService(db).authorization_summary(make_user())
        rows = {item["code"]: item for item in summary["knowledge_bases"]}

        assert rows["base"]["document_count"] == 1
        assert rows["base"]["chunk_count"] == 1
        assert rows["empty"]["document_count"] == 0
        assert rows["empty"]["chunk_count"] == 0
        assert statement_count == 1
    finally:
        db.close()
