"""
Review Repository

负责：
1. 审核任务数据库访问
2. 审核日志数据库访问
3. 支持审核中心页面
"""

from collections.abc import Collection

from sqlalchemy import delete, false, func, or_, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.review import ReviewLog, ReviewTask


class ReviewRepository:
    """
    审核仓储

    职责：
    - 审核任务创建和查询
    - 审核日志创建和查询
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_tasks(self, status: str | None = None, project_id: int | None = None) -> list[ReviewTask]:
        """查询每份文档最新的审核任务，历史任务仅用于审计。"""

        latest_task_ids = (
            select(func.max(ReviewTask.id).label("task_id"))
            .group_by(ReviewTask.document_id)
            .subquery()
        )
        stmt = (
            select(ReviewTask)
            .join(latest_task_ids, latest_task_ids.c.task_id == ReviewTask.id)
            .join(Document, Document.id == ReviewTask.document_id)
            .where(Document.is_deleted.is_(False))
            .order_by(ReviewTask.id.desc())
        )
        if status:
            stmt = stmt.where(ReviewTask.review_status == status)
        if project_id is not None:
            stmt = stmt.where(Document.project_id == project_id)
        return list(self.db.scalars(stmt).all())

    def count_distinct_review_documents(
        self,
        *,
        status: str,
        project_id: int,
        document_ids: Collection[int] | None = None,
    ) -> int:
        """按真实审核任务统计项目内文档数，避免把未提交的草稿资料计入待审核。"""

        if document_ids is not None and not document_ids:
            return 0

        filters = [
            ReviewTask.review_status == status,
            Document.project_id == project_id,
            Document.is_deleted.is_(False),
        ]
        if document_ids is not None:
            filters.append(ReviewTask.document_id.in_(list(document_ids)))

        stmt = (
            select(func.count(func.distinct(ReviewTask.document_id)))
            .select_from(ReviewTask)
            .join(Document, Document.id == ReviewTask.document_id)
            .where(*filters)
        )
        return int(self.db.scalar(stmt) or 0)

    def list_tasks_page(
        self,
        status: str | None = None,
        project_id: int | None = None,
        page: int = 1,
        page_size: int = 10,
        *,
        security_levels: Collection[str] | None = None,
        include_base_documents: bool = True,
        include_project_documents: bool = True,
        accessible_project_ids: Collection[int] | None = None,
    ) -> dict[str, object]:
        """分页查询审核任务，避免审核中心一次性加载全部历史任务。"""

        safe_page = max(page, 1)
        safe_size = max(min(page_size, 100), 1)
        offset = (safe_page - 1) * safe_size
        filters = [Document.is_deleted.is_(False)]

        if security_levels is not None:
            filters.append(Document.security_level.in_(list(security_levels)))

        access_filters: list[object] = []
        if include_base_documents and project_id is None:
            access_filters.append(or_(Document.knowledge_type == "base", Document.project_id.is_(None)))
        if include_project_documents:
            if project_id is not None:
                access_filters.append(Document.project_id == project_id)
            elif accessible_project_ids:
                access_filters.append(Document.project_id.in_(list(accessible_project_ids)))
        filters.append(or_(*access_filters) if access_filters else false())

        latest_task_ids = (
            select(func.max(ReviewTask.id).label("task_id"))
            .group_by(ReviewTask.document_id)
            .subquery()
        )
        stmt = (
            select(ReviewTask)
            .join(latest_task_ids, latest_task_ids.c.task_id == ReviewTask.id)
            .join(Document, Document.id == ReviewTask.document_id)
        )
        count_stmt = (
            select(func.count(ReviewTask.id))
            .select_from(ReviewTask)
            .join(latest_task_ids, latest_task_ids.c.task_id == ReviewTask.id)
            .join(
            Document,
            Document.id == ReviewTask.document_id,
            )
        )
        if project_id is not None:
            filters.append(Document.project_id == project_id)
        if status:
            filters.append(ReviewTask.review_status == status)

        total = int(self.db.scalar(count_stmt.where(*filters)) or 0)
        items = list(
            self.db.scalars(
                stmt.where(*filters)
                .order_by(ReviewTask.id.desc())
                .offset(offset)
                .limit(safe_size)
            ).all()
        )
        return {"items": items, "total": total, "page": safe_page, "page_size": safe_size}

    def get_task(self, task_id: int) -> ReviewTask | None:
        """按 ID 查询审核任务。"""

        return self.db.scalar(
            select(ReviewTask)
            .join(Document, Document.id == ReviewTask.document_id)
            .where(ReviewTask.id == task_id, Document.is_deleted.is_(False))
        )

    def get_open_task_by_document(self, document_id: int, version_id: int | None = None) -> ReviewTask | None:
        """查询文档未完成审核任务。"""

        stmt = (
            select(ReviewTask)
            .join(Document, Document.id == ReviewTask.document_id)
            .where(
                ReviewTask.document_id == document_id,
                ReviewTask.review_status == "reviewing",
                Document.is_deleted.is_(False),
            )
        )
        if version_id is not None:
            stmt = stmt.where(ReviewTask.version_id == version_id)
        return self.db.scalar(stmt)

    def add_task(self, task: ReviewTask) -> ReviewTask:
        """新增审核任务。"""

        self.db.add(task)
        self.db.flush()
        return task

    def add_log(self, log: ReviewLog) -> ReviewLog:
        """新增审核日志。"""

        self.db.add(log)
        self.db.flush()
        return log

    def list_logs(self, document_id: int) -> list[ReviewLog]:
        """查询文档审核日志。"""

        return list(
            self.db.scalars(select(ReviewLog).where(ReviewLog.document_id == document_id).order_by(ReviewLog.id.desc())).all()
        )

    def clear_document_records(self, document_id: int) -> dict[str, int]:
        """
        物理删除文档审核任务和审核日志。

        参数:
            document_id: 文档ID。

        返回:
            删除数量摘要。
        """

        task_result = self.db.execute(delete(ReviewTask).where(ReviewTask.document_id == document_id))
        log_result = self.db.execute(delete(ReviewLog).where(ReviewLog.document_id == document_id))
        self.db.flush()
        return {
            "review_tasks": int(task_result.rowcount or 0),
            "review_logs": int(log_result.rowcount or 0),
        }
