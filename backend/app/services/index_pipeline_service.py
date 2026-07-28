"""
Index Pipeline Service

负责：
1. 编排 PageIndex、Milvus、ripgrep 文本镜像和 GraphRAG 多路索引
2. 保持旧同步 build-index 接口和新 RQ 异步任务复用同一套逻辑
3. 在所有索引构建成功后统一发布 staging 索引
"""

import logging
import json
from pathlib import Path
import uuid

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.knowledge.indexing.index_service import IndexService
from app.knowledge.indexing.visual_index_service import VisualIndexAsset, VisualIndexService
from app.knowledge.indexing.visual_milvus_indexer import VisualMilvusIndexer
from app.models.document import Document
from app.models.page_index import DocumentPage, IndexPublicationManifest
from app.repositories.document_asset_repository import DocumentAssetRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.index_publication_repository import IndexPublicationRepository
from app.services.graph_index_service import GraphIndexService
from app.services.page_index_service import PageIndexService
from app.services.index_publication_service import IndexPublicationService
from app.services.visual_embedding_service import VisualEmbeddingService

logger = logging.getLogger(__name__)


class IndexPipelineService:
    """
    多路索引流水线服务

    职责：
    - 构建 PageIndex 文档树和 ripgrep 文本镜像
    - 调用 Milvus 向量索引
    - 构建并发布 MySQL GraphRAG 图谱
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.document_repository = DocumentRepository(db)
        self.asset_repository = DocumentAssetRepository(db)
        self.publication_repository = IndexPublicationRepository(db)
        self.page_index_service = PageIndexService(db)
        self.graph_index_service = GraphIndexService(db)
        self.vector_index_service = IndexService(db)
        self.settings = get_settings()

    def build_all(self, document: Document, publish: bool = True) -> dict:
        """
        构建文档多路索引。

        参数:
            document: 文档 ORM 对象。
            publish: 是否在构建完成后立即发布。

        返回:
            多路索引结果摘要。
        """

        chunks = self.document_repository.list_chunks(document.id, version_no=document.version_no)
        pages = self.page_index_service.repository.list_pages(document.id, document.version_no)
        visual_assets = self._list_visual_assets(document, pages) if self.settings.visual_index_enabled else []
        if not chunks and not visual_assets:
            raise AppException("文档尚未生成 Chunk，无法构建多路索引")
        if not pages:
            raise AppException("文档尚未生成 PageIndex 页级模型，无法构建多路索引")

        publication_token = uuid.uuid4().hex
        page_result = self.page_index_service.build_page_indexes(document) if chunks else {"skipped": True, "reason": "visual_only"}
        if chunks and self.settings.milvus_enabled:
            vector_result = self.vector_index_service.index_document(document.id, version_no=document.version_no)
        else:
            vector_result = {"skipped": True, "reason": "Milvus未启用，跳过向量索引构建"}
            logger.info("Milvus未启用，跳过向量索引构建: document_id=%s", document.id)
        visual_result = self._build_visual_index(visual_assets, publication_token)
        graph_result = self.graph_index_service.build_document_graph(document) if chunks else {"skipped": True, "reason": "visual_only"}
        completed: dict[str, set[int]] = {"text": set(), "visual": set(), "metadata": set()}
        if chunks and self.settings.milvus_enabled and not vector_result.get("skipped"):
            completed["text"] = {page.id for page in pages if page.index_admission_status == "text_indexed"}
        if visual_assets and not visual_result.get("skipped") and visual_result.get("status") != "skipped":
            completed["visual"] = {asset.page_id for asset in visual_assets}
        completed["metadata"] = {page.id for page in pages if page.index_admission_status == "metadata_only"}
        visual_page_ids = {asset.page_id for asset in visual_assets}
        required_by_unit = {
            page.id: (("text", "visual") if page.id in visual_page_ids else ("text",))
            for page in pages
            if page.index_admission_status == "text_indexed"
        }
        publication = IndexPublicationService().assess(pages, completed, required_by_unit=required_by_unit)
        manifest = IndexPublicationManifest(
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
            version_no=document.version_no,
            index_generation=self.settings.visual_index_generation,
            publication_token=publication_token,
            status="staging",
            coverage=publication.coverage,
            partial_coverage=publication.partial_coverage,
            required_json=json.dumps(publication.required, ensure_ascii=False),
            completed_json=json.dumps({key: sorted(value) for key, value in completed.items()}, ensure_ascii=False),
            missing_json=json.dumps(publication.missing, ensure_ascii=False),
            published_at=None,
        )
        self.publication_repository.add(manifest)
        if publish and not publication.publishable:
            raise AppException(f"索引发布单元未就绪，缺失索引: {publication.missing}")
        publish_result = self.publish_all(document, manifest=manifest) if publish else {"published": False}
        publish_result.update(
            {
                "coverage": publication.coverage,
                "partial_coverage": publication.partial_coverage,
                "missing": publication.missing,
            }
        )
        result = {
            "document_id": document.id,
            "version_no": document.version_no,
            "page_index": page_result,
            "milvus": vector_result,
            "visual": visual_result,
            "graphrag": graph_result,
            "publish": publish_result,
            "publication_token": publication_token,
        }
        logger.info("多路索引流水线完成: document_id=%s result=%s", document.id, result)
        return result

    def _build_visual_index(self, assets: list[VisualIndexAsset], publication_token: str) -> dict:
        if not assets:
            return {"skipped": True, "reason": "no_visual_assets"}
        service = VisualIndexService(
            VisualEmbeddingService(
                api_base=self.settings.visual_embedding_api_base or self.settings.model_service_api_base,
                api_key=self.settings.visual_embedding_api_key or self.settings.model_service_api_key,
                model_name=self.settings.visual_embedding_model,
                dimension=self.settings.visual_embedding_dim,
                timeout_seconds=self.settings.visual_embedding_timeout_seconds,
                index_generation=self.settings.visual_index_generation,
                distance_metric=self.settings.visual_embedding_distance_metric,
                batch_size=self.settings.visual_embedding_batch_size,
            ),
            VisualMilvusIndexer(),
        )
        return service.build_records(
            assets, self.settings.visual_index_generation, publication_token=publication_token
        )

    def _list_visual_assets(self, document: Document, pages: list[DocumentPage]) -> list[VisualIndexAsset]:
        """从已解析派生资产生成整页/区域视觉索引输入，并保留区域邻接关系。"""

        page_by_id = {page.id: page for page in pages}
        blocks = self.page_index_service.repository.list_blocks(document.id, document.version_no)
        block_by_id = {block.id: block for block in blocks}
        neighbor_by_id: dict[int, tuple[int | None, int | None]] = {}
        for index, block in enumerate(blocks):
            previous = blocks[index - 1] if index > 0 and blocks[index - 1].page_id == block.page_id else None
            following = blocks[index + 1] if index + 1 < len(blocks) and blocks[index + 1].page_id == block.page_id else None
            neighbor_by_id[block.id] = (previous.id if previous else None, following.id if following else None)
        assets = [
            asset
            for asset in self.asset_repository.list_by_document_version(document.id, document.version_no, status="ready")
            if asset.asset_type in {"page_preview", "block_image"}
        ]
        result: list[VisualIndexAsset] = []
        for asset in assets:
            page = page_by_id.get(asset.page_id)
            if page is None or not asset.storage_path:
                continue
            image_path = Path(self.settings.resolve_local_path(asset.storage_path))
            if not image_path.is_file():
                logger.warning("视觉索引资产不存在: document_id=%s asset_id=%s", document.id, asset.id)
                continue
            block = block_by_id.get(asset.block_id)
            previous_id, next_id = neighbor_by_id.get(asset.block_id, (None, None))
            result.append(
                VisualIndexAsset(
                    asset_id=asset.id,
                    asset_type=asset.asset_type,
                    image_path=image_path,
                    knowledge_base_id=document.knowledge_base_id,
                    project_id=document.project_id,
                    document_id=document.id,
                    version_no=document.version_no,
                    page_id=page.id,
                    page_no=page.page_no,
                    block_id=asset.block_id,
                    block_index=block.block_index if block else None,
                    security_level=document.security_level,
                    previous_block_id=previous_id,
                    next_block_id=next_id,
                )
            )
        return result

    def publish_all(
        self, document: Document, manifest: IndexPublicationManifest | None = None
    ) -> dict:
        """
        发布当前文档版本的 staging 索引。

        参数:
            document: 文档 ORM 对象。

        返回:
            发布结果摘要。
        """

        page_publish = self.page_index_service.publish_page_indexes(document)
        graph_publish = self.graph_index_service.publish_document_graph(document)
        if manifest is not None:
            self.publication_repository.publish(manifest)
        return {"published": True, **page_publish, **graph_publish}
