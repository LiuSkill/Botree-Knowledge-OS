"""
Index Task Repository

负责：
1. 创建和查询离线索引任务
2. 更新任务状态、进度、结果和错误
3. 为 RQ worker 与 API 层提供统一数据访问入口
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.index_task import IndexTask


class IndexTaskRepository:
    """
    索引任务仓储

    职责：
    - 管理 index_tasks 表
    - 隔离任务状态更新细节
    - 保持任务生命周期可审计
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, task: IndexTask) -> IndexTask:
        """新增索引任务。"""

        self.db.add(task)
        self.db.flush()
        return task

    def get(self, task_id: int) -> IndexTask | None:
        """按 ID 查询索引任务。"""

        return self.db.get(IndexTask, task_id)

    def list_by_document(self, document_id: int) -> list[IndexTask]:
        """查询指定文档的索引任务。"""

        stmt = select(IndexTask).where(IndexTask.document_id == document_id).order_by(IndexTask.id.desc())
        return list(self.db.scalars(stmt).all())

    def latest_task(self, document_id: int, task_type: str) -> IndexTask | None:
        """查询指定文档某类任务的最新记录。"""

        return self.db.scalar(
            select(IndexTask)
            .where(IndexTask.document_id == document_id, IndexTask.task_type == task_type)
            .order_by(IndexTask.id.desc())
        )

    def active_task(
        self,
        document_id: int,
        task_type: str,
        version_no: int | None = None,
        exclude_task_id: int | None = None,
    ) -> IndexTask | None:
        """查询指定文档仍在排队或执行中的任务。"""

        stmt = select(IndexTask).where(
            IndexTask.document_id == document_id,
            IndexTask.task_type == task_type,
            IndexTask.status.in_(("pending", "running")),
        )
        if version_no is not None:
            stmt = stmt.where(IndexTask.version_no == version_no)
        if exclude_task_id is not None:
            stmt = stmt.where(IndexTask.id != exclude_task_id)
        return self.db.scalar(stmt.order_by(IndexTask.id.desc()))

    def clear_by_document(self, document_id: int) -> int:
        """
        物理删除文档关联的索引任务。

        参数:
            document_id: 文档ID。

        返回:
            删除的任务数量。
        """

        result = self.db.execute(delete(IndexTask).where(IndexTask.document_id == document_id))
        self.db.flush()
        return int(result.rowcount or 0)
