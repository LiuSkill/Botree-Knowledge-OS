"""Project service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.security_levels import DEFAULT_SECURITY_LEVEL, allowed_security_levels, ensure_security_level_access, normalize_security_level, user_max_security_level
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_category import KnowledgeCategory
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.schemas.project import ProjectCreate, ProjectMemberCreate, ProjectUpdate
from app.services.system_service import SystemService


class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.project_repository = ProjectRepository(db)
        self.kb_repository = KnowledgeBaseRepository(db)

    def user_is_admin(self, user: User) -> bool:
        return any(role.code == "admin" for role in user.roles)

    def _user_allowed_levels(self, user: User) -> list[str]:
        return allowed_security_levels(user_max_security_level(user))

    def ensure_project_access(self, project_id: int, user: User) -> None:
        project = self.project_repository.get(project_id)
        if not project:
            raise AppException("项目不存在", status_code=404, code=404)
        ensure_security_level_access(user, project.security_level)
        if self.user_is_admin(user):
            return
        if not self.project_repository.get_member(project_id, user.id):
            raise AppException("无权访问该项目", status_code=403, code=403)

    def list_projects(self, user: User, keyword: str | None = None) -> list[dict]:
        projects = self.project_repository.list(keyword=keyword, user_id=user.id, admin=self.user_is_admin(user))
        projects = [project for project in projects if project.security_level in self._user_allowed_levels(user)]
        doc_repo = DocumentRepository(self.db)
        result: list[dict] = []
        for project in projects:
            kb = self.kb_repository.get_project_base(project.id)
            documents = [item for item in doc_repo.list(project_id=project.id) if item.security_level in self._user_allowed_levels(user)]
            result.append(self._project_to_dict(project, kb.id if kb else None, len(documents), sum(1 for doc in documents if doc.index_status == "indexed")))
        return result

    def get_project(self, project_id: int, user: User) -> dict:
        self.ensure_project_access(project_id, user)
        project = self.project_repository.get(project_id)
        if not project:
            raise AppException("项目不存在", status_code=404, code=404)
        kb = self.kb_repository.get_project_base(project.id)
        documents = [item for item in DocumentRepository(self.db).list(project_id=project.id) if item.security_level in self._user_allowed_levels(user)]
        return self._project_to_dict(project, kb.id if kb else None, len(documents), sum(1 for doc in documents if doc.index_status == "indexed"))

    def create_project(self, payload: ProjectCreate, operator: User) -> dict:
        if self.project_repository.get_by_code(payload.code):
            raise AppException("项目编码已存在")
        security_level = normalize_security_level(payload.security_level, default=DEFAULT_SECURITY_LEVEL)
        ensure_security_level_access(operator, security_level)
        project = Project(
            name=payload.name,
            code=payload.code,
            description=payload.description,
            client=payload.client,
            manager=payload.manager,
            status=payload.status,
            progress=payload.progress,
            security_level=security_level,
            created_by=operator.id,
        )
        self.project_repository.add(project)

        self.project_repository.add_member(
            ProjectMember(
                project_id=project.id,
                user_id=operator.id,
                role="owner",
                permission_scope="project_manage",
                external_user=False,
                status="active",
            )
        )
        kb = KnowledgeBase(
            name=f"{project.name}知识库",
            code=f"project-{project.code}",
            type="project",
            project_id=project.id,
            description=f"{project.name} 的项目资料与专业知识库",
            enabled=True,
            created_by=operator.id,
        )
        self.kb_repository.add(kb)
        self._seed_default_project_categories(project.id, operator.id)
        SystemService(self.db).record_operation(operator, "创建项目", "project", project.id, f"创建项目 {project.name}")
        self.db.commit()
        return self._project_to_dict(project, kb.id, 0, 0)

    def update_project(self, project_id: int, payload: ProjectUpdate, operator: User) -> dict:
        self.ensure_project_access(project_id, operator)
        project = self.project_repository.get(project_id)
        if not project:
            raise AppException("项目不存在", status_code=404, code=404)
        if payload.security_level is not None:
            project.security_level = normalize_security_level(payload.security_level, default=project.security_level)
            ensure_security_level_access(operator, project.security_level)
        for field in ["name", "description", "client", "manager", "status", "progress"]:
            value = getattr(payload, field)
            if value is not None:
                setattr(project, field, value)
        SystemService(self.db).record_operation(operator, "编辑项目", "project", project.id, f"编辑项目 {project.name}")
        self.db.commit()
        return self.get_project(project_id, operator)

    def delete_project(self, project_id: int, operator: User) -> None:
        self.ensure_project_access(project_id, operator)
        project = self.project_repository.get(project_id)
        if not project:
            raise AppException("项目不存在", status_code=404, code=404)
        self.project_repository.delete(project)
        SystemService(self.db).record_operation(operator, "删除项目", "project", project_id, "删除项目")
        self.db.commit()

    def list_members(self, project_id: int, operator: User) -> list[ProjectMember]:
        self.ensure_project_access(project_id, operator)
        return self.project_repository.list_members(project_id)

    def add_member(self, project_id: int, payload: ProjectMemberCreate, operator: User) -> ProjectMember:
        self.ensure_project_access(project_id, operator)
        if not UserRepository(self.db).get_by_id(payload.user_id):
            raise AppException("用户不存在", status_code=404, code=404)
        existing = self.project_repository.get_member(project_id, payload.user_id)
        if existing:
            return existing
        member = ProjectMember(
            project_id=project_id,
            user_id=payload.user_id,
            role=payload.role,
            permission_scope=payload.permission_scope,
            external_user=payload.external_user,
            status="active",
        )
        self.project_repository.add_member(member)
        SystemService(self.db).record_operation(operator, "新增项目成员", "project_member", member.id, f"项目 {project_id} 新增成员")
        self.db.commit()
        return member

    def delete_member(self, project_id: int, user_id: int, operator: User) -> None:
        self.ensure_project_access(project_id, operator)
        member = self.project_repository.get_member(project_id, user_id)
        if not member:
            raise AppException("项目成员不存在", status_code=404, code=404)
        self.project_repository.delete_member(member)
        SystemService(self.db).record_operation(operator, "删除项目成员", "project_member", member.id, f"项目 {project_id} 删除成员")
        self.db.commit()

    def _project_to_dict(
        self,
        project: Project,
        knowledge_base_id: int | None,
        document_count: int,
        knowledge_count: int,
    ) -> dict:
        return {
            "id": project.id,
            "name": project.name,
            "code": project.code,
            "description": project.description,
            "client": project.client,
            "manager": project.manager,
            "status": project.status,
            "progress": project.progress,
            "security_level": project.security_level,
            "created_by": project.created_by,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "knowledge_base_id": knowledge_base_id,
            "document_count": document_count,
            "knowledge_count": knowledge_count,
        }

    def _seed_default_project_categories(self, project_id: int, created_by: int | None) -> None:
        defaults = {
            "设计资料": ["设计输入", "设计计算", "设计评审"],
            "实施资料": ["会议纪要", "现场记录", "变更资料"],
            "交付资料": ["验收资料", "运维手册", "归档文件"],
        }
        for group_index, (group_name, child_names) in enumerate(defaults.items(), start=1):
            parent = KnowledgeCategory(
                scope_type="project",
                project_id=project_id,
                parent_id=None,
                name=group_name,
                code=f"project-{project_id}-{group_index}",
                sort_order=group_index * 10,
                enabled=True,
                created_by=created_by,
            )
            self.db.add(parent)
            self.db.flush()
            for child_index, child_name in enumerate(child_names, start=1):
                self.db.add(
                    KnowledgeCategory(
                        scope_type="project",
                        project_id=project_id,
                        parent_id=parent.id,
                        name=child_name,
                        code=f"{parent.code}-{child_index}",
                        sort_order=child_index * 10,
                        enabled=True,
                        created_by=created_by,
                    )
                )
