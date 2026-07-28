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
from app.repositories.document_asset_repository import DocumentAssetRepository
from app.repositories.index_publication_repository import IndexPublicationRepository
from app.repositories.knowledge_base_rebuild_repository import KnowledgeBaseRebuildRepository
from app.repositories.graph_repository import GraphRepository
from app.repositories.page_index_repository import PageIndexRepository
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
        # 迁移前的页面没有准入结论；回填属于重建准备动作，必须在源快照之前完成，
        # 否则重建自身写入的准入状态会被误判为上传源发生变化。
        for document in documents:
            pages = self.repository.list_pages(document)
            if not pages:
                raise AppException(f"文档 {document.id} 缺少可复用解析页，无法原地重建")
            self._backfill_admission(document, pages)
        before = self._snapshot(documents)
        results: list[dict[str, object]] = []
        for document in documents:
            pages = self.repository.list_pages(document)
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
            IndexService(self.db).delete_document_index(document.id, vector_ids, flush=False)
            if get_settings().visual_index_enabled:
                VisualMilvusIndexer().delete_document(document.id, flush=False)
            # Graph 实体通过外键引用旧 Chunk，必须先清理图谱再替换 Chunk。
            GraphRepository(self.db).clear_all_document_graph(document.id)
            # 复用解析页，但旧 PageIndex 仍通过外键引用旧 Chunk，需要先单独清理。
            PageIndexRepository(self.db).clear_document_indexes(document.id, document.version_no)
            self.document_repository.replace_chunks(document.id, chunks, version_no=document.version_no)
            result = IndexPipelineService(self.db).build_all(document, publish=False)
            results.append(result)
            manifest = self.publication_repository.get_by_token(str(result["publication_token"]))
            if manifest is None:
                raise AppException(f"document {document.id} is missing its staging publication manifest")
            IndexPipelineService(self.db).publish_all(document, manifest=manifest)
            self.db.flush()
            self.ensure_unchanged(before, self._snapshot(self.repository.list_source_documents(knowledge_base_id)))
            # 大知识库可能包含数千文档；逐文档原子提交可限制事务规模，
            # 并保证中途故障时已发布文档无需随未完成文档一起回滚。
            self.db.commit()
            logger.info(
                "知识库文档重建并发布完成: knowledge_base_id=%s document_id=%s",
                knowledge_base_id,
                document.id,
            )
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

    def _backfill_admission(self, document: Document, pages: list[object]) -> None:
        """为迁移前已解析页面恢复准入状态，避免默认值导致文本索引被整体跳过。"""

        text_page_numbers = {
            chunk.page_number
            for chunk in self.document_repository.list_chunks(document.id, version_no=document.version_no)
            if chunk.page_number is not None
        }
        visual_page_ids = {
            asset.page_id
            for asset in DocumentAssetRepository(self.db).list_by_document_version(
                document.id,
                document.version_no,
                status="ready",
            )
            if asset.page_id is not None and asset.asset_type in {"page_preview", "block_image"}
        }
        for page in pages:
            if page.index_admission_status != "waiting_correction":
                continue
            if page.page_no in text_page_numbers:
                page.index_admission_status = "text_indexed"
                page.index_admission_reason_json = '["legacy_active_chunk"]'
                page.text_quality_score = 100
            elif page.id in visual_page_ids:
                page.index_admission_status = "visual_indexed"
                page.index_admission_reason_json = '["legacy_ready_visual_asset"]'
            else:
                page.index_admission_status = "metadata_only"
                page.index_admission_reason_json = '["legacy_no_indexable_content"]'
        self.db.flush()
