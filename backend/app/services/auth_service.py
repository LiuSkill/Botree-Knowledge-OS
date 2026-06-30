"""
Auth Service

负责：
1. 用户登录校验
2. JWT Token 生成
3. 登录日志记录
"""

import logging

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.rbac import filter_bound_action_codes, menu_permission_codes, sync_menu_action_permission_codes
from app.core.security import create_access_token, verify_password
from app.core.security_levels import user_max_security_level
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.system_service import SystemService
from app.utils.user_avatar import avatar_url_for_user

logger = logging.getLogger(__name__)

MENU_PERMISSION_CODES = menu_permission_codes()


class AuthService:
    """
    认证服务

    职责：
    - 校验用户名密码
    - 返回当前用户信息和访问令牌
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.user_repository = UserRepository(db)

    def login(self, username: str, password: str, ip_address: str | None = None) -> dict:
        """
        用户登录

        参数:
            username: 用户名
            password: 密码
            ip_address: 登录 IP

        返回:
            Token 和用户信息。
        """

        user = self.user_repository.get_by_username(username)
        if not user or not verify_password(password, user.password_hash):
            logger.warning("用户登录失败: %s", username)
            raise AppException("用户名或密码错误", status_code=401, code=401)
        if user.status != "enabled":
            raise AppException("用户已被禁用", status_code=403, code=403)

        token = create_access_token(str(user.id), {"username": user.username})
        SystemService(self.db).record_operation(user, "登录", "auth", user.id, "用户登录系统", ip_address=ip_address)
        self.db.commit()
        logger.info("用户登录成功: %s", username)
        return {"access_token": token, "token_type": "bearer", "user": self.to_current_user(user)}

    def to_current_user(self, user: User) -> dict:
        """
        转换当前用户响应

        参数:
            user: 用户 ORM 对象

        返回:
            前端使用的当前用户字典。
        """

        permission_codes = sync_menu_action_permission_codes(self._user_permission_codes(user))
        return {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "email": user.email,
            "phone": user.phone,
            "department": user.department,
            "department_id": user.department_id,
            "department_name": user.department_name,
            "status": user.status,
            "avatar_url": avatar_url_for_user(user),
            "avatar_updated_at": user.avatar_updated_at.isoformat() if user.avatar_updated_at else None,
            "roles": [
                {
                    "id": role.id,
                    "name": role.name,
                    "code": role.code,
                    "enabled": role.enabled,
                    "security_level": role.security_level,
                    "data_scope": role.data_scope,
                }
                for role in user.roles
            ],
            "max_security_level": user_max_security_level(user),
            "permission_codes": sorted(permission_codes),
            "permissions": {
                "menus": sorted(permission_codes & MENU_PERMISSION_CODES),
                "actions": sorted(filter_bound_action_codes(permission_codes)),
            },
        }

    def current_permissions(self, user: User) -> dict[str, list[str]]:
        """返回当前用户菜单与按钮权限，供前端路由、菜单和 v-permission 使用。"""

        permission_codes = sync_menu_action_permission_codes(self._user_permission_codes(user))
        return {
            "menus": sorted(permission_codes & MENU_PERMISSION_CODES),
            "actions": sorted(filter_bound_action_codes(permission_codes)),
        }

    def _user_permission_codes(self, user: User) -> set[str]:
        """仅汇总启用角色授予的权限码。"""

        return {
            permission.code
            for role in user.roles
            if role.enabled
            for permission in role.permissions
        }
