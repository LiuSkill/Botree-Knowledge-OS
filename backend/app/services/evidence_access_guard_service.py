"""Final evidence access guard service."""

from __future__ import annotations

import logging
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.security_levels import can_access_security_level, normalize_security_level, user_max_security_level
from app.models.document import Document, DocumentChunk
from app.retrieval.schemas import Evidence
from app.services.project_document_policy_service import ProjectDocumentPolicyService

logger = logging.getLogger(__name__)

APPROVED_DOCUMENT_STATUSES = {"reviewed", "active"}
APPROVED_REVIEW_STATUSES = {"approved"}
PUBLISHED_DOCUMENT_STATUSES = {"已发布"}
ACTIVE_INDEX_STATUSES = {"indexed"}
ACTIVE_CHUNK_STATUSES = {"active"}


@dataclass(frozen=True)
class EvidenceGuardResult:
    """最终证据断言结果。"""

    evidences: list[Evidence]
    rejected: list[dict[str, Any]] = field(default_factory=list)
    rejection_counts: dict[str, int] = field(default_factory=dict)
    primary_reason: str = ""
    risk: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvidenceAccessGuardService:
    """LLM prompt 组装前的最后一道证据安全门。"""

    def __init__(self, db: Session | None) -> None:
        self.db = db
        self.project_document_policy = ProjectDocumentPolicyService(db) if db is not None else None

    def filter_evidences(
        self,
        *,
        evidences: list[Evidence],
        chat_type: str,
        project_id: int | None,
        user: Any | None,
        audit_action: str = "RAG证据权限过滤",
    ) -> EvidenceGuardResult:
        accepted: list[Evidence] = []
        rejected: list[dict[str, Any]] = []
        for evidence in evidences:
            reason = self._reject_reason(evidence, chat_type=chat_type, project_id=project_id, user=user)
            if reason:
                rejected.append(
                    {
                        "document_id": evidence.document_id,
                        "chunk_id": evidence.chunk_id,
                        "file_name": evidence.file_name,
                        "reason": reason,
                    }
                )
                continue
            accepted.append(evidence)

        counts = dict(Counter(item["reason"] for item in rejected))
        primary_reason = self._primary_reason(counts)
        result = EvidenceGuardResult(
            evidences=accepted,
            rejected=rejected,
            rejection_counts=counts,
            primary_reason=primary_reason,
            risk=self._risk_for_reason(primary_reason),
        )
        if rejected:
            logger.info(
                "final_evidence_guard: accepted=%s rejected=%s primary_reason=%s counts=%s chat_type=%s project_id=%s user_level=%s",
                len(accepted),
                len(rejected),
                primary_reason,
                counts,
                chat_type,
                project_id,
                user_max_security_level(user),
            )
            self._record_filtered_audit(
                rejected,
                chat_type=chat_type,
                project_id=project_id,
                user=user,
                audit_action=audit_action,
                rejection_counts=counts,
            )
        return result

    def _reject_reason(
        self,
        evidence: Evidence,
        *,
        chat_type: str,
        project_id: int | None,
        user: Any | None,
    ) -> str | None:
        if reason := self._scope_reject_reason(evidence, chat_type=chat_type, project_id=project_id):
            return reason
        if reason := self._security_reject_reason(evidence, user):
            return reason
        if reason := self._metadata_status_reject_reason(evidence, chat_type=chat_type):
            return reason
        if self.db is None or bool((evidence.metadata or {}).get("metadata_only")):
            return None
        return self._database_status_reject_reason(evidence, chat_type=chat_type, project_id=project_id, user=user)

    def _scope_reject_reason(self, evidence: Evidence, *, chat_type: str, project_id: int | None) -> str | None:
        metadata = evidence.metadata or {}
        if not self._source_scope_allows(metadata.get("source_scope"), chat_type):
            return "source_scope_denied"
        if chat_type == "project_chat":
            if project_id is None:
                return "project_missing"
            if evidence.project_id != project_id:
                return "project_mismatch"
            return None
        if chat_type == "base_chat" and evidence.project_id is not None and evidence.source_type == "project":
            return "source_scope_denied"
        return None

    def _source_scope_allows(self, raw_scope: Any, chat_type: str) -> bool:
        if raw_scope is None:
            return True
        if isinstance(raw_scope, str):
            scopes = {item.strip() for item in raw_scope.split(",") if item.strip()}
        elif isinstance(raw_scope, list):
            scopes = {str(item).strip() for item in raw_scope if str(item).strip()}
        else:
            return True
        scope_aliases = {
            "project_chat": {"project_chat", "project"},
            "base_chat": {"base_chat", "base", "industry"},
        }
        return not scopes or bool(scopes & scope_aliases.get(chat_type, {chat_type})) or "all" in scopes

    def _security_reject_reason(self, evidence: Evidence, user: Any | None) -> str | None:
        metadata = evidence.metadata or {}
        raw_level = metadata.get("security_level")
        if raw_level is None:
            return "security_level_missing"
        try:
            evidence_level = normalize_security_level(raw_level)
        except Exception:  # noqa: BLE001
            return "security_level_invalid"
        if not can_access_security_level(user_max_security_level(user), evidence_level):
            return "permission_denied"
        return None

    def _metadata_status_reject_reason(self, evidence: Evidence, *, chat_type: str) -> str | None:
        metadata = evidence.metadata or {}
        project_evidence = chat_type == "project_chat" or evidence.source_type == "project"
        if project_evidence and self._metadata_bool(metadata.get("is_deleted")) is True:
            return "document_deleted"
        if project_evidence:
            status = str(metadata.get("status") or "").strip()
            if status and status not in PUBLISHED_DOCUMENT_STATUSES:
                return "document_not_published"
            ai_enabled = self._metadata_bool(metadata.get("ai_enabled"))
            if ai_enabled is False:
                return "ai_disabled"
            is_current_version = self._metadata_bool(metadata.get("is_current_version"))
            if is_current_version is False:
                return "version_not_current"
        review_status = str(metadata.get("review_status") or "").strip()
        document_status = str(metadata.get("document_status") or "").strip()
        index_status = str(metadata.get("index_status") or "").strip()
        chunk_status = str(metadata.get("chunk_status") or "").strip()
        current_version = metadata.get("current_version")
        if review_status and review_status not in APPROVED_REVIEW_STATUSES:
            return "document_not_approved"
        if document_status and document_status not in APPROVED_DOCUMENT_STATUSES:
            return "document_not_approved"
        if index_status and index_status not in ACTIVE_INDEX_STATUSES:
            return "index_not_current"
        if chunk_status and chunk_status not in ACTIVE_CHUNK_STATUSES:
            return "chunk_inactive"
        if current_version is False or str(current_version).strip().lower() == "false":
            return "version_not_current"
        return None

    def _database_status_reject_reason(
        self,
        evidence: Evidence,
        *,
        chat_type: str,
        project_id: int | None,
        user: Any | None,
    ) -> str | None:
        document = self.db.get(Document, evidence.document_id)
        if document is None:
            return "document_missing"
        if document.project_id != evidence.project_id:
            return "project_mismatch"
        if not can_access_security_level(user_max_security_level(user), document.security_level):
            return "permission_denied"
        if bool(getattr(document, "is_deleted", False)):
            return "document_deleted"
        if document.project_id is not None and self.project_document_policy is not None:
            if reason := self.project_document_policy.project_chat_document_reject_reason(
                document,
                user=user,
                project_id=project_id,
                require_chat_permission=chat_type == "project_chat",
            ):
                return reason
        else:
            if document.review_status not in APPROVED_REVIEW_STATUSES:
                return "document_not_approved"
            if document.document_status not in APPROVED_DOCUMENT_STATUSES:
                return "document_not_approved"
        if document.index_status not in ACTIVE_INDEX_STATUSES:
            return "index_not_current"
        if not bool(document.current_version) or not bool(getattr(document, "is_current_version", False)):
            return "version_not_current"
        chunk = self.db.get(DocumentChunk, evidence.chunk_id)
        if chunk is None:
            return "chunk_missing"
        if chunk.document_id != document.id:
            return "chunk_document_mismatch"
        if document.project_id is not None and self.project_document_policy is not None:
            if reason := self.project_document_policy.project_chat_chunk_reject_reason(
                chunk,
                document,
                user=user,
                project_id=project_id,
            ):
                return reason
        if not can_access_security_level(user_max_security_level(user), chunk.security_level):
            return "permission_denied"
        if chunk.chunk_status not in ACTIVE_CHUNK_STATUSES:
            return "chunk_inactive"
        if chunk.version_no != document.version_no:
            return "version_not_current"
        return None

    def _primary_reason(self, counts: dict[str, int]) -> str:
        if not counts:
            return ""
        priority = [
            "permission_denied",
            "security_level_missing",
            "security_level_invalid",
            "project_mismatch",
            "source_scope_denied",
            "document_deleted",
            "document_not_published",
            "document_not_approved",
            "ai_disabled",
            "version_not_current",
            "index_not_current",
            "chunk_inactive",
        ]
        for reason in priority:
            if reason in counts:
                return reason
        return max(counts.items(), key=lambda item: item[1])[0]

    def _risk_for_reason(self, reason: str) -> str:
        if reason in {"permission_denied", "security_level_missing", "security_level_invalid", "source_scope_denied"}:
            return "permission_limited"
        if reason in {"project_mismatch", "document_missing", "chunk_missing"}:
            return "irrelevant"
        if reason in {"document_deleted", "document_not_published", "ai_disabled", "version_not_current", "index_not_current"}:
            return "insufficient_coverage"
        if reason:
            return "insufficient_coverage"
        return "none"

    def _metadata_bool(self, value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "是"}

    def _record_filtered_audit(
        self,
        rejected: list[dict[str, Any]],
        *,
        chat_type: str,
        project_id: int | None,
        user: Any | None,
        audit_action: str,
        rejection_counts: dict[str, int],
    ) -> None:
        if self.db is None:
            return
        try:
            from app.services.system_service import SystemService

            detail = {
                "chat_type": chat_type,
                "project_id": project_id,
                "filtered_count": len(rejected),
                "rejection_counts": rejection_counts,
                "items": [
                    {
                        "document_id": item.get("document_id"),
                        "chunk_id": item.get("chunk_id"),
                        "reason": item.get("reason"),
                    }
                    for item in rejected[:20]
                ],
            }
            SystemService(self.db).record_operation(
                user,
                audit_action,
                "rag_evidence",
                project_id,
                json.dumps(detail, ensure_ascii=False),
                result="filtered",
                project_id=project_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("evidence过滤审计日志写入失败: action=%s error=%s", audit_action, exc)
