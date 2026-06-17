"""
Index Task Model

负责：
1. 记录离线索引任务生命周期
2. 保存 RQ job id、进度、失败原因和执行结果
3. 支撑文档索引构建、重试、发布和审计
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class IndexTask(TimestampMixin, Base):
    """
    离线索引任务表

    职责：
    - 记录 MinerU、PageIndex、Milvus、ripgrep、GraphRAG、发布等任务
    - 为前端展示任务进度提供稳定数据源
    - 为后台 worker 失败重试提供状态依据
    """

    __tablename__ = "index_tasks"
    __table_args__ = (
        Index("idx_index_tasks_document_id", "document_id"),
        Index("idx_index_tasks_version_id", "version_id"),
        Index("idx_index_tasks_version_no", "version_no"),
        Index("idx_index_tasks_task_type", "task_type"),
        Index("idx_index_tasks_status", "status"),
        {"comment": "离线索引任务表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, comment="关联文档ID，关联documents.id")
    version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"), nullable=True, comment="关联文档版本ID，关联document_versions.id")
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="任务对应文档版本号")
    task_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="任务类型：mineru_parse/pageindex_build/milvus_build/ripgrep_build/graphrag_build/index_publish/full_build")
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False, comment="任务状态：pending/running/success/failed/canceled")
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="任务进度，0-100")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败错误信息")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="任务执行结果JSON")
    rq_job_id: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="RQ任务ID")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="任务开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="任务完成时间")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="创建人ID，关联users.id")
