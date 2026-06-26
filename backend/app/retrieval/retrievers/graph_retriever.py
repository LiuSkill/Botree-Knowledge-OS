"""
GraphRAG Retriever

负责：
1. 基于 MySQL 图谱实体和关系执行第一阶段关系检索
2. 将关系证据映射回文档 Chunk 来源
3. 与 PageIndex、Milvus、ripgrep 统一返回 Evidence
"""

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.retrieval.base import BaseRetriever
from app.retrieval.retrievers.keyword_retriever import KeywordRetriever
from app.retrieval.schemas import Evidence
from app.services.project_service import ProjectService


class GraphRAGRetriever(BaseRetriever):
    """
    GraphRAG 检索器

    职责：
    - 从问题中抽取关键词查询实体
    - 扩展实体邻接关系
    - 返回可追溯到 Chunk 的关系证据
    """

    name = "graphrag"

    def __init__(self, db: Session) -> None:
        self.db = db
        self.graph_repository = GraphRepository(db)
        self.document_repository = DocumentRepository(db)
        self.keyword_policy = KeywordRetriever(db)

    def search(self, query: str, mode: str, project_id: int | None, user: User, limit: int = 5) -> list[Evidence]:
        """执行图谱关系检索。"""

        terms = self.keyword_policy._terms(query)
        entities = self.graph_repository.search_entities(terms, limit=limit * 3)
        relations = self.graph_repository.relations_for_entities([entity.id for entity in entities], limit=limit * 3)
        evidences: list[Evidence] = []
        project_service = ProjectService(self.db)
        allowed_levels = set(self.keyword_policy._allowed_security_levels(user))
        for relation in relations:
            if relation.chunk_id is None or relation.document_id is None:
                continue
            document = self.db.get(Document, relation.document_id)
            if not document or document.review_status != "approved" or document.index_status != "indexed":
                continue
            if document.version_no != relation.version_no:
                continue
            if document.security_level not in allowed_levels:
                continue
            if not self.keyword_policy._scope_allowed(document.knowledge_type, document.project_id, document.knowledge_base_id, mode, project_id, user):
                continue
            if document.project_id is not None:
                try:
                    project_service.ensure_project_access(document.project_id, user)
                except Exception:
                    continue
            chunk = self.document_repository.get_chunk(relation.chunk_id)
            if not chunk or chunk.chunk_status != "active":
                continue
            if chunk.security_level not in allowed_levels:
                continue
            source = self.graph_repository.get_entity(relation.source_entity_id)
            target = self.graph_repository.get_entity(relation.target_entity_id)
            relation_text = self._relation_text(source.entity_name if source else "", relation.relation_type, target.entity_name if target else "")
            evidences.append(
                Evidence(
                    score=7.0,
                    source_type=self.keyword_policy._source_type(document.knowledge_type, mode),
                    knowledge_base_id=document.knowledge_base_id,
                    project_id=document.project_id,
                    document_id=document.id,
                    chunk_id=chunk.id,
                    drawing_no=relation.drawing_no or document.drawing_no,
                    file_name=document.file_name,
                    page_number=relation.page_number or chunk.page_number,
                    content=f"{relation_text}\n\n{chunk.content}",
                    retriever=self.name,
                    metadata=self.keyword_policy._evidence_metadata(
                        document,
                        chunk,
                        {"relation_id": relation.id, "relation_type": relation.relation_type},
                    ),
                )
            )
            if len(evidences) >= limit:
                break
        return evidences

    def _relation_text(self, source_name: str, relation_type: str, target_name: str) -> str:
        """构建关系证据文本。"""

        if source_name and target_name:
            return f"GraphRAG关系：{source_name} --{relation_type}--> {target_name}"
        return f"GraphRAG关系：{relation_type}"
