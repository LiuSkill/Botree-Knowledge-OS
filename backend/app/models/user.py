"""
User and permission models.
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.security_levels import DEFAULT_SECURITY_LEVEL
from app.models.base import Base, TimestampMixin


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id"), primary_key=True, comment="用户ID，关联 users.id"),
    Column("role_id", ForeignKey("roles.id"), primary_key=True, comment="角色ID，关联 roles.id"),
    Column("created_at", DateTime, default=datetime.utcnow, nullable=False, comment="创建时间"),
    Column("updated_at", DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, comment="更新时间"),
    comment="用户角色关联表",
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id"), primary_key=True, comment="角色ID，关联 roles.id"),
    Column("permission_id", ForeignKey("permissions.id"), primary_key=True, comment="权限ID，关联 permissions.id"),
    Column("created_at", DateTime, default=datetime.utcnow, nullable=False, comment="创建时间"),
    Column("updated_at", DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, comment="更新时间"),
    comment="角色权限关联表",
)


class User(TimestampMixin, Base):
    """平台用户。"""

    __tablename__ = "users"
    __table_args__ = {"comment": "用户主表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False, comment="登录用户名")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")
    real_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="真实姓名")
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="邮箱")
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="手机号")
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="所属部门")
    status: Mapped[str] = mapped_column(String(30), default="enabled", nullable=False, comment="状态：enabled/disabled")
    avatar_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="头像 MinIO 对象 Key")
    avatar_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="头像原始文件名")
    avatar_content_type: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="头像 MIME 类型")
    avatar_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="头像更新时间")

    roles: Mapped[list["Role"]] = relationship("Role", secondary=user_roles, back_populates="users")


class Role(TimestampMixin, Base):
    """系统角色。"""

    __tablename__ = "roles"
    __table_args__ = {"comment": "角色表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="角色名称")
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="角色编码")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="角色描述")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    security_level: Mapped[str] = mapped_column(
        String(30),
        default=DEFAULT_SECURITY_LEVEL,
        nullable=False,
        comment="角色可访问的最高密级：public/internal/confidential",
    )

    users: Mapped[list[User]] = relationship("User", secondary=user_roles, back_populates="roles")
    permissions: Mapped[list["Permission"]] = relationship(
        "Permission",
        secondary=role_permissions,
        back_populates="roles",
    )


class Permission(TimestampMixin, Base):
    """权限点。"""

    __tablename__ = "permissions"
    __table_args__ = {"comment": "权限表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    module: Mapped[str] = mapped_column(String(100), nullable=False, comment="权限所属模块")
    action: Mapped[str] = mapped_column(String(100), nullable=False, comment="权限动作：view/create/update/delete/review/auth")
    code: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, comment="权限编码")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="权限说明")

    roles: Mapped[list[Role]] = relationship("Role", secondary=role_permissions, back_populates="permissions")
