"""
Index Service

负责：
1. 调用真实 Embedding 服务
2. 将 Chunk 向量写入 Milvus
3. 删除旧版本外部向量索引
"""

import logging

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.knowledge.indexing.milvus_indexer import MilvusIndexer
from app.repositories.document_repository import DocumentRepository
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class IndexService:
    """
    索引服务

    职责：
    - 为文档 Chunk 生成真实向量
    - 将向量写入 Milvus
    - 回填 Chunk 的 vector_id，便于版本切换时删除旧索引
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.document_repository = DocumentRepository(db)
        self.embedding_service = EmbeddingService(db)
        self.milvus_indexer = MilvusIndexer()

    def index_document(self, document_id: int, version_no: int | None = None) -> dict:
        """
        构建文档索引

        参数:
            document_id: 文档ID

        返回:
            索引结果。
        """

        chunks = self.document_repository.list_chunks(document_id, version_no=version_no)
        if not chunks:
            raise AppException("文档没有可索引的有效 Chunk")
        document = self.document_repository.get(document_id)

        vectors = self.embedding_service.embed_texts([chunk.content for chunk in chunks])
        records = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            if len(vector) != self.settings.embedding_dim:
                raise AppException(
                    f"Embedding维度不匹配：配置={self.settings.embedding_dim} 实际={len(vector)}",
                    status_code=500,
                    code=500,
                )
            vector_id = f"doc_{document_id}_chunk_{chunk.id}_v{chunk.version_no}"
            chunk.vector_id = vector_id
            records.append(
                {
                    "id": vector_id,
                    "knowledge_base_id": int(chunk.knowledge_base_id),
                    "project_id": int(chunk.project_id or 0),
                    "document_id": int(document_id),
                    "chunk_id": int(chunk.id),
                    "page_no": int(chunk.page_number or 0),
                    "version_no": int(chunk.version_no),
                    "drawing_no": str(document.drawing_no if document else ""),
                    "security_level": str(chunk.security_level),
                    "embedding": vector,
                }
            )
        result = self.milvus_indexer.upsert_chunks(records)
        self.db.flush()
        logger.info("文档真实向量索引完成: document_id=%s vectors=%s", document_id, len(records))
        return {**result, "document_id": document_id, "chunk_count": len(chunks)}

    def delete_document_index(self, document_id: int, vector_ids: list[str] | None = None) -> dict:
        """
        删除文档旧版本索引信息。

        参数:
            document_id: 文档ID。
            vector_ids: 旧 Chunk 绑定的向量 ID，后续接入 Milvus 时用于删除向量。

        返回:
            删除结果。
        """

        if not vector_ids:
            return {"document_id": document_id, "deleted_vector_count": 0, "status": "skipped"}
        return {"document_id": document_id, **self.milvus_indexer.delete_vectors(document_id, vector_ids)}
