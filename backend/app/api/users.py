"""
Users API

负责：
1. 用户管理接口
2. 用户新增、编辑、删除和重置密码
3. Controller 层不直接操作数据库
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, has_permission, require_permission
from app.core.database import get_db
from app.core.exceptions import AppException
from app.core.response import success
from app.models.user import User
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.auth_service import AuthService
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["用户管理"])
current_user_router = APIRouter(prefix="/user", tags=["当前用户权限"])


@router.get("", summary="用户列表")
def list_users(
    keyword: str | None = None,
    status: str | None = None,
    role_id: int | None = None,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_permission("system:user:view")),
    db: Session = Depends(get_db),
) -> dict:
    """查询用户列表。"""

    result = UserService(db).list_users(keyword=keyword, status=status, role_id=role_id, page=page, page_size=page_size)
    return success(
        {
            **result,
            "items": [UserOut.model_validate(item).model_dump(mode="json") for item in result["items"]],
        }
    )


@router.post("", summary="新增用户")
def create_user(payload: UserCreate, current_user: User = Depends(require_permission("system:user:create")), db: Session = Depends(get_db)) -> dict:
    """新增用户。"""

    user = UserService(db).create_user(payload, current_user)
    return success(UserOut.model_validate(user).model_dump(mode="json"))


@router.get("/{user_id}", summary="用户详情")
def get_user(user_id: int, _: User = Depends(require_permission("system:user:view")), db: Session = Depends(get_db)) -> dict:
    """查询用户详情。"""

    user = UserService(db).user_repository.get_by_id(user_id)
    return success(UserOut.model_validate(user).model_dump(mode="json") if user else None)


@router.get("/{user_id}/avatar", summary="读取用户头像")
def get_user_avatar(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """按权限读取用户头像。"""

    avatar = UserService(db).open_avatar_stream(user_id, current_user)
    return StreamingResponse(avatar["content"], media_type=avatar["content_type"])


@router.put("/{user_id}", summary="编辑用户")
def update_user(user_id: int, payload: UserUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """编辑用户。"""

    changed_fields = payload.model_fields_set
    if changed_fields == {"status"}:
        if not has_permission(current_user, "system:user:disable"):
            raise AppException("无权执行该操作", status_code=403, code=403)
    elif not has_permission(current_user, "system:user:edit"):
        raise AppException("无权执行该操作", status_code=403, code=403)
    user = UserService(db).update_user(user_id, payload, current_user)
    return success(UserOut.model_validate(user).model_dump(mode="json"))


@router.delete("/{user_id}", summary="删除用户")
def delete_user(user_id: int, current_user: User = Depends(require_permission("system:user:delete")), db: Session = Depends(get_db)) -> dict:
    """删除用户。"""

    UserService(db).delete_user(user_id, current_user)
    return success({"deleted": True})


@router.post("/{user_id}/reset-password", summary="重置密码")
def reset_password(user_id: int, current_user: User = Depends(require_permission("system:user:reset-password")), db: Session = Depends(get_db)) -> dict:
    """重置用户密码。"""

    UserService(db).reset_password(user_id, current_user)
    return success({"reset": True, "default_password": "Botree@123456"})


@current_user_router.get("/current-permissions", summary="当前用户权限")
def current_permissions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """返回当前登录用户的菜单和按钮权限。"""

    return success(AuthService(db).current_permissions(current_user))
