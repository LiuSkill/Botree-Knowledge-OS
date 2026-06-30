"""
System Repository

负责：
1. 操作日志数据库访问
2. 仪表盘统计查询
3. 系统配置查询扩展
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document, DocumentChunk
from app.models.knowledge_category import KnowledgeCategory
from app.models.knowledge_base import KnowledgeBase
from app.models.operation_log import OperationLog
from app.models.project import Project
from app.models.review import ReviewTask
from app.models.user import User


class SystemRepository:
    """
    系统仓储

    职责：
    - 保存操作日志
    - 查询工作台统计数据
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def add_log(self, log: OperationLog) -> OperationLog:
        """新增操作日志。"""

        self.db.add(log)
        self.db.flush()
        return log

    def list_logs(
        self,
        keyword: str | None = None,
        result: str | None = None,
        target_type: str | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> list[OperationLog]:
        """查询操作日志列表。"""

        stmt = select(OperationLog).order_by(OperationLog.id.desc())
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                (OperationLog.username.like(like))
                | (OperationLog.action.like(like))
                | (OperationLog.target_type.like(like))
                | (OperationLog.target_id.like(like))
                | (OperationLog.detail.like(like))
            )
        if result:
            stmt = stmt.where(OperationLog.result == result)
        if target_type:
            stmt = stmt.where(OperationLog.target_type == target_type)
        if started_at:
            stmt = stmt.where(OperationLog.created_at >= started_at)
        if ended_at:
            stmt = stmt.where(OperationLog.created_at <= ended_at)
        return list(self.db.scalars(stmt).all())

    def dashboard_counts(self) -> dict[str, int]:
        """查询工作台统计数量。"""

        return {
            "project_count": int(self.db.scalar(select(func.count(Project.id))) or 0),
            "knowledge_base_count": int(self.db.scalar(select(func.count(KnowledgeBase.id))) or 0),
            "document_count": int(self.db.scalar(select(func.count(Document.id))) or 0),
            "knowledge_entry_count": int(
                self.db.scalar(select(func.count(DocumentChunk.id)).where(DocumentChunk.chunk_status == "active")) or 0
            ),
            "ai_answer_count": int(
                self.db.scalar(select(func.count(ChatMessage.id)).where(ChatMessage.role == "assistant")) or 0
            ),
            "pending_review_count": int(
                self.db.scalar(select(func.count(ReviewTask.id)).where(ReviewTask.review_status == "reviewing")) or 0
            ),
        }

    def list_recent_user_questions(self, limit: int = 4) -> list[tuple[ChatMessage, ChatSession, User]]:
        """查询最近用户提问及其会话上下文。"""

        stmt = (
            select(ChatMessage, ChatSession, User)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .join(User, User.id == func.coalesce(ChatMessage.user_id, ChatSession.user_id))
            .where(ChatMessage.role == "user")
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).all())

    def list_user_login_logs(self, user_id: int, limit: int = 2) -> list[OperationLog]:
        """查询指定用户最近登录日志。"""

        stmt = (
            select(OperationLog)
            .where(OperationLog.user_id == user_id, OperationLog.action == "登录", OperationLog.result == "success")
            .order_by(OperationLog.id.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def list_document_category_stats(self) -> list[tuple[str, int]]:
        """按真实知识分类统计文档数量。"""

        category_stmt = (
            select(KnowledgeCategory.name, func.count(Document.id))
            .join(Document, Document.category_id == KnowledgeCategory.id)
            .group_by(KnowledgeCategory.id, KnowledgeCategory.name)
            .order_by(func.count(Document.id).desc())
        )
        category_rows = [(str(name), int(count)) for name, count in self.db.execute(category_stmt).all()]
        uncategorized_count = int(
            self.db.scalar(select(func.count(Document.id)).where(Document.category_id.is_(None))) or 0
        )
        if uncategorized_count:
            category_rows.append(("未分类", uncategorized_count))
        return category_rows
