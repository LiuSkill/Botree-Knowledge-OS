"""
Users API

负责：
1. 用户管理接口
2. 用户新增、编辑、删除和重置密码
3. Controller 层不直接操作数据库
"""

import json
from typing import Any, TypeVar, cast

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as FormUploadFile

from app.api.deps import get_current_user, has_permission, require_permission
from app.core.database import get_db
from app.core.exceptions import AppException
from app.core.response import success
from app.models.user import User
from app.schemas.department import DepartmentOut
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.auth_service import AuthService
from app.services.department_service import DepartmentService
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["用户管理"])
current_user_router = APIRouter(prefix="/user", tags=["当前用户权限"])
PayloadModel = TypeVar("PayloadModel", bound=BaseModel)


def _truthy_form_value(value: Any) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def _extract_avatar_file(value: Any) -> UploadFile | None:
    if isinstance(value, FormUploadFile) and value.filename:
        return cast(UploadFile, value)
    return None


def _validate_payload(model: type[PayloadModel], data: dict[str, Any]) -> PayloadModel:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise AppException("用户请求参数不合法", status_code=422, code=422) from exc


async def _parse_user_payload(request: Request) -> tuple[dict[str, Any], UploadFile | None, bool]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        payload_value = form.get("payload")
        if not isinstance(payload_value, str):
            raise AppException("用户表单数据不能为空", status_code=422, code=422)
        try:
            payload = json.loads(payload_value)
        except json.JSONDecodeError as exc:
            raise AppException("用户表单数据格式错误", status_code=422, code=422) from exc
        if not isinstance(payload, dict):
            raise AppException("用户表单数据格式错误", status_code=422, code=422)
        avatar_file = _extract_avatar_file(form.get("avatar"))
        clear_avatar = _truthy_form_value(form.get("clear_avatar")) and avatar_file is None
        return payload, avatar_file, clear_avatar

    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise AppException("用户请求数据格式错误", status_code=422, code=422) from exc
    if not isinstance(payload, dict):
        raise AppException("用户请求数据格式错误", status_code=422, code=422)
    return payload, None, False


@router.get("", summary="用户列表")
def list_users(
    keyword: str | None = None,
    status: str | None = None,
    role_id: int | None = None,
    department_id: int | None = None,
    include_children: bool = False,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_permission("system:user:view")),
    db: Session = Depends(get_db),
) -> dict:
    """查询用户列表。"""

    result = UserService(db).list_users(
        keyword=keyword,
        status=status,
        role_id=role_id,
        department_id=department_id,
        include_children=include_children,
        page=page,
        page_size=page_size,
    )
    return success(
        {
            **result,
            "items": [UserOut.model_validate(item).model_dump(mode="json") for item in result["items"]],
        }
    )


@router.post("", summary="新增用户")
async def create_user(
    request: Request,
    current_user: User = Depends(require_permission("system:user:create")),
    db: Session = Depends(get_db),
) -> dict:
    """新增用户。"""

    payload_data, avatar_file, _clear_avatar = await _parse_user_payload(request)
    payload = _validate_payload(UserCreate, payload_data)
    service = UserService(db)
    user = (
        await service.create_user_with_avatar(payload, current_user, avatar_file)
        if avatar_file
        else service.create_user(payload, current_user)
    )
    return success(UserOut.model_validate(user).model_dump(mode="json"))


@router.get("/departments/tree", summary="用户管理部门树")
def user_department_tree(
    keyword: str | None = None,
    status: str | None = None,
    _: User = Depends(require_permission("system:user:view")),
    db: Session = Depends(get_db),
) -> dict:
    """查询用户管理可用部门树。"""

    tree = DepartmentService(db).list_department_tree(keyword=keyword, status=status)
    return success([DepartmentOut.model_validate(item).model_dump(mode="json") for item in tree])


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
async def update_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """编辑用户。"""

    payload_data, avatar_file, clear_avatar = await _parse_user_payload(request)
    payload = _validate_payload(UserUpdate, payload_data)
    changed_fields = payload.model_fields_set
    avatar_changed = avatar_file is not None or clear_avatar
    if changed_fields == {"status"} and not avatar_changed:
        if not has_permission(current_user, "system:user:disable"):
            raise AppException("无权执行该操作", status_code=403, code=403)
    elif not has_permission(current_user, "system:user:edit"):
        raise AppException("无权执行该操作", status_code=403, code=403)
    service = UserService(db)
    user = (
        await service.update_user_with_avatar(
            user_id,
            payload,
            current_user,
            avatar_file=avatar_file,
            clear_avatar=clear_avatar,
        )
        if avatar_changed
        else service.update_user(user_id, payload, current_user)
    )
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
