"""
User Service

负责：
1. 用户、角色、权限管理业务
2. 密码初始化和重置
3. 系统管理操作日志记录
"""

import logging
from collections.abc import Iterator
from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.minio import get_minio_client
from app.core.rbac import filter_bound_action_codes, menu_permission_codes, sync_menu_action_permission_codes
from app.core.security import hash_password, verify_password
from app.models.user import Permission, Role, User
from app.repositories.user_repository import RoleRepository, UserRepository
from app.schemas.role import RoleCreate, RoleUpdate
from app.schemas.user import UserCreate, UserUpdate
from app.services.system_service import SystemService
from app.utils.pagination import paginate
from app.utils.user_avatar import avatar_url_for_user

logger = logging.getLogger(__name__)

AVATAR_MAX_BYTES = 2 * 1024 * 1024
AVATAR_CONTENT_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
}
MENU_PERMISSION_CODES = menu_permission_codes()


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

    def list_users(
        self,
        keyword: str | None = None,
        status: str | None = None,
        role_id: int | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict:
        """查询用户列表。"""

        return paginate(self.user_repository.list(keyword=keyword, status=status, role_id=role_id), page, page_size)

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

    async def upload_own_avatar(self, user: User, upload_file: UploadFile) -> dict:
        """
        上传当前用户头像。

        说明：
            头像是个人资产，当前版本只允许本人维护；文件必须写入 MinIO，
            未配置对象存储时直接返回业务错误，避免悄悄落盘导致环境不一致。
        """

        content_type = (upload_file.content_type or "").lower()
        extension = AVATAR_CONTENT_TYPES.get(content_type)
        if not extension:
            raise AppException("头像仅支持 PNG、JPG、JPEG、WEBP 格式")

        content = await upload_file.read(AVATAR_MAX_BYTES + 1)
        if not content:
            raise AppException("头像文件不能为空")
        if len(content) > AVATAR_MAX_BYTES:
            raise AppException("头像文件不能超过 2MB")

        client = get_minio_client()
        if client is None:
            raise AppException("对象存储未启用，无法上传头像", status_code=503, code=503)

        settings = get_settings()
        object_key = f"avatars/{user.id}/{uuid4().hex}.{extension}"
        previous_object_key = user.avatar_object_key
        client.put_object(
            settings.minio_bucket,
            object_key,
            BytesIO(content),
            length=len(content),
            content_type=content_type,
        )
        self._remove_avatar_object(client, previous_object_key)

        user.avatar_object_key = object_key
        user.avatar_file_name = Path(upload_file.filename or f"avatar.{extension}").name
        user.avatar_content_type = content_type
        user.avatar_updated_at = datetime.utcnow()
        SystemService(self.db).record_operation(user, "更新头像", "user", user.id, "当前用户更新头像")
        self.db.commit()
        logger.info("用户头像已上传: user_id=%s object_key=%s", user.id, object_key)
        return self._current_user_profile(user)

    def delete_own_avatar(self, user: User) -> dict:
        """删除当前用户头像。"""

        client = get_minio_client()
        if client is None:
            raise AppException("对象存储未启用，无法删除头像", status_code=503, code=503)

        self._remove_avatar_object(client, user.avatar_object_key)
        user.avatar_object_key = None
        user.avatar_file_name = None
        user.avatar_content_type = None
        user.avatar_updated_at = None
        SystemService(self.db).record_operation(user, "删除头像", "user", user.id, "当前用户删除头像")
        self.db.commit()
        logger.info("用户头像已删除: user_id=%s", user.id)
        return self._current_user_profile(user)

    def change_own_password(self, user: User, current_password: str, new_password: str) -> None:
        """修改当前用户密码。"""

        if not verify_password(current_password, user.password_hash):
            raise AppException("当前密码错误", status_code=400, code=400)
        user.password_hash = hash_password(new_password)
        SystemService(self.db).record_operation(user, "修改密码", "user", user.id, "当前用户修改密码")
        self.db.commit()
        logger.info("用户密码已修改: user_id=%s", user.id)

    def open_avatar_stream(self, user_id: int, current_user: User) -> dict:
        """按权限读取用户头像对象。"""

        target = self.user_repository.get_by_id(user_id)
        if not target:
            raise AppException("用户不存在", status_code=404, code=404)
        if not self._can_read_avatar(target, current_user):
            raise AppException("无权查看该用户头像", status_code=403, code=403)
        if not target.avatar_object_key:
            raise AppException("用户未设置头像", status_code=404, code=404)

        client = get_minio_client()
        if client is None:
            raise AppException("对象存储未启用，无法读取头像", status_code=503, code=503)

        settings = get_settings()
        response = client.get_object(settings.minio_bucket, target.avatar_object_key)
        return {
            "content": self._stream_minio_response(response),
            "content_type": target.avatar_content_type or "application/octet-stream",
        }

    def _current_user_profile(self, user: User) -> dict:
        """返回与 /auth/me 一致的当前用户资料。"""

        permission_codes = sync_menu_action_permission_codes(self._user_permission_codes(user))
        return {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "email": user.email,
            "phone": user.phone,
            "department": user.department,
            "status": user.status,
            "avatar_url": avatar_url_for_user(user),
            "avatar_updated_at": user.avatar_updated_at.isoformat() if user.avatar_updated_at else None,
            "roles": [
                {"id": role.id, "name": role.name, "code": role.code, "enabled": role.enabled}
                for role in user.roles
            ],
            "permission_codes": sorted(permission_codes),
            "permissions": {
                "menus": sorted(permission_codes & MENU_PERMISSION_CODES),
                "actions": sorted(filter_bound_action_codes(permission_codes)),
            },
        }

    def _can_read_avatar(self, target: User, current_user: User) -> bool:
        """判断当前用户是否可读取目标用户头像。"""

        if target.id == current_user.id:
            return True
        if any(role.code == "admin" and role.enabled for role in current_user.roles):
            return True
        return "system:user" in self._user_permission_codes(current_user)

    def _user_permission_codes(self, user: User) -> set[str]:
        """仅汇总启用角色授予的权限码。"""

        return {
            permission.code
            for role in user.roles
            if role.enabled
            for permission in role.permissions
        }

    def _remove_avatar_object(self, client, object_key: str | None) -> None:
        """删除 MinIO 头像对象，旧对象不存在时仅记录告警。"""

        if not object_key:
            return
        try:
            client.remove_object(get_settings().minio_bucket, object_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除头像对象失败: object_key=%s error=%s", object_key, exc)

    def _stream_minio_response(self, response) -> Iterator[bytes]:
        """流式读取 MinIO 对象并确保连接释放。"""

        try:
            yield from response.stream(32 * 1024)
        finally:
            response.close()
            response.release_conn()


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

    def list_role_page(
        self,
        keyword: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict:
        """按筛选条件分页查询角色列表。"""

        return paginate(self.role_repository.list(keyword=keyword, enabled=enabled), page, page_size)

    def list_permissions(self) -> list:
        """查询权限列表。"""

        return self.role_repository.list_permissions()

    def create_role(self, payload: RoleCreate, operator: User) -> Role:
        """创建角色。"""

        if self.role_repository.get_by_code(payload.code):
            raise AppException("角色编码已存在")
        role = Role(name=payload.name, code=payload.code, description=payload.description, enabled=True)
        role.permissions = self._resolve_bound_permissions(payload.permission_ids)
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
            role.permissions = self._resolve_bound_permissions(payload.permission_ids)
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

    def _resolve_bound_permissions(self, permission_ids: list[int]) -> list[Permission]:
        """
        根据页面-按钮绑定关系过滤角色权限。

        业务规则：
        - 菜单权限可独立授权，用于控制路由和菜单可见性；
        - 按钮权限必须挂靠在已授权页面下，取消页面权限时同步取消该页按钮权限；
        - 后端保存时再次裁剪，防止绕过前端提交孤立按钮权限。
        """

        selected_ids = set(permission_ids)
        permissions = self.role_repository.list_permissions()
        selected_permissions = [permission for permission in permissions if permission.id in selected_ids]
        synced_codes = sync_menu_action_permission_codes({permission.code for permission in selected_permissions})
        return [permission for permission in permissions if permission.code in synced_codes]
