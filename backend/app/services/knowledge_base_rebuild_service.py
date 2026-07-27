"""从可复用解析页执行知识库原地完整重建。"""

from dataclasses import dataclass
import json
import logging

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.knowledge.chunking.chunk_builder import ChunkBuilder
from app.knowledge.indexing.index_service import IndexService
from app.models.document import Document, DocumentChunk
from app.repositories.document_repository import DocumentRepository
from app.repositories.index_publication_repository import IndexPublicationRepository
from app.repositories.knowledge_base_rebuild_repository import KnowledgeBaseRebuildRepository
from app.services.index_pipeline_service import IndexPipelineService
from app.knowledge.indexing.visual_milvus_indexer import VisualMilvusIndexer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RebuildSourceSnapshot:
    digest: str
    document_ids: tuple[int, ...]


class KnowledgeBaseRebuildService:
    """重建期间清空旧分块并复用解析页；源发生变化时拒绝发布。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = KnowledgeBaseRebuildRepository(db)
        self.document_repository = DocumentRepository(db)
        self.publication_repository = IndexPublicationRepository(db)

    def rebuild(self, knowledge_base_id: int) -> dict[str, object]:
        documents = self.repository.list_source_documents(knowledge_base_id)
        before = self._snapshot(documents)
        results: list[dict[str, object]] = []
        manifests = []
        for document in documents:
            pages = self.repository.list_pages(document)
            if not pages:
                raise AppException(f"文档 {document.id} 缺少可复用解析页，无法原地重建")
            payloads = [
                {
                    "page_number": page.page_no,
                    "page_title": page.page_title,
                    "text": page.corrected_text or page.clean_content or page.page_text,
                }
                for page in pages
                if page.index_admission_status == "text_indexed"
            ]
            chunks = self._build_chunks(document, payloads)
            old_chunks = self.document_repository.list_chunks(document.id, include_obsolete=True)
            vector_ids = [chunk.vector_id for chunk in old_chunks if chunk.vector_id]
            IndexService(self.db).delete_document_index(document.id, vector_ids)
            if get_settings().visual_index_enabled:
                VisualMilvusIndexer().delete_document(document.id)
            self.document_repository.clear_chunks(document.id)
            self.document_repository.replace_chunks(document.id, chunks, version_no=document.version_no)
            result = IndexPipelineService(self.db).build_all(document, publish=False)
            results.append(result)
            manifest = self.publication_repository.get_by_token(str(result["publication_token"]))
            if manifest is None:
                raise AppException(f"document {document.id} is missing its staging publication manifest")
            manifests.append((document, manifest))
        self.db.flush()
        self.ensure_unchanged(before, self._snapshot(self.repository.list_source_documents(knowledge_base_id)))
        for document, manifest in manifests:
            IndexPipelineService(self.db).publish_all(document, manifest=manifest)
        self.db.commit()
        logger.info("知识库原地重建完成: knowledge_base_id=%s document_count=%s", knowledge_base_id, len(documents))
        return {"knowledge_base_id": knowledge_base_id, "document_count": len(documents), "results": results}

    @staticmethod
    def ensure_unchanged(before: RebuildSourceSnapshot, after: RebuildSourceSnapshot) -> None:
        if before != after:
            raise AppException("重建期间源快照发生变化，已拒绝发布")

    def _snapshot(self, documents: list[Document]) -> RebuildSourceSnapshot:
        return RebuildSourceSnapshot(self.repository.snapshot_digest(documents), tuple(item.id for item in documents))

    def _build_chunks(self, document: Document, pages: list[dict[str, object]]) -> list[DocumentChunk]:
        settings = get_settings()
        return [
            DocumentChunk(
                knowledge_base_id=document.knowledge_base_id,
                document_id=document.id,
                project_id=document.project_id,
                knowledge_type=document.knowledge_type,
                version_no=document.version_no,
                chunk_status="active",
                chunk_index=item["chunk_index"],
                content=item["content"],
                page_number=item["page_number"],
                section_title=item["section_title"],
                security_level=document.security_level,
                metadata_json=json.dumps(item.get("metadata", {}), ensure_ascii=False),
            )
            for item in ChunkBuilder(rule_version="structure-v1", index_generation=settings.visual_index_generation).build(pages)
        ]
