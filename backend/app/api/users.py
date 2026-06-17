"""
Users API

负责：
1. 用户管理接口
2. 用户新增、编辑、删除和重置密码
3. Controller 层不直接操作数据库
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.core.response import success
from app.models.user import User
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["用户管理"])


@router.get("", summary="用户列表")
def list_users(keyword: str | None = None, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """查询用户列表。"""

    users = UserService(db).list_users(keyword)
    return success([UserOut.model_validate(item).model_dump(mode="json") for item in users])


@router.post("", summary="新增用户")
def create_user(payload: UserCreate, current_user: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """新增用户。"""

    user = UserService(db).create_user(payload, current_user)
    return success(UserOut.model_validate(user).model_dump(mode="json"))


@router.get("/{user_id}", summary="用户详情")
def get_user(user_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """查询用户详情。"""

    user = UserService(db).user_repository.get_by_id(user_id)
    return success(UserOut.model_validate(user).model_dump(mode="json") if user else None)


@router.put("/{user_id}", summary="编辑用户")
def update_user(user_id: int, payload: UserUpdate, current_user: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """编辑用户。"""

    user = UserService(db).update_user(user_id, payload, current_user)
    return success(UserOut.model_validate(user).model_dump(mode="json"))


@router.delete("/{user_id}", summary="删除用户")
def delete_user(user_id: int, current_user: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """删除用户。"""

    UserService(db).delete_user(user_id, current_user)
    return success({"deleted": True})


@router.post("/{user_id}/reset-password", summary="重置密码")
def reset_password(user_id: int, current_user: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """重置用户密码。"""

    UserService(db).reset_password(user_id, current_user)
    return success({"reset": True, "default_password": "Botree@123456"})
