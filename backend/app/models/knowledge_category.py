"""
Knowledge Category Models

负责：
1. 定义企业知识和项目资料的动态分类树
2. 通过 scope_type 与 project_id 隔离企业分类和项目分类
3. 为文档上传、筛选和审核后构建进度提供分类来源
"""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KnowledgeCategory(TimestampMixin, Base):
    """
    知识分类表

    职责：
    - 使用邻接表结构支持无限层级分类
    - 企业分类使用 scope_type=base 且 project_id 为空
    - 项目分类使用 scope_type=project 且 project_id 指向所属项目
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
    code: Mapped[str] = mapped_column(String(100), nullable=False, comment="分类编码，同一范围内唯一")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="分类说明")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值，数值越小越靠前")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="创建人ID，关联users.id")
