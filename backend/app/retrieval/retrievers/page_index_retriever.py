"""
PageIndex Retriever

负责：
1. 基于已发布 PageIndex 执行长文档页级定位
2. 回查 MySQL 文档、Chunk 和权限状态
3. 返回带 page_no、drawing_no、chunk_id 的统一 Evidence
"""

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.repositories.page_index_repository import PageIndexRepository
from app.retrieval.base import BaseRetriever
from app.retrieval.retrievers.keyword_retriever import KeywordRetriever
from app.retrieval.schemas import Evidence
from app.services.project_document_policy_service import ProjectDocumentPolicyService
from app.services.project_service import ProjectService


class PageIndexRetriever(BaseRetriever):
    """
    PageIndex 检索器

    职责：
    - 对页级索引文本做轻量关键词评分
    - 将页级命中映射回 Chunk citation
    - 作为长文档内部定位优先召回通道
    """

    name = "page_index"

    def __init__(self, db: Session) -> None:
        self.db = db
        self.page_repository = PageIndexRepository(db)
        self.document_repository = DocumentRepository(db)
        self.keyword_policy = KeywordRetriever(db)

    def search(self, query: str, mode: str, project_id: int | None, user: User, limit: int = 5) -> list[Evidence]:
        """执行 PageIndex 检索。"""

        terms = self.keyword_policy._terms(query)
        evidences: list[Evidence] = []
        project_service = ProjectService(self.db)
        project_document_policy = ProjectDocumentPolicyService(self.db)
        allowed_levels = set(self.keyword_policy._allowed_security_levels(user))
        for page_index in self.page_repository.list_published_indexes(list(allowed_levels)):
            if page_index.chunk_id is None:
                continue
            document = self.db.get(Document, page_index.document_id)
            if not document or document.index_status != "indexed":
                continue
            if document.project_id is None and document.review_status != "approved":
                continue
            if document.version_no != page_index.version_no:
                continue
            if document.security_level not in allowed_levels or page_index.security_level not in allowed_levels:
                continue
            if not self.keyword_policy._scope_allowed(document.knowledge_type, document.project_id, document.knowledge_base_id, mode, project_id, user):
                continue
            if document.project_id is not None:
                if project_document_policy.project_chat_document_reject_reason(
                    document,
                    user=user,
                    project_id=project_id,
                    require_chat_permission=mode == "project_chat",
                ):
                    continue
                try:
                    project_service.ensure_project_access(document.project_id, user)
                except Exception:
                    continue
            chunk = self.document_repository.get_chunk(page_index.chunk_id)
            if not chunk or chunk.chunk_status != "active":
                continue
            if document.project_id is not None and project_document_policy.project_chat_chunk_reject_reason(
                chunk,
                document,
                user=user,
                project_id=project_id,
            ):
                continue
            if chunk.security_level not in allowed_levels:
                continue
            page_score = self.keyword_policy._score(page_index.index_text, query, terms)
            chunk_score = self.keyword_policy._score(chunk.content, query, terms)
            if page_score <= 0 and chunk_score <= 0:
                continue
            # 同一页可能拆成多个 chunk，页级命中负责召回，chunk 级命中负责把真正含答案的片段排到前面。
            score = page_score + chunk_score * 0.6
            evidences.append(
                Evidence(
                    score=score + 1.0,
                    source_type=self.keyword_policy._source_type(document.knowledge_type, mode),
                    knowledge_base_id=document.knowledge_base_id,
                    project_id=document.project_id,
                    document_id=document.id,
                    chunk_id=chunk.id,
                    drawing_no=page_index.drawing_no or document.drawing_no,
                    file_name=document.file_name,
                    page_number=page_index.page_no,
                    content=chunk.content,
                    retriever=self.name,
                    metadata=self.keyword_policy._evidence_metadata(
                        document,
                        chunk,
                        {
                            "page_index_id": page_index.id,
                            "page_score": round(page_score, 4),
                            "chunk_score": round(chunk_score, 4),
                            "page_index_security_level": page_index.security_level,
                        },
                    ),
                )
            )
        return sorted(evidences, key=lambda item: item.score, reverse=True)[:limit]
