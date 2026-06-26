"""
Knowledge base models.
"""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KnowledgeBase(TimestampMixin, Base):
    """Knowledge base container."""

    __tablename__ = "knowledge_bases"
    __table_args__ = {"comment": "知识库表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="知识库名称")
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="知识库编码")
    type: Mapped[str] = mapped_column(String(30), index=True, nullable=False, comment="知识库类型：base/project")
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"),
        index=True,
        nullable=True,
        comment="所属项目ID，基础知识库为空，项目知识库关联 projects.id",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="知识库描述")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        comment="创建人ID，关联 users.id",
    )
