"""跨通道索引发布清单的数据访问。"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.page_index import IndexPublicationManifest
from app.utils.time_utils import now_utc


class IndexPublicationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, manifest: IndexPublicationManifest) -> IndexPublicationManifest:
        self.db.add(manifest)
        self.db.flush()
        return manifest

    def publish(self, manifest: IndexPublicationManifest) -> None:
        self.db.execute(
            update(IndexPublicationManifest)
            .where(
                IndexPublicationManifest.document_id == manifest.document_id,
                IndexPublicationManifest.status == "published",
                IndexPublicationManifest.id != manifest.id,
            )
            .values(status="obsolete")
        )
        manifest.status = "published"
        manifest.published_at = now_utc()
        self.db.flush()

    def published_tokens(self, document_ids: list[int]) -> list[str]:
        if not document_ids:
            return []
        return list(
            self.db.scalars(
                select(IndexPublicationManifest.publication_token)
                .where(
                    IndexPublicationManifest.document_id.in_(document_ids),
                    IndexPublicationManifest.status == "published",
                )
                .order_by(IndexPublicationManifest.id)
            ).all()
        )

    def get_by_token(self, publication_token: str) -> IndexPublicationManifest | None:
        return self.db.scalar(
            select(IndexPublicationManifest).where(
                IndexPublicationManifest.publication_token == publication_token
            )
        )
