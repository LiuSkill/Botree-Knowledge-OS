"""
Knowledge Base Models

负责：
1. 基础知识库和项目知识库建模
2. 记录知识库授权策略
3. 为后续外部用户授权预留字段
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KnowledgeBase(TimestampMixin, Base):
    """
    知识库表

    职责：
    - 区分基础知识和项目知识
    - 保存项目知识库与 project_id 的绑定关系
    - 提供知识检索范围的基础约束
    """

    __tablename__ = "knowledge_bases"
    __table_args__ = {"comment": "知识库表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="知识库名称")
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="知识库编码")
    type: Mapped[str] = mapped_column(String(30), index=True, nullable=False, comment="知识库类型：base/project")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True, nullable=True, comment="所属项目ID，base为空，project关联projects.id")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="知识库描述")
    visibility: Mapped[str] = mapped_column(String(30), default="internal", nullable=False, comment="可见性：internal/authorized/private")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="创建人ID，关联users.id")


class KnowledgeBasePermission(TimestampMixin, Base):
    """
    知识库授权表

    职责：
    - 管理用户、角色、项目、外部用户对知识库的访问授权
    - MVP 阶段用于展示授权关系并预留外部授权能力
    """

    __tablename__ = "knowledge_base_permissions"
    __table_args__ = {"comment": "知识库授权表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True, nullable=False, comment="知识库ID，关联knowledge_bases.id")
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False, comment="授权主体类型：user/role/project/external_user")
    subject_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="授权主体ID，项目授权关联projects.id，外部用户可为空")
    external_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="外部授权主体标识")
    permission: Mapped[str] = mapped_column(String(50), default="read", nullable=False, comment="授权权限：read/manage")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="授权过期时间")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="创建人ID，关联users.id")
