"""
User Service

负责：
1. 用户、角色、权限管理业务
2. 密码初始化和重置
3. 系统管理操作日志记录
"""

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.security import hash_password
from app.models.user import Role, User
from app.repositories.user_repository import RoleRepository, UserRepository
from app.schemas.role import RoleCreate, RoleUpdate
from app.schemas.user import UserCreate, UserUpdate
from app.services.system_service import SystemService


class UserService:
    """
    用户服务

    职责：
    - 处理用户增删改查
    - 管理用户角色分配
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.user_repository = UserRepository(db)
        self.role_repository = RoleRepository(db)

    def list_users(self, keyword: str | None = None) -> list[User]:
        """查询用户列表。"""

        return self.user_repository.list(keyword)

    def create_user(self, payload: UserCreate, operator: User) -> User:
        """创建用户。"""

        if self.user_repository.get_by_username(payload.username):
            raise AppException("用户名已存在")
        user = User(
            username=payload.username,
            password_hash=hash_password(payload.password),
            real_name=payload.real_name,
            email=payload.email,
            phone=payload.phone,
            department=payload.department,
            status="enabled",
        )
        user.roles = [role for role_id in payload.role_ids if (role := self.role_repository.get_by_id(role_id))]
        self.user_repository.add(user)
        SystemService(self.db).record_operation(operator, "新增用户", "user", user.id, f"新增用户 {user.username}")
        self.db.commit()
        return user

    def update_user(self, user_id: int, payload: UserUpdate, operator: User) -> User:
        """更新用户。"""

        user = self.user_repository.get_by_id(user_id)
        if not user:
            raise AppException("用户不存在", status_code=404, code=404)
        for field in ["real_name", "email", "phone", "department", "status"]:
            value = getattr(payload, field)
            if value is not None:
                setattr(user, field, value)
        if payload.role_ids is not None:
            user.roles = [role for role_id in payload.role_ids if (role := self.role_repository.get_by_id(role_id))]
        SystemService(self.db).record_operation(operator, "编辑用户", "user", user.id, f"编辑用户 {user.username}")
        self.db.commit()
        return user

    def delete_user(self, user_id: int, operator: User) -> None:
        """删除用户。"""

        user = self.user_repository.get_by_id(user_id)
        if not user:
            raise AppException("用户不存在", status_code=404, code=404)
        self.user_repository.delete(user)
        SystemService(self.db).record_operation(operator, "删除用户", "user", user_id, "删除用户")
        self.db.commit()

    def reset_password(self, user_id: int, operator: User, password: str = "Botree@123456") -> None:
        """重置密码。"""

        user = self.user_repository.get_by_id(user_id)
        if not user:
            raise AppException("用户不存在", status_code=404, code=404)
        user.password_hash = hash_password(password)
        SystemService(self.db).record_operation(operator, "重置密码", "user", user.id, f"重置用户 {user.username} 密码")
        self.db.commit()


class RoleService:
    """
    角色服务

    职责：
    - 处理角色 CRUD
    - 管理角色权限绑定
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.role_repository = RoleRepository(db)

    def list_roles(self) -> list[Role]:
        """查询角色列表。"""

        return self.role_repository.list()

    def list_permissions(self) -> list:
        """查询权限列表。"""

        return self.role_repository.list_permissions()

    def create_role(self, payload: RoleCreate, operator: User) -> Role:
        """创建角色。"""

        if self.role_repository.get_by_code(payload.code):
            raise AppException("角色编码已存在")
        role = Role(name=payload.name, code=payload.code, description=payload.description, enabled=True)
        role.permissions = [permission for permission in self.role_repository.list_permissions() if permission.id in payload.permission_ids]
        self.role_repository.add(role)
        SystemService(self.db).record_operation(operator, "新增角色", "role", role.id, f"新增角色 {role.name}")
        self.db.commit()
        return role

    def update_role(self, role_id: int, payload: RoleUpdate, operator: User) -> Role:
        """更新角色。"""

        role = self.role_repository.get_by_id(role_id)
        if not role:
            raise AppException("角色不存在", status_code=404, code=404)
        for field in ["name", "description", "enabled"]:
            value = getattr(payload, field)
            if value is not None:
                setattr(role, field, value)
        if payload.permission_ids is not None:
            role.permissions = [permission for permission in self.role_repository.list_permissions() if permission.id in payload.permission_ids]
        SystemService(self.db).record_operation(operator, "编辑角色", "role", role.id, f"编辑角色 {role.name}")
        self.db.commit()
        return role

    def delete_role(self, role_id: int, operator: User) -> None:
        """删除角色。"""

        role = self.role_repository.get_by_id(role_id)
        if not role:
            raise AppException("角色不存在", status_code=404, code=404)
        self.role_repository.delete(role)
        SystemService(self.db).record_operation(operator, "删除角色", "role", role_id, "删除角色")
        self.db.commit()
