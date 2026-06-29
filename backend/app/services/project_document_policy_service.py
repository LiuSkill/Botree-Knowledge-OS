"""Project document retrieval access policy."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.security_levels import can_access_security_level, user_max_security_level
from app.models.document import Document, DocumentChunk
from app.models.user import User
from app.services.project_access_service import ProjectAccessService

PUBLISHED_DOCUMENT_STATUS = "已发布"
INDEX_STATUS_INDEXED = "indexed"
ACTIVE_CHUNK_STATUS = "active"


class ProjectDocumentPolicyService:
    """项目问答资料准入规则，供检索、重排和生成前断言复用。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.project_access = ProjectAccessService(db)

    def project_chat_document_reject_reason(
        self,
        document: Document | None,
        *,
        user: User | Any | None,
        project_id: int | None,
        require_chat_permission: bool = True,
    ) -> str | None:
        """返回项目问答不可使用该文档的原因，返回 None 表示可进入问答链路。"""

        if document is None:
            return "document_missing"
        if project_id is None:
            return "project_missing"
        if document.project_id != project_id:
            return "project_mismatch"
        if bool(getattr(document, "is_deleted", False)):
            return "document_deleted"
        if str(getattr(document, "knowledge_type", "") or "") != "project":
            return "source_scope_denied"

        if user is None:
            return "permission_denied"
        try:
            permission_codes = ("project_chat:ask",) if require_chat_permission else ("project:view", "project")
            self.project_access.ensure_project_access(int(project_id), user, permission_codes=permission_codes)
        except AppException:
            return "permission_denied"

        if not can_access_security_level(user_max_security_level(user), document.security_level):
            return "permission_denied"
        if str(getattr(document, "status", "") or "").strip() != PUBLISHED_DOCUMENT_STATUS:
            return "document_not_published"
        if not bool(getattr(document, "ai_enabled", False)):
            return "ai_disabled"
        if str(getattr(document, "index_status", "") or "").strip() != INDEX_STATUS_INDEXED:
            return "index_not_current"
        if not bool(getattr(document, "is_current_version", False)):
            return "version_not_current"
        return None

    def project_chat_chunk_reject_reason(
        self,
        chunk: DocumentChunk | None,
        document: Document,
        *,
        user: User | Any | None,
        project_id: int | None,
    ) -> str | None:
        """校验 Evidence 对应 Chunk 是否仍属于当前可检索版本。"""

        if chunk is None:
            return "chunk_missing"
        if chunk.document_id != document.id:
            return "chunk_document_mismatch"
        if chunk.project_id is not None and project_id is not None and chunk.project_id != project_id:
            return "project_mismatch"
        if str(getattr(chunk, "chunk_status", "") or "").strip() != ACTIVE_CHUNK_STATUS:
            return "chunk_inactive"
        if not can_access_security_level(user_max_security_level(user), chunk.security_level):
            return "permission_denied"
        if chunk.version_no != document.version_no:
            return "version_not_current"
        return None

    def project_chat_evidence_reject_reason(
        self,
        *,
        document: Document | None,
        chunk: DocumentChunk | None,
        user: User | Any | None,
        project_id: int | None,
        require_chat_permission: bool = True,
    ) -> str | None:
        """组合校验项目文档和 Chunk，用于 AnswerGenerator 前最终证据断言。"""

        if reason := self.project_chat_document_reject_reason(
            document,
            user=user,
            project_id=project_id,
            require_chat_permission=require_chat_permission,
        ):
            return reason
        if document is None:
            return "document_missing"
        return self.project_chat_chunk_reject_reason(chunk, document, user=user, project_id=project_id)
