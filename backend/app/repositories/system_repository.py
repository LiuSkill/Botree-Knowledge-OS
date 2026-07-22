"""
System Repository

负责：
1. 操作日志数据库访问
2. 仪表盘统计查询
3. 系统配置查询扩展
"""

from datetime import datetime

from sqlalchemy import case, false, func, or_, select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document, DocumentChunk
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

    def list_document_type_distribution(
        self,
        *,
        security_levels: list[str],
        include_base_documents: bool,
        include_project_documents: bool,
        accessible_project_ids: list[int],
    ) -> list[tuple[str, int]]:
        """按首页可访问文档口径一次聚合文件类型分布。"""

        normalized_type = func.lower(func.trim(func.replace(Document.file_type, ".", "")))
        type_group = case(
            (normalized_type == "pdf", "pdf"),
            (normalized_type.in_(("doc", "docx")), "word"),
            (normalized_type.in_(("xls", "xlsx", "xlsm", "csv")), "excel"),
            (normalized_type.in_(("ppt", "pptx")), "powerpoint"),
            (normalized_type.in_(("jpg", "jpeg", "png", "webp", "bmp", "gif", "tif", "tiff")), "image"),
            else_="other",
        )
        access_filters: list[object] = []
        if include_base_documents:
            access_filters.append(or_(Document.knowledge_type == "base", Document.project_id.is_(None)))
        if include_project_documents and accessible_project_ids:
            access_filters.append(Document.project_id.in_(accessible_project_ids))
        stmt = (
            select(type_group.label("type"), func.count(Document.id))
            .where(
                Document.is_deleted.is_(False),
                Document.review_status == "approved",
                Document.security_level.in_(security_levels),
                or_(*access_filters) if access_filters else false(),
            )
            .group_by(type_group)
        )
        return [(str(type_name), int(count)) for type_name, count in self.db.execute(stmt).all()]

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
