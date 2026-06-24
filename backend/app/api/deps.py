"""
API Dependencies

负责：
1. 解析当前登录用户
2. 提供管理员和项目权限校验辅助函数
3. 避免 Controller 层重复编写认证逻辑
"""

from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError
from sqlalchemy.orm import Session

from app.core.rbac import action_page_bindings
from app.core.database import get_db
from app.core.exceptions import AppException
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user_repository import UserRepository

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    获取当前登录用户

    参数:
        credentials: Bearer Token 凭证
        db: 数据库会话

    返回:
        当前用户 ORM 对象。
    """

    if credentials is None:
        raise AppException("未登录或登录已过期", status_code=401, code=401)
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (KeyError, ValueError, PyJWTError) as exc:
        raise AppException("无效登录凭证", status_code=401, code=401) from exc

    user = UserRepository(db).get_by_id(user_id)
    if not user or user.status != "enabled":
        raise AppException("用户不存在或已禁用", status_code=401, code=401)
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    校验管理员角色

    参数:
        current_user: 当前登录用户

    返回:
        当前管理员用户。
    """

    if not any(role.code == "admin" and role.enabled for role in current_user.roles):
        raise AppException("需要管理员权限", status_code=403, code=403)
    return current_user


def user_permission_codes(user: User) -> set[str]:
    """
    获取用户权限编码集合

    参数:
        user: 当前用户

    返回:
        用户通过角色获得的权限编码集合。
    """

    codes: set[str] = set()
    for role in user.roles:
        if not role.enabled:
            continue
        for permission in role.permissions:
            codes.add(permission.code)
    return codes


def has_permission(user: User, permission_code: str) -> bool:
    """
    判断用户是否拥有指定权限

    参数:
        user: 当前用户
        permission_code: 权限编码，例如 review:view

    返回:
        是否拥有权限。
    """

    if is_admin(user):
        return True
    permission_codes = user_permission_codes(user)
    bound_menu_codes = action_page_bindings().get(permission_code)
    if bound_menu_codes is not None:
        return bool(bound_menu_codes & permission_codes)
    return permission_code in permission_codes


def require_permission(permission_code: str) -> Callable[[User], User]:
    """
    生成权限校验依赖

    参数:
        permission_code: 权限编码

    返回:
        FastAPI 依赖函数。
    """

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        """校验当前用户是否拥有指定权限。"""

        if not has_permission(current_user, permission_code):
            raise AppException("无权执行该操作", status_code=403, code=403)
        return current_user

    return dependency


def require_any_permission(*permission_codes: str) -> Callable[[User], User]:
    """
    生成任一权限校验依赖。

    说明：
        部分接口会被多个页面复用，例如用户管理需要读取角色选项，
        权限矩阵也需要读取角色列表，此时满足任一页面权限即可访问。
    """

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        """校验当前用户是否拥有任一指定权限。"""

        if not any(has_permission(current_user, code) for code in permission_codes):
            raise AppException("无权执行该操作", status_code=403, code=403)
        return current_user

    return dependency


def is_admin(user: User) -> bool:
    """
    判断用户是否管理员

    参数:
        user: 用户对象

    返回:
        是否拥有 admin 角色。
    """

    return any(role.code == "admin" and role.enabled for role in user.roles)
