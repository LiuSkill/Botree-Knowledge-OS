"""
Project Models

负责：
1. 项目主数据建模
2. 项目成员和项目级权限隔离
3. 支撑项目知识库自动创建
"""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Project(TimestampMixin, Base):
    """
    项目表

    职责：
    - 保存企业项目基础信息
    - 作为项目知识隔离的核心边界
    - 关联项目成员、知识库和项目资料
    """

    __tablename__ = "projects"
    __table_args__ = {"comment": "项目主表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="项目名称")
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="项目编码")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="项目描述")
    client: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="客户名称")
    manager: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="项目经理")
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, comment="项目状态：active/completed/pending/archived")
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="项目进度百分比")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="创建人ID，关联users.id")

    members: Mapped[list["ProjectMember"]] = relationship("ProjectMember", back_populates="project")


class ProjectMember(TimestampMixin, Base):
    """
    项目成员表

    职责：
    - 维护用户与项目之间的授权关系
    - 控制项目资料和项目知识检索访问范围
    """

    __tablename__ = "project_members"
    __table_args__ = {"comment": "项目成员表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False, comment="所属项目ID，关联projects.id")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False, comment="用户ID，关联users.id")
    role: Mapped[str] = mapped_column(String(100), default="member", nullable=False, comment="项目角色：owner/manager/member/viewer/external")
    permission_scope: Mapped[str] = mapped_column(String(100), default="project_read", nullable=False, comment="权限范围：project_manage/project_read/authorized_only")
    external_user: Mapped[bool] = mapped_column(default=False, nullable=False, comment="是否外部用户")
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, comment="成员状态：active/disabled/expired")

    project: Mapped[Project] = relationship("Project", back_populates="members")
