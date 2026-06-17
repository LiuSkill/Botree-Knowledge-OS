"""
Keyword Retriever

负责：
1. 基于数据库 Chunk 内容做关键词检索
2. 严格过滤未审核、未索引和无权限资料
3. 返回带来源追踪的证据
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge_base import KnowledgeBase, KnowledgeBasePermission
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.retrieval.base import BaseRetriever
from app.retrieval.query_utils import extract_query_terms, score_text_relevance
from app.retrieval.schemas import Evidence
from app.services.project_service import ProjectService


class KeywordRetriever(BaseRetriever):
    """
    关键词检索器

    职责：
    - 对 Chunk 文本计算简单相关性分数
    - 在未启用向量库时提供真实数据库文本检索
    """

    name = "keyword"

    def __init__(self, db: Session) -> None:
        self.db = db

    def search(self, query: str, mode: str, project_id: int | None, user: User, limit: int = 5) -> list[Evidence]:
        """执行关键词检索。"""

        terms = self._terms(query)
        evidences: list[Evidence] = []
        project_service = ProjectService(self.db)

        for chunk, document in DocumentRepository(self.db).searchable_chunks():
            if not self._scope_allowed(document.knowledge_type, document.project_id, document.knowledge_base_id, mode, project_id, user):
                continue
            if document.project_id is not None:
                project_service.ensure_project_access(document.project_id, user)

            score = self._score(chunk.content, query, terms)
            if score <= 0:
                continue
            evidences.append(
                Evidence(
                    score=score,
                    source_type=self._source_type(document.knowledge_type, mode),
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
        return sorted(evidences, key=lambda item: item.score, reverse=True)[:limit]

    def _scope_allowed(
        self,
        knowledge_type: str,
        doc_project_id: int | None,
        knowledge_base_id: int,
        mode: str,
        project_id: int | None,
        user: User,
    ) -> bool:
        """判断 Chunk 是否在当前检索范围内。"""

        effective_mode = "hybrid" if mode == "auto" and project_id is not None else ("base_only" if mode == "auto" else mode)
        if effective_mode == "project_chat":
            return knowledge_type == "project" and doc_project_id == project_id
        if effective_mode == "base_chat":
            if knowledge_type == "base":
                return self._base_knowledge_allowed(knowledge_base_id, None, user, strict_external=False)
            return False
        if effective_mode == "base_only":
            return knowledge_type == "base" and self._base_knowledge_allowed(knowledge_base_id, project_id, user, strict_external=False)
        if effective_mode == "project_only":
            return knowledge_type == "project" and doc_project_id == project_id
        if effective_mode == "hybrid":
            return (
                knowledge_type == "base" and self._base_knowledge_allowed(knowledge_base_id, project_id, user, strict_external=False)
            ) or (knowledge_type == "project" and doc_project_id == project_id)
        return False

    def _source_type(self, knowledge_type: str, mode: str) -> str:
        """
        计算引用来源类型

        参数:
            knowledge_type: 文档知识类型
            mode: 实际检索模式

        返回:
            前端展示使用的来源类型。
        """

        if mode == "project_chat" and knowledge_type == "base":
            return "authorized_internal"
        return knowledge_type

    def _base_knowledge_allowed(
        self,
        knowledge_base_id: int,
        project_id: int | None,
        user: User,
        strict_external: bool,
    ) -> bool:
        """
        判断基础知识库是否可被当前问答引用

        说明:
            - 普通内部用户可以访问 internal 基础知识。
            - project_chat 支持 project/user/role 三类授权记录。
            - 外部用户只能访问显式授权给项目、用户或外部主体的基础知识。
        """

        if self._is_admin(user):
            return True
        knowledge_base = self.db.get(KnowledgeBase, knowledge_base_id)
        if not knowledge_base or not knowledge_base.enabled:
            return False
        external_user = self._is_external_user(user)
        if knowledge_base.visibility == "internal" and not (strict_external and external_user):
            return True
        return self._has_explicit_base_permission(knowledge_base_id, project_id, user)

    def _has_explicit_base_permission(self, knowledge_base_id: int, project_id: int | None, user: User) -> bool:
        """查询用户、角色或项目是否具备基础知识库授权。"""

        now = datetime.utcnow()
        role_ids = [role.id for role in user.roles]
        stmt = select(KnowledgeBasePermission).where(
            KnowledgeBasePermission.knowledge_base_id == knowledge_base_id,
            KnowledgeBasePermission.permission.in_(["read", "manage"]),
        )
        permissions = list(self.db.scalars(stmt).all())
        for permission in permissions:
            if permission.expires_at and permission.expires_at < now:
                continue
            if permission.subject_type == "user" and permission.subject_id == user.id:
                return True
            if permission.subject_type == "role" and permission.subject_id in role_ids:
                return True
            if permission.subject_type == "project" and project_id is not None and permission.subject_id == project_id:
                return True
            if permission.subject_type == "external_user" and permission.external_subject == user.username:
                return True
        return False

    def _is_admin(self, user: User) -> bool:
        """判断是否平台管理员。"""

        return any(role.code == "admin" for role in user.roles)

    def _is_external_user(self, user: User) -> bool:
        """判断是否外部用户。"""

        return any(role.code == "external" or "外部" in role.name for role in user.roles)

    def _terms(self, query: str) -> list[str]:
        """抽取中英文检索词。"""

        return extract_query_terms(query)

    def _score(self, content: str, query: str, terms: list[str]) -> float:
        """计算简单相关性得分。"""

        return score_text_relevance(content, query, terms)
