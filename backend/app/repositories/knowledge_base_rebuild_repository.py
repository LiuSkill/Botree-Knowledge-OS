"""知识库原地重建所需的数据访问。"""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.page_index import DocumentPage


class KnowledgeBaseRebuildRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_source_documents(self, knowledge_base_id: int) -> list[Document]:
        return list(
            self.db.scalars(
                select(Document)
                .where(
                    Document.knowledge_base_id == knowledge_base_id,
                    Document.is_deleted.is_(False),
                    Document.is_current_version.is_(True),
                    Document.parse_status == "success",
                )
                .order_by(Document.id)
            ).all()
        )

    def snapshot_digest(self, documents: list[Document]) -> str:
        payload = []
        for item in documents:
            pages = self.list_pages(item)
            payload.append({
                "id": item.id,
                "version_no": item.version_no,
                "storage_path": item.storage_path,
                "review_status": item.review_status,
                "security_level": item.security_level,
                "is_current_version": item.is_current_version,
                "pages": [
                    {
                        "page_no": page.page_no,
                        "source_hash": page.source_hash,
                        "correction_status": page.correction_status,
                        "corrected_text": page.corrected_text,
                        "clean_content": page.clean_content,
                    }
                    for page in pages
                ],
            })
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def list_pages(self, document: Document) -> list[DocumentPage]:
        return list(
            self.db.scalars(
                select(DocumentPage)
                .where(DocumentPage.document_id == document.id, DocumentPage.version_no == document.version_no)
                .order_by(DocumentPage.page_no)
            ).all()
        )
