"""Keyword retriever."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security_levels import allowed_security_levels, user_max_security_level
from app.models.document import Document, DocumentChunk
from app.models.knowledge_base import KnowledgeBase
from app.models.project import Project
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.retrieval.base import BaseRetriever
from app.retrieval.query_utils import extract_query_terms, score_text_relevance
from app.retrieval.schemas import Evidence
from app.services.project_service import ProjectService


class KeywordRetriever(BaseRetriever):
    """基于数据库 Chunk 正文的轻量关键词检索器。"""

    name = "keyword"

    def __init__(self, db: Session) -> None:
        self.db = db

    def search(self, query: str, mode: str, project_id: int | None, user: User, limit: int = 5) -> list[Evidence]:
        terms = self._terms(query)
        evidences: list[Evidence] = []
        project_service = ProjectService(self.db)
        allowed_levels = self._allowed_security_levels(user)

        for chunk, document in DocumentRepository(self.db).searchable_chunks(security_levels=allowed_levels):
            if not self._scope_allowed(document.knowledge_type, document.project_id, document.knowledge_base_id, mode, project_id, user):
                continue
            if document.project_id is not None:
                try:
                    project_service.ensure_project_access(document.project_id, user)
                except Exception:
                    continue

            score = self._score(chunk.content, query, terms)
            if score <= 0:
                continue
            evidences.append(
                Evidence(
                    score=score,
                    source_type=self._source_type(document.knowledge_type, mode),
                    knowledge_base_id=document.knowledge_base_id,
                    project_id=document.project_id,
                    document_id=document.id,
                    chunk_id=chunk.id,
                    drawing_no=document.drawing_no,
                    file_name=document.file_name,
                    page_number=chunk.page_number,
                    content=chunk.content,
                    retriever=self.name,
                    metadata=self._evidence_metadata(document, chunk),
                )
            )
        return sorted(evidences, key=lambda item: item.score, reverse=True)[:limit]

    def _scope_allowed(
        self,
        knowledge_type: str,
        doc_project_id: int | None,
        knowledge_base_id: int,
        mode: str,
        project_id: int | None,
        user: User,
    ) -> bool:
        """判断 Chunk 是否落在当前问答范围内，不再读取旧 KB 授权模型。"""

        effective_mode = "hybrid" if mode == "auto" and project_id is not None else ("base_only" if mode == "auto" else mode)
        if effective_mode == "project_chat":
            return knowledge_type == "project" and doc_project_id == project_id
        if effective_mode == "base_chat":
            return knowledge_type == "base" and self._base_knowledge_allowed(knowledge_base_id, project_id, user, strict_external=False)
        if effective_mode == "base_only":
            return knowledge_type == "base" and self._base_knowledge_allowed(knowledge_base_id, project_id, user, strict_external=False)
        if effective_mode == "project_only":
            return knowledge_type == "project" and doc_project_id == project_id
        if effective_mode == "project_with_industry":
            return (knowledge_type == "project" and doc_project_id == project_id) or (
                knowledge_type == "base" and self._base_knowledge_allowed(knowledge_base_id, project_id, user, strict_external=True)
            )
        if effective_mode == "hybrid":
            return (
                knowledge_type == "base" and self._base_knowledge_allowed(knowledge_base_id, project_id, user, strict_external=False)
            ) or (knowledge_type == "project" and doc_project_id == project_id)
        return False

    def _source_type(self, knowledge_type: str, mode: str) -> str:  # noqa: ARG002
        return "base" if knowledge_type == "base" else "project"

    def _base_knowledge_allowed(
        self,
        knowledge_base_id: int,
        project_id: int | None,  # noqa: ARG002
        user: User,  # noqa: ARG002
        strict_external: bool,  # noqa: ARG002
    ) -> bool:
        """基础知识库只作为容器，启用即可进入密级过滤后的检索范围。"""

        if self.db is None:
            return True
        knowledge_base = self.db.get(KnowledgeBase, knowledge_base_id)
        return bool(knowledge_base and knowledge_base.enabled and knowledge_base.type == "base")

    def accessible_base_knowledge_base_ids(self, project_id: int | None, user: User, strict_external: bool) -> list[int]:  # noqa: ARG002
        """返回启用的基础知识库容器 ID，内容权限由文档密级控制。"""

        if self.db is None:
            return []
        stmt = select(KnowledgeBase.id).where(KnowledgeBase.type == "base", KnowledgeBase.enabled.is_(True))
        return [int(kb_id) for kb_id in self.db.scalars(stmt).all()]

    def _evidence_metadata(
        self,
        document: Document,
        chunk: DocumentChunk,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = {
            "source_scope": "project" if document.knowledge_type == "project" else "base",
            "security_level": chunk.security_level or document.security_level,
            "document_security_level": document.security_level,
            "project_security_level": self._project_security_level(document),
            "review_status": document.review_status,
            "document_status": document.document_status,
            "index_status": document.index_status,
            "chunk_status": chunk.chunk_status,
            "current_version": chunk.version_no == document.version_no and bool(document.current_version),
            "version_no": chunk.version_no,
            "document_version_no": document.version_no,
        }
        if extra:
            metadata.update(extra)
        return metadata

    def _project_security_level(self, document: Document) -> str | None:
        if self.db is None or document.project_id is None:
            return None
        project = self.db.get(Project, document.project_id)
        return getattr(project, "security_level", None)

    def _allowed_security_levels(self, user: User) -> list[str]:
        return allowed_security_levels(user_max_security_level(user))

    def _is_external_user(self, user: User) -> bool:
        return any(role.code == "external" or "外部" in role.name for role in getattr(user, "roles", []) or [])

    def _terms(self, query: str) -> list[str]:
        return extract_query_terms(query)

    def _score(self, content: str, query: str, terms: list[str] | None = None) -> float:
        return score_text_relevance(content, query, terms or self._terms(query))
