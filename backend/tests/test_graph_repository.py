from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models import Base, Document, GraphEntity, GraphRelation, KnowledgeBase  # noqa: E402
from app.repositories.graph_repository import GraphRepository  # noqa: E402


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_factory()


def test_publish_document_graph_updates_only_target_document() -> None:
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

        old_source = GraphEntity(
            knowledge_base_id=1,
            document_id=target_document.id,
            version_no=0,
            entity_type="equipment",
            entity_name="Old Pump",
            status="published",
        )
        old_target = GraphEntity(
            knowledge_base_id=1,
            document_id=target_document.id,
            version_no=0,
            entity_type="line",
            entity_name="Old Line",
            status="published",
        )
        current_source = GraphEntity(
            knowledge_base_id=1,
            document_id=target_document.id,
            version_no=1,
            entity_type="equipment",
            entity_name="New Pump",
            status="staging",
        )
        current_target = GraphEntity(
            knowledge_base_id=1,
            document_id=target_document.id,
            version_no=1,
            entity_type="line",
            entity_name="New Line",
            status="staging",
        )
        other_source = GraphEntity(
            knowledge_base_id=1,
            document_id=other_document.id,
            version_no=1,
            entity_type="equipment",
            entity_name="Other Pump",
            status="published",
        )
        other_target = GraphEntity(
            knowledge_base_id=1,
            document_id=other_document.id,
            version_no=1,
            entity_type="line",
            entity_name="Other Line",
            status="published",
        )
        db.add_all([old_source, old_target, current_source, current_target, other_source, other_target])
        db.flush()

        old_relation = GraphRelation(
            knowledge_base_id=1,
            source_entity_id=old_source.id,
            target_entity_id=old_target.id,
            relation_type="connects",
            document_id=target_document.id,
            version_no=0,
            status="published",
        )
        current_relation = GraphRelation(
            knowledge_base_id=1,
            source_entity_id=current_source.id,
            target_entity_id=current_target.id,
            relation_type="connects",
            document_id=target_document.id,
            version_no=1,
            status="staging",
        )
        other_relation = GraphRelation(
            knowledge_base_id=1,
            source_entity_id=other_source.id,
            target_entity_id=other_target.id,
            relation_type="connects",
            document_id=other_document.id,
            version_no=1,
            status="published",
        )
        db.add_all([old_relation, current_relation, other_relation])
        db.commit()

        entity_count = GraphRepository(db).publish_document_graph(target_document.id, 1)
        db.commit()

        assert entity_count == 2
        assert db.get(GraphEntity, old_source.id).status == "obsolete"
        assert db.get(GraphEntity, old_target.id).status == "obsolete"
        assert db.get(GraphRelation, old_relation.id).status == "obsolete"
        assert db.get(GraphEntity, current_source.id).status == "published"
        assert db.get(GraphEntity, current_target.id).status == "published"
        assert db.get(GraphRelation, current_relation.id).status == "published"
        assert db.get(GraphEntity, other_source.id).status == "published"
        assert db.get(GraphEntity, other_target.id).status == "published"
        assert db.get(GraphRelation, other_relation.id).status == "published"
    finally:
        db.close()
