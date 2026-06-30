"""Departments API."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, has_permission, require_permission
from app.core.database import get_db
from app.core.exceptions import AppException
from app.core.response import success
from app.models.user import User
from app.schemas.department import DepartmentCreate, DepartmentOut, DepartmentStatusUpdate, DepartmentUpdate, DepartmentUserOption
from app.services.department_service import DepartmentService

router = APIRouter(prefix="/system/departments", tags=["部门管理"])


@router.get("/tree", summary="查询部门树")
def department_tree(
    keyword: str | None = None,
    status: str | None = None,
    _: User = Depends(require_permission("system:department:view")),
    db: Session = Depends(get_db),
) -> dict:
    """查询部门树。"""

    tree = DepartmentService(db).list_department_tree(keyword=keyword, status=status)
    return success([DepartmentOut.model_validate(item).model_dump(mode="json") for item in tree])


@router.get("/user-options", summary="部门负责人候选用户")
def department_user_options(
    _: User = Depends(require_permission("system:department:view")),
    db: Session = Depends(get_db),
) -> dict:
    """查询可作为部门负责人的用户。"""

    users = DepartmentService(db).list_user_options()
    return success([DepartmentUserOption.model_validate(item).model_dump(mode="json") for item in users])


@router.get("", summary="查询部门列表")
def list_departments(
    keyword: str | None = None,
    status: str | None = None,
    parent_id: int | None = None,
    _: User = Depends(require_permission("system:department:view")),
    db: Session = Depends(get_db),
) -> dict:
    """查询部门平铺列表。"""

    departments = DepartmentService(db).list_departments(keyword=keyword, status=status, parent_id=parent_id)
    return success([DepartmentOut.model_validate(item).model_dump(mode="json") for item in departments])


@router.get("/{department_id}", summary="部门详情")
def get_department(
    department_id: int,
    _: User = Depends(require_permission("system:department:view-detail")),
    db: Session = Depends(get_db),
) -> dict:
    """查询部门详情。"""

    department = DepartmentService(db).get_department(department_id)
    return success(DepartmentOut.model_validate(department).model_dump(mode="json"))


@router.post("", summary="新增部门")
def create_department(
    payload: DepartmentCreate,
    current_user: User = Depends(require_permission("system:department:create")),
    db: Session = Depends(get_db),
) -> dict:
    """新增部门。"""

    department = DepartmentService(db).create_department(payload, current_user)
    return success(DepartmentOut.model_validate(department).model_dump(mode="json"))


@router.put("/{department_id}", summary="编辑部门")
def update_department(
    department_id: int,
    payload: DepartmentUpdate,
    current_user: User = Depends(require_permission("system:department:edit")),
    db: Session = Depends(get_db),
) -> dict:
    """编辑部门。"""

    department = DepartmentService(db).update_department(department_id, payload, current_user)
    return success(DepartmentOut.model_validate(department).model_dump(mode="json"))


@router.patch("/{department_id}/status", summary="启用或停用部门")
def update_department_status(
    department_id: int,
    payload: DepartmentStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """启用或停用部门。"""

    permission_code = "system:department:enable" if payload.status == "enabled" else "system:department:disable"
    if not has_permission(current_user, permission_code):
        raise AppException("无权执行该操作", status_code=403, code=403)
    department = DepartmentService(db).update_status(department_id, payload, current_user)
    return success(DepartmentOut.model_validate(department).model_dump(mode="json"))


@router.delete("/{department_id}", summary="删除部门")
def delete_department(
    department_id: int,
    current_user: User = Depends(require_permission("system:department:delete")),
    db: Session = Depends(get_db),
) -> dict:
    """删除部门。"""

    DepartmentService(db).delete_department(department_id, current_user)
    return success({"deleted": True})
