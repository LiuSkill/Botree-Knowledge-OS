"""
System Repository

负责：
1. 操作日志数据库访问
2. 仪表盘统计查询
3. 系统配置查询扩展
"""

from datetime import date, datetime, timedelta

from sqlalchemy import and_, case, false, func, or_, select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document, DocumentChunk
from app.models.knowledge_base import KnowledgeBase
from app.models.operation_log import OperationLog
from app.models.project import Project
from app.models.review import ReviewTask


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

    def count_accessible_document_chunks(
        self,
        *,
        security_levels: list[str],
        include_base_documents: bool,
        include_project_documents: bool,
        accessible_project_ids: list[int],
    ) -> int:
        """统计当前用户可访问且有效的知识条目。"""

        access_filters: list[object] = []
        if include_base_documents:
            access_filters.append(or_(Document.knowledge_type == "base", Document.project_id.is_(None)))
        if include_project_documents and accessible_project_ids:
            access_filters.append(Document.project_id.in_(accessible_project_ids))
        stmt = (
            select(func.count(DocumentChunk.id))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.chunk_status == "active",
                Document.is_deleted.is_(False),
                Document.review_status == "approved",
                Document.security_level.in_(security_levels),
                or_(*access_filters) if access_filters else false(),
            )
        )
        return int(self.db.scalar(stmt) or 0)

    def count_accessible_ai_answers(
        self,
        *,
        user_id: int | None,
        include_enterprise: bool,
        include_project: bool,
        accessible_project_ids: list[int],
    ) -> int:
        """沿用顶部累计口径，统计当前用户范围内的助手回答消息。"""

        type_filters: list[object] = []
        if include_enterprise:
            type_filters.append(ChatSession.chat_type == "base_chat")
        if include_project and accessible_project_ids:
            type_filters.append(
                and_(ChatSession.chat_type == "project_chat", ChatSession.project_id.in_(accessible_project_ids))
            )
        filters: list[object] = [
            ChatMessage.role == "assistant",
            or_(*type_filters) if type_filters else false(),
        ]
        if user_id is not None:
            filters.append(ChatSession.user_id == user_id)
        stmt = select(func.count(ChatMessage.id)).join(ChatSession, ChatSession.id == ChatMessage.session_id).where(*filters)
        return int(self.db.scalar(stmt) or 0)

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

    def list_knowledge_asset_distribution(
        self,
        *,
        security_levels: list[str],
        include_base_documents: bool,
        include_project_documents: bool,
        accessible_project_ids: list[int],
    ) -> list[tuple[int | None, str | None, int]]:
        """按企业公共知识和可访问项目一次聚合有效文档数量。"""

        access_filters: list[object] = []
        if include_base_documents:
            access_filters.append(or_(Document.knowledge_type == "base", Document.project_id.is_(None)))
        if include_project_documents and accessible_project_ids:
            access_filters.append(Document.project_id.in_(accessible_project_ids))
        scope_project_id = case(
            (or_(Document.knowledge_type == "base", Document.project_id.is_(None)), None),
            else_=Document.project_id,
        )
        stmt = (
            select(scope_project_id.label("scope_project_id"), Project.name, func.count(Document.id))
            .outerjoin(Project, Project.id == scope_project_id)
            .where(
                Document.is_deleted.is_(False),
                Document.review_status == "approved",
                Document.security_level.in_(security_levels),
                or_(*access_filters) if access_filters else false(),
            )
            .group_by(scope_project_id, Project.name)
        )
        return [
            (int(project_id) if project_id is not None else None, str(project_name) if project_name else None, int(count))
            for project_id, project_name, count in self.db.execute(stmt).all()
        ]

    def list_qa_trend_counts(
        self,
        *,
        started_at: datetime,
        ended_at: datetime,
        timezone_offset: timedelta,
        user_id: int | None,
        include_enterprise: bool,
        include_project: bool,
        accessible_project_ids: list[int],
    ) -> list[tuple[date, str, int]]:
        """按业务日期和问答类型聚合正式用户问题。"""

        offset_seconds = int(timezone_offset.total_seconds())
        dialect_name = self.db.bind.dialect.name if self.db.bind is not None else ""
        if dialect_name == "sqlite":
            modifier = f"{offset_seconds:+d} seconds"
            business_date = func.date(func.datetime(ChatMessage.created_at, modifier))
        elif dialect_name in {"mysql", "mariadb"}:
            hours, remainder = divmod(abs(offset_seconds), 3600)
            minutes = remainder // 60
            sign = "-" if offset_seconds < 0 else ""
            business_date = func.date(func.addtime(ChatMessage.created_at, f"{sign}{hours:02d}:{minutes:02d}:00"))
        else:
            business_date = func.date(ChatMessage.created_at + timezone_offset)

        type_filters: list[object] = []
        if include_enterprise:
            type_filters.append(ChatSession.chat_type == "base_chat")
        if include_project and accessible_project_ids:
            type_filters.append(
                and_(ChatSession.chat_type == "project_chat", ChatSession.project_id.in_(accessible_project_ids))
            )

        filters: list[object] = [
            ChatMessage.role == "user",
            ChatMessage.created_at >= started_at,
            ChatMessage.created_at < ended_at,
            or_(*type_filters) if type_filters else false(),
        ]
        if user_id is not None:
            filters.append(func.coalesce(ChatMessage.user_id, ChatSession.user_id) == user_id)
        stmt = (
            select(business_date.label("business_date"), ChatSession.chat_type, func.count(ChatMessage.id))
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(*filters)
            .group_by(business_date, ChatSession.chat_type)
            .order_by(business_date.asc())
        )
        return [
            (raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date)), str(chat_type), int(count))
            for raw_date, chat_type, count in self.db.execute(stmt).all()
        ]

    def list_user_login_logs(self, user_id: int, limit: int = 2) -> list[OperationLog]:
        """查询指定用户最近登录日志。"""

        stmt = (
            select(OperationLog)
            .where(OperationLog.user_id == user_id, OperationLog.action == "登录", OperationLog.result == "success")
            .order_by(OperationLog.id.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())
