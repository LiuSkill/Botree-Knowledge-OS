"""Project models."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.security_levels import DEFAULT_SECURITY_LEVEL
from app.models.base import Base, TimestampMixin


class Project(TimestampMixin, Base):
    """Project main record."""

    __tablename__ = "projects"
    __table_args__ = {"comment": "项目主表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="项目名称（兼容旧字段）")
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="项目编号（兼容旧字段）")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="项目简介")
    client: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="客户名称（兼容旧字段）")
    manager: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="项目负责人（兼容旧字段）")
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, comment="旧项目状态")
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="项目进度百分比")

    project_short_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="项目简称")
    project_english_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="项目英文名称")
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="客户名称")
    project_type: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="项目类型")
    project_status: Mapped[str] = mapped_column(String(30), default="进行中", nullable=False, comment="项目状态：待启动/进行中/已完成/已暂停")
    project_stage: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="项目阶段")
    raw_material_type: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="原料类型")
    capacity: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="处理能力")
    process_route: Mapped[str | None] = mapped_column(Text, nullable=True, comment="工艺路线")
    main_products: Mapped[str | None] = mapped_column(Text, nullable=True, comment="主要产品")
    scope_description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="项目范围")
    deliverables: Mapped[str | None] = mapped_column(Text, nullable=True, comment="交付成果")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="项目负责人ID")
    owner_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="项目负责人姓名")
    department_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="所属部门ID")

    security_level: Mapped[str] = mapped_column(
        String(30),
        default=DEFAULT_SECURITY_LEVEL,
        nullable=False,
        comment="项目密级：public/internal/confidential",
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="创建人ID")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否删除")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="删除时间")

    members: Mapped[list["ProjectMember"]] = relationship("ProjectMember", back_populates="project")


class ProjectMember(TimestampMixin, Base):
    """Project member record."""

    __tablename__ = "project_members"
    __table_args__ = {"comment": "项目成员表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False, comment="所属项目ID")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False, comment="用户ID")
    role: Mapped[str] = mapped_column(String(100), default="member", nullable=False, comment="项目角色：owner/manager/member/viewer/external")
    permission_scope: Mapped[str] = mapped_column(String(100), default="project_read", nullable=False, comment="权限范围：project_manage/project_read/authorized_only")
    external_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否外部用户")
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, comment="成员状态：active/disabled/expired")

    project: Mapped[Project] = relationship("Project", back_populates="members")
