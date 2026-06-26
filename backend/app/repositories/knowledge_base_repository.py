"""Knowledge base repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge_base import KnowledgeBase


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
