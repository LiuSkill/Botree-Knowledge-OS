"""Knowledge base repository."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk
from app.models.knowledge_base import KnowledgeBase


@dataclass(frozen=True)
class KnowledgeBaseStatsRow:
    """知识库聚合统计行，避免 Service 层按知识库、文档循环查询。"""

    knowledge_base: KnowledgeBase
    document_count: int
    chunk_count: int


class KnowledgeBaseRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, kb_type: str | None = None, project_id: int | None = None) -> list[KnowledgeBase]:
        stmt = select(KnowledgeBase).order_by(KnowledgeBase.id.desc())
        if kb_type:
            stmt = stmt.where(KnowledgeBase.type == kb_type)
        if project_id is not None:
            stmt = stmt.where(KnowledgeBase.project_id == project_id)
        return list(self.db.scalars(stmt).all())

    def list_with_counts(self, kb_type: str | None = None, project_id: int | None = None) -> list[KnowledgeBaseStatsRow]:
        """查询知识库列表并聚合未删除资料数、有效分块数。"""

        document_counts = (
            select(
                Document.knowledge_base_id.label("knowledge_base_id"),
                func.count(Document.id).label("document_count"),
            )
            .where(Document.is_deleted.is_(False))
            .group_by(Document.knowledge_base_id)
            .subquery()
        )
        chunk_counts = (
            select(
                Document.knowledge_base_id.label("knowledge_base_id"),
                func.count(DocumentChunk.id).label("chunk_count"),
            )
            .join(DocumentChunk, DocumentChunk.document_id == Document.id)
            .where(Document.is_deleted.is_(False), DocumentChunk.chunk_status == "active")
            .group_by(Document.knowledge_base_id)
            .subquery()
        )
        stmt = (
            select(
                KnowledgeBase,
                func.coalesce(document_counts.c.document_count, 0),
                func.coalesce(chunk_counts.c.chunk_count, 0),
            )
            .outerjoin(document_counts, document_counts.c.knowledge_base_id == KnowledgeBase.id)
            .outerjoin(chunk_counts, chunk_counts.c.knowledge_base_id == KnowledgeBase.id)
            .order_by(KnowledgeBase.id.desc())
        )
        if kb_type:
            stmt = stmt.where(KnowledgeBase.type == kb_type)
        if project_id is not None:
            stmt = stmt.where(KnowledgeBase.project_id == project_id)
        return [
            KnowledgeBaseStatsRow(
                knowledge_base=knowledge_base,
                document_count=int(document_count or 0),
                chunk_count=int(chunk_count or 0),
            )
            for knowledge_base, document_count, chunk_count in self.db.execute(stmt).all()
        ]

    def get(self, kb_id: int) -> KnowledgeBase | None:
        return self.db.get(KnowledgeBase, kb_id)

    def get_by_code(self, code: str) -> KnowledgeBase | None:
        return self.db.scalar(select(KnowledgeBase).where(KnowledgeBase.code == code))

    def get_project_base(self, project_id: int) -> KnowledgeBase | None:
        return self.db.scalar(select(KnowledgeBase).where(KnowledgeBase.type == "project", KnowledgeBase.project_id == project_id))

    def add(self, knowledge_base: KnowledgeBase) -> KnowledgeBase:
        self.db.add(knowledge_base)
        self.db.flush()
        return knowledge_base

    def delete(self, knowledge_base: KnowledgeBase) -> None:
        self.db.delete(knowledge_base)
        self.db.flush()
