"""统一已验证可检索范围快照。"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.security_levels import allowed_security_levels, user_max_security_level
from app.models.user import User
from app.repositories.index_publication_repository import IndexPublicationRepository
from app.repositories.verified_retrieval_scope_repository import VerifiedRetrievalScopeRepository


class VerifiedRetrievalScopeService:
    """以业务数据库为唯一事实源生成短 TTL、可主动失效的范围快照。"""

    _shared_cache: dict[tuple[int, str, int | None], dict[str, Any]] = {}

    def __init__(self, db: Session, ttl_seconds: int = 30) -> None:
        self.db = db
        self.ttl_seconds = max(1, ttl_seconds)
        self._cache = self._shared_cache
        self.repository = VerifiedRetrievalScopeRepository(db)

    def create(self, mode: str, project_id: int | None, user: User) -> dict[str, Any]:
        key = (int(user.id), mode, project_id)
        now = time.time()
        cached = self._cache.get(key)
        if cached and float(cached["expires_at"]) > now:
            return dict(cached)
        document_ids = self._build(mode, project_id, user)
        publication_tokens = IndexPublicationRepository(self.db).published_tokens(document_ids)
        snapshot = {
            "snapshot_id": uuid.uuid4().hex,
            "verified": True,
            "verified_at": now,
            "expires_at": now + self.ttl_seconds,
            "document_ids": document_ids,
            "publication_tokens": publication_tokens,
        }
        self._cache[key] = snapshot
        return dict(snapshot)

    def invalidate(self, user_id: int | None = None) -> int:
        keys = [key for key in self._cache if user_id is None or key[0] == int(user_id)]
        for key in keys:
            self._cache.pop(key, None)
        return len(keys)

    def _build(self, mode: str, project_id: int | None, user: User) -> list[int]:
        levels = allowed_security_levels(user_max_security_level(user))
        return self.repository.searchable_document_ids(
            mode,
            project_id,
            levels,
            self.repository.enabled_base_knowledge_base_ids(),
        )
