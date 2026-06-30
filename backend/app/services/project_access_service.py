"""Project and project-document access policy service."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.data_scope import (
    DATA_SCOPE_ALL,
    DATA_SCOPE_DEPARTMENT,
    DATA_SCOPE_OWN,
    DATA_SCOPE_PUBLIC_ONLY,
    enabled_role_data_scopes,
)
from app.core.exceptions import AppException
from app.core.rbac import sync_menu_action_permission_codes
from app.core.security_levels import ensure_security_level_access
from app.models.document import Document
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.repositories.project_repository import ProjectRepository

logger = logging.getLogger(__name__)


class ProjectAccessService:
    """统一封装项目和项目资料访问规则，供 Service 层复用。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.project_repository = ProjectRepository(db)

    def is_admin(self, user: User) -> bool:
        """系统管理员不受项目数据范围限制。"""

        return any(role.code == "admin" and role.enabled for role in user.roles)

    def has_permission(self, user: User, *permission_codes: str) -> bool:
        """判断用户是否显式拥有任一权限点。"""

        if self.is_admin(user):
            return True
        user_codes = sync_menu_action_permission_codes(
            {
                permission.code
                for role in user.roles
                if role.enabled
                for permission in role.permissions
            }
        )
        return any(code in user_codes for code in permission_codes)

    def ensure_permission(self, user: User, *permission_codes: str, message: str = "无权执行该操作") -> None:
        """无任一指定权限时抛出统一业务异常。"""

        if not self.has_permission(user, *permission_codes):
            raise AppException(message, status_code=403, code=403)

    def ensure_project_access(
        self,
        project_id: int,
        user: User,
        *,
        permission_codes: tuple[str, ...] = ("project:view", "project"),
    ) -> Project:
        """校验项目页面/API 权限、数据范围和项目密级。"""

        project = self.project_repository.get(project_id)
        if not project or bool(getattr(project, "is_deleted", False)):
            raise AppException("项目不存在", status_code=404, code=404)
        self.ensure_permission(user, *permission_codes, message="无权访问该项目")
        ensure_security_level_access(user, project.security_level, message="无权访问该项目密级")
        if self.is_admin(user) or self._data_scope_allows_project(project, user):
            return project
        raise AppException("无权访问该项目", status_code=403, code=403)

    def can_access_project(
        self,
        project: Project,
        user: User,
        *,
        permission_codes: tuple[str, ...] = ("project:view", "project"),
    ) -> bool:
        """列表过滤使用的非抛错项目访问判断。"""

        try:
            self.ensure_permission(user, *permission_codes, message="无权访问该项目")
            ensure_security_level_access(user, project.security_level, message="无权访问该项目密级")
        except AppException:
            return False
        return self.is_admin(user) or self._data_scope_allows_project(project, user)

    def ensure_document_access(
        self,
        document: Document,
        user: User,
        *,
        permission_codes: tuple[str, ...] = ("project:view",),
    ) -> None:
        """校验项目资料操作权限、项目访问权限、文档归属、软删除和文档密级。"""

        if bool(getattr(document, "is_deleted", False)):
            raise AppException("文档不存在", status_code=404, code=404)
        if document.project_id is not None:
            self.ensure_project_access(document.project_id, user, permission_codes=("project:view", "project"))
            self.ensure_permission(user, *permission_codes, message="无权访问该项目资料")
        ensure_security_level_access(user, document.security_level, message="无权访问该文档密级")

    def can_access_document(
        self,
        document: Document,
        user: User,
        *,
        permission_codes: tuple[str, ...] = ("project:view",),
    ) -> bool:
        """列表过滤使用的非抛错文档访问判断。"""

        try:
            self.ensure_document_access(document, user, permission_codes=permission_codes)
        except AppException:
            return False
        return True

    def _data_scope_allows_project(self, project: Project, user: User) -> bool:
        scopes = enabled_role_data_scopes(user)
        if DATA_SCOPE_ALL in scopes:
            return True
        member = self.project_repository.get_member(project.id, user.id)
        if DATA_SCOPE_DEPARTMENT in scopes and self._same_department(project, user):
            return True
        if DATA_SCOPE_DEPARTMENT in scopes and self._is_active_member(member):
            logger.info(
                "项目缺少部门字段时按成员关系兼容部门数据范围: project_id=%s user_id=%s",
                project.id,
                user.id,
            )
            return True
        if DATA_SCOPE_OWN in scopes and self._is_own_project(project, user, member):
            return True
        return DATA_SCOPE_PUBLIC_ONLY in scopes and str(project.security_level or "").lower() == "public"

    def _same_department(self, project: Project, user: User) -> bool:
        project_department = getattr(project, "department", None) or getattr(project, "department_id", None)
        user_department = getattr(user, "department", None) or getattr(user, "department_id", None)
        return bool(project_department and user_department and str(project_department) == str(user_department))

    def _is_own_project(self, project: Project, user: User, member: ProjectMember | None) -> bool:
        return bool(project.created_by == user.id or self._is_active_member(member))

    def _is_active_member(self, member: ProjectMember | None) -> bool:
        return bool(member and member.status == "active")
