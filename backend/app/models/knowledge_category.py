"""Knowledge category models."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security_levels import DEFAULT_SECURITY_LEVEL
from app.models.base import Base, TimestampMixin


class KnowledgeCategory(TimestampMixin, Base):
    """知识分类/项目资料目录表。

    项目目录继续复用现有 knowledge_categories，以保持上传、筛选和资料树链路兼容。
    """

    __tablename__ = "knowledge_categories"
    __table_args__ = {"comment": "知识分类表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    scope_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False, comment="分类范围：base/project")
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"),
        index=True,
        nullable=True,
        comment="所属项目ID，项目分类关联projects.id，企业分类为空",
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_categories.id"),
        index=True,
        nullable=True,
        comment="父分类ID，关联knowledge_categories.id",
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="分类名称")
    code: Mapped[str] = mapped_column(String(100), nullable=False, comment="分类/目录编码，项目目录按同一父目录唯一")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="分类说明")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值，数值越小越靠前")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    default_security_level: Mapped[str] = mapped_column(
        String(30),
        default=DEFAULT_SECURITY_LEVEL,
        nullable=False,
        comment="目录默认密级",
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否删除")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="删除时间")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="创建人ID，关联users.id")
