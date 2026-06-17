"""
Review Models

负责：
1. 审核任务建模
2. 审核动作日志建模
3. 保证文档发布流程可审计
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ReviewTask(TimestampMixin, Base):
    """
    审核任务表

    职责：
    - 记录待审核文档
    - 保存审核人、状态和审核意见
    """

    __tablename__ = "review_tasks"
    __table_args__ = {"comment": "审核任务表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False, comment="关联文档ID，关联documents.id")
    version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"), index=True, nullable=True, comment="关联文档版本ID，关联document_versions.id")
    version_no: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="关联文档版本号")
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="审核人ID，关联users.id")
    review_status: Mapped[str] = mapped_column(String(30), default="reviewing", index=True, nullable=False, comment="审核状态：reviewing/approved/rejected")
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="审核意见")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="审核完成时间")


class ReviewLog(TimestampMixin, Base):
    """
    审核日志表

    职责：
    - 记录提交、通过、驳回等审核动作
    - 为后续合规追踪提供审计依据
    """

    __tablename__ = "review_logs"
    __table_args__ = {"comment": "审核日志表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False, comment="关联文档ID，关联documents.id")
    version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"), nullable=True, comment="关联文档版本ID，关联document_versions.id")
    version_no: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="关联文档版本号")
    action: Mapped[str] = mapped_column(String(50), nullable=False, comment="审核动作：submit/approve/reject/archive")
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="操作人ID，关联users.id")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="操作说明")
