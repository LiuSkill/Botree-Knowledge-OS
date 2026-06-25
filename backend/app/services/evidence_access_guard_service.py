"""Final evidence access guard service.

负责：
1. 在答案生成前二次断言证据的项目、权限、审核状态、版本和使用范围。
2. 剔除不合规证据，避免它们进入 LLM prompt。
3. 输出可审计的剔除原因，供 EvidenceEvaluator 重新归一 evidence_status。
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk
from app.retrieval.schemas import Evidence

logger = logging.getLogger(__name__)

APPROVED_DOCUMENT_STATUSES = {"reviewed", "active"}
APPROVED_REVIEW_STATUSES = {"approved"}
ACTIVE_INDEX_STATUSES = {"indexed"}
ACTIVE_CHUNK_STATUSES = {"active"}
SECURITY_LEVELS = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "secret": 3,
    "top_secret": 4,
}


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
    """答案生成前的最后一道证据安全门。"""

    def __init__(self, db: Session | None) -> None:
        self.db = db

    def filter_evidences(
        self,
        *,
        evidences: list[Evidence],
        chat_type: str,
        project_id: int | None,
        user: Any | None,
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
                "final_evidence_guard: accepted=%s rejected=%s primary_reason=%s counts=%s chat_type=%s project_id=%s",
                len(accepted),
                len(rejected),
                primary_reason,
                counts,
                chat_type,
                project_id,
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
        if reason := self._metadata_status_reject_reason(evidence):
            return reason
        if self.db is None:
            return None
        return self._database_status_reject_reason(evidence)

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
        if chat_type == "base_chat":
            if evidence.project_id is not None and evidence.source_type == "project":
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
            "base_chat": {"base_chat", "base", "industry", "authorized_internal"},
        }
        return not scopes or bool(scopes & scope_aliases.get(chat_type, {chat_type})) or "all" in scopes

    def _security_reject_reason(self, evidence: Evidence, user: Any | None) -> str | None:
        raw_level = (evidence.metadata or {}).get("security_level")
        if raw_level is None:
            return None
        evidence_level = self._security_level(raw_level, default=0)
        user_level = self._user_security_level(user)
        if evidence_level > user_level:
            return "permission_denied"
        return None

    def _metadata_status_reject_reason(self, evidence: Evidence) -> str | None:
        metadata = evidence.metadata or {}
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

    def _database_status_reject_reason(self, evidence: Evidence) -> str | None:
        document = self.db.get(Document, evidence.document_id)
        if document is None:
            return "document_missing"
        if document.project_id != evidence.project_id:
            return "project_mismatch"
        if document.review_status not in APPROVED_REVIEW_STATUSES:
            return "document_not_approved"
        if document.document_status not in APPROVED_DOCUMENT_STATUSES:
            return "document_not_approved"
        if document.index_status not in ACTIVE_INDEX_STATUSES:
            return "index_not_current"
        if not bool(document.current_version):
            return "version_not_current"
        chunk = self.db.get(DocumentChunk, evidence.chunk_id)
        if chunk is None:
            return "chunk_missing"
        if chunk.document_id != document.id:
            return "chunk_document_mismatch"
        if chunk.chunk_status not in ACTIVE_CHUNK_STATUSES:
            return "chunk_inactive"
        if chunk.version_no != document.version_no:
            return "version_not_current"
        return None

    def _security_level(self, raw_level: Any, default: int) -> int:
        try:
            return int(raw_level)
        except (TypeError, ValueError):
            return SECURITY_LEVELS.get(str(raw_level or "").strip().lower(), default)

    def _user_security_level(self, user: Any | None) -> int:
        if user is None:
            return SECURITY_LEVELS["internal"]
        if any(getattr(role, "code", "") == "admin" for role in getattr(user, "roles", []) or []):
            return max(SECURITY_LEVELS.values())
        raw_level = getattr(user, "security_level", None)
        if raw_level is None:
            raw_level = getattr(user, "data_security_level", None)
        return self._security_level(raw_level, default=SECURITY_LEVELS["internal"])

    def _primary_reason(self, counts: dict[str, int]) -> str:
        if not counts:
            return ""
        priority = [
            "permission_denied",
            "project_mismatch",
            "source_scope_denied",
            "document_not_approved",
            "version_not_current",
            "index_not_current",
            "chunk_inactive",
        ]
        for reason in priority:
            if reason in counts:
                return reason
        return max(counts.items(), key=lambda item: item[1])[0]

    def _risk_for_reason(self, reason: str) -> str:
        if reason in {"permission_denied", "source_scope_denied"}:
            return "permission_limited"
        if reason in {"project_mismatch", "document_missing", "chunk_missing"}:
            return "irrelevant"
        if reason:
            return "insufficient_coverage"
        return "none"
