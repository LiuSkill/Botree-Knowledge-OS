"""
Retrieval Service

负责：
1. 提供知识检索业务入口
2. 将内部 Evidence 转为 API 引用来源结构
3. 保证检索遵守权限和审核索引规则
"""

from sqlalchemy.orm import Session

from app.models.user import User
from app.retrieval.router import RetrievalRouter
from app.retrieval.schemas import Evidence


class RetrievalService:
    """
    检索服务

    职责：
    - 调用 RetrievalRouter
    - 整理前端可展示的引用来源
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def search(
        self,
        query: str,
        mode: str,
        project_id: int | None,
        user: User,
        limit: int = 5,
        chat_type: str | None = None,
        execution_mode: str = "planner",
    ) -> dict:
        """
        执行检索

        参数:
            query: 查询文本
            mode: 检索模式
            project_id: 项目ID
            user: 当前用户
            limit: 返回数量
            chat_type: 问答类型，project_chat/base_chat

        返回:
            检索结果。
        """

        result = RetrievalRouter(self.db).search(query, mode, project_id, user, limit, chat_type, execution_mode)
        result["citations"] = [self.evidence_to_citation(evidence) for evidence in result.pop("evidences")]
        return result

    def evidence_to_citation(self, evidence: Evidence) -> dict:
        """
        Evidence 转引用来源

        参数:
            evidence: 内部证据对象

        返回:
            引用来源字典。
        """

        return {
            "source_type": evidence.source_type,
            "knowledge_base_id": evidence.knowledge_base_id,
            "project_id": evidence.project_id,
            "document_id": evidence.document_id,
            "chunk_id": evidence.chunk_id,
            "drawing_no": evidence.drawing_no,
            "file_name": evidence.file_name,
            "page_number": evidence.page_number,
            "content": evidence.content,
            "retriever": evidence.retriever,
            "score": evidence.score,
            "metadata": evidence.metadata,
        }
