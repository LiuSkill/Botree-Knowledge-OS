"""
Milvus Retriever

负责：
1. 调用真实 Embedding 服务生成查询向量
2. 调用真实 Milvus 执行向量检索
3. 回查数据库来源并执行权限过滤
"""

import logging

from sqlalchemy.orm import Session

from app.knowledge.indexing.milvus_indexer import MilvusIndexer
from app.models.document import Document
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.retrieval.base import BaseRetriever
from app.retrieval.retrievers.keyword_retriever import KeywordRetriever
from app.retrieval.schemas import Evidence
from app.services.embedding_service import EmbeddingService
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)


class MilvusHybridRetriever(BaseRetriever):
    """
    Milvus 混合检索器

    职责：
    - 用真实向量服务召回候选 Chunk
    - 使用数据库状态做二次校验
    - 返回可追溯 Evidence
    """

    name = "milvus"

    def __init__(self, db: Session) -> None:
        self.db = db
        self.document_repository = DocumentRepository(db)
        self.embedding_service = EmbeddingService(db)
        self.milvus_indexer = MilvusIndexer()
        self.keyword_policy = KeywordRetriever(db)

    def search(self, query: str, mode: str, project_id: int | None, user: User, limit: int = 5) -> list[Evidence]:
        """
        执行真实向量检索。

        参数:
            query: 查询文本。
            mode: 检索模式。
            project_id: 项目ID。
            user: 当前用户。
            limit: 最大返回数量。

        返回:
            通过权限过滤的证据列表。
        """

        query_vector = self.embedding_service.embed_texts([query])[0]
        hits = self.milvus_indexer.search(query_vector, limit * 3)
        evidences: list[Evidence] = []
        project_service = ProjectService(self.db)
        filter_stats = {
            "missing_or_inactive_chunk": 0,
            "document_unavailable": 0,
            "version_mismatch": 0,
            "scope_denied": 0,
            "project_access_denied": 0,
        }

        for hit in hits:
            chunk = self.document_repository.get_chunk(hit["chunk_id"])
            if not chunk or chunk.chunk_status != "active":
                filter_stats["missing_or_inactive_chunk"] += 1
                continue
            document = self.db.get(Document, chunk.document_id)
            if not document or document.review_status != "approved" or document.index_status != "indexed":
                filter_stats["document_unavailable"] += 1
                continue
            if chunk.version_no != document.version_no:
                filter_stats["version_mismatch"] += 1
                continue
            if not self.keyword_policy._scope_allowed(document.knowledge_type, document.project_id, document.knowledge_base_id, mode, project_id, user):
                filter_stats["scope_denied"] += 1
                continue
            if document.project_id is not None:
                try:
                    project_service.ensure_project_access(document.project_id, user)
                except Exception:
                    filter_stats["project_access_denied"] += 1
                    logger.exception(
                        "Milvus检索项目权限校验失败: document_id=%s project_id=%s user_id=%s",
                        document.id,
                        document.project_id,
                        getattr(user, "id", None),
                    )
                    continue
            evidences.append(
                Evidence(
                    score=float(hit["score"]),
                    source_type=self.keyword_policy._source_type(document.knowledge_type, mode),
                    knowledge_base_id=document.knowledge_base_id,
                    project_id=document.project_id,
                    document_id=document.id,
                    chunk_id=chunk.id,
                    drawing_no=document.drawing_no,
                    file_name=document.file_name,
                    page_number=chunk.page_number,
                    content=chunk.content,
                    retriever=self.name,
                )
            )
            if len(evidences) >= limit:
                break
        logger.info(
            "Milvus检索诊断: hits=%s evidences=%s filter_stats=%s query_preview=%s mode=%s project_id=%s",
            len(hits),
            len(evidences),
            filter_stats,
            query[:120],
            mode,
            project_id,
        )
        if hits and not evidences:
            logger.warning("Milvus命中已被二次校验全部过滤: filter_stats=%s", filter_stats)
        if not hits:
            logger.warning("Milvus向量召回为空: limit=%s query_preview=%s", limit * 3, query[:120])
        return evidences
