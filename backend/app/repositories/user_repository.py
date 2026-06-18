"""
User Repository

负责：
1. 用户、角色、权限数据库访问
2. 支持系统管理和认证服务
3. 保持上层业务不直接编写 ORM 查询
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.user import Permission, Role, User


class UserRepository:
    """
    用户仓储

    职责：
    - 查询和保存用户
    - 加载用户角色
    - 提供用户名唯一性查询
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, keyword: str | None = None, status: str | None = None, role_id: int | None = None) -> list[User]:
        """查询用户列表。"""

        stmt = select(User).options(selectinload(User.roles).selectinload(Role.permissions)).order_by(User.id.desc())
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                (User.username.like(like))
                | (User.real_name.like(like))
                | (User.email.like(like))
                | (User.department.like(like))
            )
        if status:
            stmt = stmt.where(User.status == status)
        if role_id:
            stmt = stmt.where(User.roles.any(Role.id == role_id))
        return list(self.db.scalars(stmt).all())

    def get_by_id(self, user_id: int) -> User | None:
        """按 ID 查询用户。"""

        return self.db.scalar(select(User).options(selectinload(User.roles).selectinload(Role.permissions)).where(User.id == user_id))

    def get_by_username(self, username: str) -> User | None:
        """按用户名查询用户。"""

        return self.db.scalar(select(User).options(selectinload(User.roles).selectinload(Role.permissions)).where(User.username == username))

    def add(self, user: User) -> User:
        """新增用户。"""

        self.db.add(user)
        self.db.flush()
        return user

    def delete(self, user: User) -> None:
        """删除用户。"""

        self.db.delete(user)
        self.db.flush()


class RoleRepository:
    """
    角色仓储

    职责：
    - 管理角色和权限关系
    - 支持权限矩阵展示
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, keyword: str | None = None, enabled: bool | None = None) -> list[Role]:
        """查询角色列表。"""

        stmt = select(Role).options(selectinload(Role.permissions)).order_by(Role.id)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where((Role.name.like(like)) | (Role.code.like(like)) | (Role.description.like(like)))
        if enabled is not None:
            stmt = stmt.where(Role.enabled.is_(enabled))
        return list(self.db.scalars(stmt).all())

    def get_by_id(self, role_id: int) -> Role | None:
        """按 ID 查询角色。"""

        return self.db.scalar(select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id))

    def get_by_code(self, code: str) -> Role | None:
        """按编码查询角色。"""

        return self.db.scalar(select(Role).where(Role.code == code))

    def list_permissions(self) -> list[Permission]:
        """查询全部权限点。"""

        return list(self.db.scalars(select(Permission).order_by(Permission.module, Permission.action)).all())

    def add(self, role: Role) -> Role:
        """新增角色。"""

        self.db.add(role)
        self.db.flush()
        return role

    def delete(self, role: Role) -> None:
        """删除角色。"""

        self.db.delete(role)
        self.db.flush()
