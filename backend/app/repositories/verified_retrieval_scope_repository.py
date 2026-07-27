"""已验证检索范围的数据访问。"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase


class VerifiedRetrievalScopeRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def enabled_base_knowledge_base_ids(self) -> list[int]:
        stmt = select(KnowledgeBase.id).where(KnowledgeBase.type == "base", KnowledgeBase.enabled.is_(True))
        return [int(value) for value in self.db.scalars(stmt).all()]

    def searchable_document_ids(
        self,
        mode: str,
        project_id: int | None,
        security_levels: list[str],
        base_knowledge_base_ids: list[int],
    ) -> list[int]:
        stmt = select(Document.id).where(
            Document.is_deleted.is_(False),
            Document.is_current_version.is_(True),
            Document.index_status == "indexed",
            Document.security_level.in_(security_levels),
        )
        clauses = []
        if mode in {"project_only", "project_chat", "project_with_industry", "hybrid"} and project_id is not None:
            clauses.append(Document.project_id == project_id)
        if mode in {"base_only", "base_chat", "project_with_industry", "hybrid"} and base_knowledge_base_ids:
            clauses.append(
                (Document.project_id.is_(None))
                & (Document.review_status == "approved")
                & (Document.knowledge_base_id.in_(base_knowledge_base_ids))
            )
        if not clauses:
            return []
        return list(self.db.scalars(stmt.where(or_(*clauses)).order_by(Document.id)).all())
