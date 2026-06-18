"""
Roles API

负责：
1. 角色管理接口
2. 权限矩阵数据接口
3. 支持系统管理页面
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import success
from app.models.user import User
from app.schemas.role import PermissionOut, RoleCreate, RoleOut, RoleUpdate
from app.services.user_service import RoleService

router = APIRouter(prefix="/roles", tags=["角色管理"])


@router.get("", summary="角色列表")
def list_roles(
    keyword: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_any_permission("system:user", "system:permission")),
    db: Session = Depends(get_db),
) -> dict:
    """查询角色列表。"""

    result = RoleService(db).list_role_page(keyword=keyword, enabled=enabled, page=page, page_size=page_size)
    return success(
        {
            **result,
            "items": [RoleOut.model_validate(item).model_dump(mode="json") for item in result["items"]],
        }
    )


@router.post("", summary="新增角色")
def create_role(payload: RoleCreate, current_user: User = Depends(require_permission("permission:create")), db: Session = Depends(get_db)) -> dict:
    """新增角色。"""

    role = RoleService(db).create_role(payload, current_user)
    return success(RoleOut.model_validate(role).model_dump(mode="json"))


@router.put("/{role_id}", summary="编辑角色")
def update_role(
    role_id: int,
    payload: RoleUpdate,
    current_user: User = Depends(require_any_permission("permission:edit", "permission:save")),
    db: Session = Depends(get_db),
) -> dict:
    """编辑角色。"""

    role = RoleService(db).update_role(role_id, payload, current_user)
    return success(RoleOut.model_validate(role).model_dump(mode="json"))


@router.delete("/{role_id}", summary="删除角色")
def delete_role(role_id: int, current_user: User = Depends(require_permission("permission:delete")), db: Session = Depends(get_db)) -> dict:
    """删除角色。"""

    RoleService(db).delete_role(role_id, current_user)
    return success({"deleted": True})


@router.get("/permissions/matrix", summary="权限矩阵")
def permission_matrix(_: User = Depends(require_permission("system:permission")), db: Session = Depends(get_db)) -> dict:
    """查询权限矩阵。"""

    service = RoleService(db)
    return success(
        {
            "roles": [RoleOut.model_validate(role).model_dump(mode="json") for role in service.list_roles()],
            "permissions": [PermissionOut.model_validate(item).model_dump(mode="json") for item in service.list_permissions()],
        }
    )
