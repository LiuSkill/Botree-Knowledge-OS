"""
Index Pipeline Service

负责：
1. 编排 PageIndex、Milvus、ripgrep 文本镜像和 GraphRAG 多路索引
2. 保持旧同步 build-index 接口和新 RQ 异步任务复用同一套逻辑
3. 在所有索引构建成功后统一发布 staging 索引
"""

import logging

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.knowledge.indexing.index_service import IndexService
from app.models.document import Document
from app.repositories.document_repository import DocumentRepository
from app.services.graph_index_service import GraphIndexService
from app.services.page_index_service import PageIndexService

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
        if not chunks:
            raise AppException("文档尚未生成 Chunk，无法构建多路索引")
        if not pages:
            raise AppException("文档尚未生成 PageIndex 页级模型，无法构建多路索引")

        page_result = self.page_index_service.build_page_indexes(document)
        if self.settings.milvus_enabled:
            vector_result = self.vector_index_service.index_document(document.id, version_no=document.version_no)
        else:
            vector_result = {"skipped": True, "reason": "Milvus未启用，跳过向量索引构建"}
            logger.info("Milvus未启用，跳过向量索引构建: document_id=%s", document.id)
        graph_result = self.graph_index_service.build_document_graph(document)
        publish_result = self.publish_all(document) if publish else {"published": False}
        result = {
            "document_id": document.id,
            "version_no": document.version_no,
            "page_index": page_result,
            "milvus": vector_result,
            "graphrag": graph_result,
            "publish": publish_result,
        }
        logger.info("多路索引流水线完成: document_id=%s result=%s", document.id, result)
        return result

    def publish_all(self, document: Document) -> dict:
        """
        发布当前文档版本的 staging 索引。

        参数:
            document: 文档 ORM 对象。

        返回:
            发布结果摘要。
        """

        page_publish = self.page_index_service.publish_page_indexes(document)
        graph_publish = self.graph_index_service.publish_document_graph(document)
        return {"published": True, **page_publish, **graph_publish}
