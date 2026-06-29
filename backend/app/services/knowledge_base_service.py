"""Knowledge base service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.services.project_service import ProjectService
from app.services.system_service import SystemService


class KnowledgeBaseService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = KnowledgeBaseRepository(db)

    def list_bases(self, user: User, kb_type: str | None = None, project_id: int | None = None) -> list[dict]:
        if project_id is not None:
            ProjectService(self.db).ensure_project_access(project_id, user)
        bases = self.repository.list(kb_type=kb_type, project_id=project_id)
        doc_repo = DocumentRepository(self.db)
        result: list[dict] = []
        for kb in bases:
            if kb.type == "project" and kb.project_id is not None:
                ProjectService(self.db).ensure_project_access(kb.project_id, user)
            documents = doc_repo.list(knowledge_base_id=kb.id)
            result.append(self._kb_to_dict(kb, len(documents), sum(len(doc_repo.list_chunks(doc.id)) for doc in documents)))
        return result

    def get_project_base(
        self,
        project_id: int,
        user: User,
        permission_codes: tuple[str, ...] = ("project:view", "project"),
    ) -> KnowledgeBase:
        ProjectService(self.db).ensure_project_access(project_id, user, permission_codes)
        knowledge_base = self.repository.get_project_base(project_id)
        if not knowledge_base:
            raise AppException("项目知识库不存在", status_code=404, code=404)
        return knowledge_base

    def get_base(self, kb_id: int, user: User) -> dict:
        kb = self.repository.get(kb_id)
        if not kb:
            raise AppException("知识库不存在", status_code=404, code=404)
        if kb.type == "project" and kb.project_id is not None:
            ProjectService(self.db).ensure_project_access(kb.project_id, user)
        documents = DocumentRepository(self.db).list(knowledge_base_id=kb.id)
        doc_repo = DocumentRepository(self.db)
        return self._kb_to_dict(kb, len(documents), sum(len(doc_repo.list_chunks(doc.id)) for doc in documents))

    def create_base(self, payload: KnowledgeBaseCreate, operator: User) -> KnowledgeBase:
        if self.repository.get_by_code(payload.code):
            raise AppException("知识库编码已存在")
        if payload.type == "project" and payload.project_id is None:
            raise AppException("项目知识库必须绑定 project_id")
        if payload.type == "project" and payload.project_id is not None:
            ProjectService(self.db).ensure_project_access(payload.project_id, operator)
        kb = KnowledgeBase(
            name=payload.name,
            code=payload.code,
            type=payload.type,
            project_id=payload.project_id,
            description=payload.description,
            enabled=payload.enabled,
            created_by=operator.id,
        )
        self.repository.add(kb)
        SystemService(self.db).record_operation(operator, "创建知识库", "knowledge_base", kb.id, f"创建知识库 {kb.name}")
        self.db.commit()
        return kb

    def update_base(self, kb_id: int, payload: KnowledgeBaseUpdate, operator: User) -> KnowledgeBase:
        kb = self.repository.get(kb_id)
        if not kb:
            raise AppException("知识库不存在", status_code=404, code=404)
        if kb.type == "project" and kb.project_id is not None:
            ProjectService(self.db).ensure_project_access(kb.project_id, operator)
        for field in ["name", "description", "enabled"]:
            value = getattr(payload, field)
            if value is not None:
                setattr(kb, field, value)
        SystemService(self.db).record_operation(operator, "编辑知识库", "knowledge_base", kb.id, f"编辑知识库 {kb.name}")
        self.db.commit()
        return kb

    def delete_base(self, kb_id: int, operator: User) -> None:
        kb = self.repository.get(kb_id)
        if not kb:
            raise AppException("知识库不存在", status_code=404, code=404)
        if kb.type == "project" and kb.project_id is not None:
            ProjectService(self.db).ensure_project_access(kb.project_id, operator)
        self.repository.delete(kb)
        SystemService(self.db).record_operation(operator, "删除知识库", "knowledge_base", kb_id, "删除知识库")
        self.db.commit()

    def authorization_summary(self, user: User) -> dict:
        return {"knowledge_bases": self.list_bases(user), "security_levels": ["public", "internal", "confidential"]}

    def _kb_to_dict(self, kb: KnowledgeBase, document_count: int, chunk_count: int) -> dict:
        return {
            "id": kb.id,
            "name": kb.name,
            "code": kb.code,
            "type": kb.type,
            "project_id": kb.project_id,
            "description": kb.description,
            "enabled": kb.enabled,
            "created_by": kb.created_by,
            "created_at": kb.created_at,
            "updated_at": kb.updated_at,
            "document_count": document_count,
            "chunk_count": chunk_count,
        }
