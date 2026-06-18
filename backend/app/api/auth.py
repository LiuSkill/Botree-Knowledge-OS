"""
Auth API

负责：
1. 用户登录
2. 获取当前用户
3. 退出登录日志记录
"""

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.response import success
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest
from app.services.auth_service import AuthService
from app.services.system_service import SystemService
from app.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", summary="用户登录")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """
    用户登录接口

    参数:
        payload: 登录请求
        request: HTTP 请求
        db: 数据库会话

    返回:
        JWT token 和当前用户。
    """

    data = AuthService(db).login(payload.username, payload.password, request.client.host if request.client else None)
    return success(data)


@router.get("/me", summary="获取当前用户")
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """
    获取当前用户接口

    返回:
        当前登录用户信息。
    """

    return success(AuthService(db).to_current_user(current_user))


@router.post("/me/avatar", summary="上传当前用户头像")
async def upload_my_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """上传当前用户头像。"""

    profile = await UserService(db).upload_own_avatar(current_user, file)
    return success(profile)


@router.delete("/me/avatar", summary="删除当前用户头像")
def delete_my_avatar(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """删除当前用户头像。"""

    profile = UserService(db).delete_own_avatar(current_user)
    return success(profile)


@router.post("/me/change-password", summary="修改当前用户密码")
def change_my_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """修改当前用户密码。"""

    UserService(db).change_own_password(current_user, payload.current_password, payload.new_password)
    return success({"changed": True})


@router.post("/logout", summary="退出登录")
def logout(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """
    退出登录接口

    返回:
        退出成功状态。
    """

    SystemService(db).record_operation(current_user, "退出登录", "auth", current_user.id, "用户退出登录", auto_commit=True)
    return success({"logged_out": True})
