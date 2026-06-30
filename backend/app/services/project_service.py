"""Project service."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.data_scope import enabled_role_data_scopes
from app.core.exceptions import AppException
from app.core.project_directory_template import DEFAULT_PROJECT_DIRECTORY_TEMPLATE
from app.core.security_levels import (
    DEFAULT_SECURITY_LEVEL,
    allowed_security_levels,
    ensure_security_level_access,
    normalize_security_level,
    user_max_security_level,
)
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_category import KnowledgeCategory
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.repositories.chat_repository import ChatRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.schemas.project import PROJECT_STATUS_OPTIONS, ProjectCreate, ProjectMemberCreate, ProjectUpdate
from app.services.project_access_service import ProjectAccessService
from app.services.system_service import SystemService

PROJECT_STATUS_TO_LEGACY = {
    "待启动": "pending",
    "进行中": "active",
    "已完成": "completed",
    "已暂停": "archived",
}
LEGACY_STATUS_TO_PROJECT = {
    "pending": "待启动",
    "active": "进行中",
    "completed": "已完成",
    "archived": "已暂停",
    "inactive": "已暂停",
}
REVIEW_PENDING_STATUSES = {"draft", "reviewing", "rejected"}


class ProjectService:
    """项目服务，集中处理项目业务和项目级访问控制。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.project_repository = ProjectRepository(db)
        self.kb_repository = KnowledgeBaseRepository(db)
        self.access_service = ProjectAccessService(db)

    def user_is_admin(self, user: User) -> bool:
        return self.access_service.is_admin(user)

    def ensure_project_access(
        self,
        project_id: int,
        user: User,
        permission_codes: tuple[str, ...] = ("project:view", "project"),
    ) -> Project:
        """校验项目访问权限并返回项目对象。"""

        return self.access_service.ensure_project_access(project_id, user, permission_codes=permission_codes)

    def list_projects(
        self,
        user: User,
        keyword: str | None = None,
        project_status: str | None = None,
        security_level: str | None = None,
    ) -> list[dict]:
        self.access_service.ensure_permission(user, "project:view", "project", message="无权查看项目列表")
        target_status = self._normalize_project_status(project_status) if project_status else None
        target_security = normalize_security_level(security_level, default="") if security_level else None
        max_security_level = user_max_security_level(user)
        accessible_security_levels = allowed_security_levels(max_security_level)
        user_department = getattr(user, "department_id", None) or getattr(user, "department", None)
        rows = self.project_repository.list_with_stats(
            user_id=user.id,
            user_department=str(user_department) if user_department else None,
            is_admin=self.access_service.is_admin(user),
            data_scopes=enabled_role_data_scopes(user),
            project_security_levels=accessible_security_levels,
            document_security_levels=accessible_security_levels,
            include_document_stats=self.access_service.has_permission(
                user,
                "project:view",
                "project:view",
                "knowledge:view",
            ),
            pending_review_statuses=REVIEW_PENDING_STATUSES,
            keyword=keyword,
            project_status=target_status,
            security_level=target_security,
        )
        return [
            self._project_to_dict(
                row.project,
                row.knowledge_base_id,
                document_count=row.document_count,
                knowledge_count=row.knowledge_count,
                parsed_document_count=row.parsed_document_count,
                indexed_document_count=row.indexed_document_count,
                pending_review_document_count=row.pending_review_document_count,
            )
            for row in rows
        ]

    def get_project(self, project_id: int, user: User) -> dict:
        project = self.ensure_project_access(project_id, user, ("project:view", "project:view", "project"))
        kb = self.kb_repository.get_project_base(project.id)
        return self._project_to_dict(project, kb.id if kb else None, **self._project_document_stats(project.id, user))

    def get_project_overview(self, project_id: int, user: User) -> dict:
        project = self.ensure_project_access(project_id, user, ("project:view", "project:view", "project"))
        kb = self.kb_repository.get_project_base(project.id)
        doc_repo = DocumentRepository(self.db)
        documents = [
            item
            for item in doc_repo.list(project_id=project.id)
            if self.access_service.can_access_document(item, user, permission_codes=("project:view",))
        ]
        categories = list(
            self.db.query(KnowledgeCategory)
            .filter(
                KnowledgeCategory.scope_type == "project",
                KnowledgeCategory.project_id == project.id,
                KnowledgeCategory.is_deleted.is_(False),
            )
            .order_by(KnowledgeCategory.sort_order, KnowledgeCategory.id)
            .all()
        )
        category_by_id = {category.id: category for category in categories}
        root_counts: dict[int, int] = {category.id: 0 for category in categories if category.parent_id is None}
        for document in documents:
            root_id = self._root_category_id(document.category_id or document.directory_id, category_by_id)
            if root_id is not None:
                root_counts[root_id] = root_counts.get(root_id, 0) + 1

        recent_documents = sorted(documents, key=lambda item: item.created_at, reverse=True)[:5]
        uploader_ids = {
            uploader_id
            for document in recent_documents
            if (uploader_id := document.upload_user_id or document.created_by) is not None
        }
        uploader_by_id = {user.id: user for user in UserRepository(self.db).list_by_ids(uploader_ids)}
        overview = self._project_to_dict(project, kb.id if kb else None, **self._document_counts(documents))
        overview.update(
            {
                "qa_count": ChatRepository(self.db).count_project_answers(project.id),
                "first_level_directory_stats": [
                    {
                        "directory_id": category.id,
                        "directory_code": category.code,
                        "directory_name": category.name,
                        "document_count": root_counts.get(category.id, 0),
                    }
                    for category in categories
                    if category.parent_id is None
                ],
                "recent_documents": [
                    self._overview_document_to_dict(document, category_by_id, uploader_by_id)
                    for document in recent_documents
                ],
                "project_chat_enabled": self.access_service.has_permission(user, "project:chat"),
            }
        )
        return overview

    def create_project(self, payload: ProjectCreate, operator: User) -> dict:
        if self.project_repository.get_by_code(payload.code):
            raise AppException("项目编号已存在")
        security_level = normalize_security_level(payload.security_level, default=DEFAULT_SECURITY_LEVEL)
        ensure_security_level_access(operator, security_level)
        project_status = self._normalize_project_status(payload.status)
        project_short_name = self._clean_text(payload.project_short_name) or self._clean_text(payload.name)
        customer_name = self._clean_text(payload.client)
        owner_name = self._clean_text(payload.manager)
        description = self._clean_text(payload.description)
        self._validate_required_basic_fields(
            project_name=payload.name,
            project_code=payload.code,
            project_short_name=project_short_name,
            customer_name=customer_name,
            owner_name=owner_name,
            project_status=project_status,
            security_level=security_level,
            description=description,
        )

        project = Project(
            name=self._clean_text(payload.name) or payload.name,
            code=self._clean_text(payload.code) or payload.code,
            project_short_name=project_short_name,
            project_english_name=self._clean_text(payload.project_english_name),
            description=description,
            client=customer_name,
            customer_name=customer_name,
            manager=owner_name,
            owner_id=payload.owner_id,
            owner_name=owner_name,
            status=self._legacy_project_status(project_status),
            project_status=project_status,
            progress=payload.progress,
            security_level=security_level,
            project_type=self._clean_text(payload.project_type),
            project_stage=self._clean_text(payload.project_stage),
            raw_material_type=self._clean_text(payload.raw_material_type),
            capacity=self._clean_text(payload.capacity),
            process_route=self._clean_text(payload.process_route),
            main_products=self._clean_text(payload.main_products),
            scope_description=self._clean_text(payload.scope_description),
            deliverables=self._clean_text(payload.deliverables),
            department_id=payload.department_id,
            created_by=operator.id,
            is_deleted=False,
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
        return self._project_to_dict(project, kb.id, **self._empty_document_counts())

    def update_project(self, project_id: int, payload: ProjectUpdate, operator: User) -> dict:
        project = self.ensure_project_access(project_id, operator, ("project:edit", "project:edit"))
        fields_set = payload.model_fields_set
        if "code" in fields_set and payload.code and payload.code != project.code:
            existing = self.project_repository.get_by_code(payload.code)
            if existing and existing.id != project.id:
                raise AppException("项目编号已存在")
            project.code = self._clean_text(payload.code) or payload.code
        if "name" in fields_set and payload.name is not None:
            project.name = self._clean_text(payload.name) or payload.name
        if "security_level" in fields_set and payload.security_level is not None:
            project.security_level = normalize_security_level(payload.security_level, default=project.security_level)
            ensure_security_level_access(operator, project.security_level)
        if "status" in fields_set and payload.status is not None:
            project.project_status = self._normalize_project_status(payload.status)
            project.status = self._legacy_project_status(project.project_status)

        self._apply_nullable_project_fields(project, payload, fields_set)
        project_status = self._project_status_label(project)
        project.project_status = project_status
        project.status = self._legacy_project_status(project_status)
        self._validate_required_basic_fields(
            project_name=project.name,
            project_code=project.code,
            project_short_name=project.project_short_name,
            customer_name=project.customer_name or project.client,
            owner_name=project.owner_name or project.manager,
            project_status=project_status,
            security_level=project.security_level,
            description=project.description,
        )

        SystemService(self.db).record_operation(operator, "编辑项目", "project", project.id, f"编辑项目 {project.name}")
        self.db.commit()
        return self.get_project(project_id, operator)

    def delete_project(self, project_id: int, operator: User) -> None:
        project = self.ensure_project_access(project_id, operator, ("project:delete",))
        project.is_deleted = True
        project.deleted_at = datetime.utcnow()
        SystemService(self.db).record_operation(operator, "删除项目", "project", project_id, "软删除项目")
        self.db.commit()

    def list_members(self, project_id: int, operator: User) -> list[ProjectMember]:
        self.ensure_project_access(project_id, operator, ("project:view", "project:view", "project"))
        return self.project_repository.list_members(project_id)

    def add_member(self, project_id: int, payload: ProjectMemberCreate, operator: User) -> ProjectMember:
        self.ensure_project_access(project_id, operator, ("project:edit", "project:edit"))
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
        self.ensure_project_access(project_id, operator, ("project:edit", "project:edit"))
        member = self.project_repository.get_member(project_id, user_id)
        if not member:
            raise AppException("项目成员不存在", status_code=404, code=404)
        self.project_repository.delete_member(member)
        SystemService(self.db).record_operation(operator, "删除项目成员", "project_member", member.id, f"项目 {project_id} 删除成员")
        self.db.commit()

    def _apply_nullable_project_fields(self, project: Project, payload: ProjectUpdate, fields_set: set[str]) -> None:
        text_fields = [
            "project_short_name",
            "project_english_name",
            "description",
            "project_type",
            "project_stage",
            "raw_material_type",
            "capacity",
            "process_route",
            "main_products",
            "scope_description",
            "deliverables",
        ]
        for field in text_fields:
            if field in fields_set:
                setattr(project, field, self._clean_text(getattr(payload, field)))
        if "client" in fields_set:
            project.client = self._clean_text(payload.client)
            project.customer_name = project.client
        if "manager" in fields_set:
            project.manager = self._clean_text(payload.manager)
            project.owner_name = project.manager
        if "owner_id" in fields_set:
            project.owner_id = payload.owner_id
        if "department_id" in fields_set:
            project.department_id = payload.department_id
        if "progress" in fields_set and payload.progress is not None:
            project.progress = payload.progress

    def _project_to_dict(
        self,
        project: Project,
        knowledge_base_id: int | None,
        document_count: int,
        knowledge_count: int,
        parsed_document_count: int,
        indexed_document_count: int,
        pending_review_document_count: int,
    ) -> dict:
        project_status = self._project_status_label(project)
        customer_name = project.customer_name or project.client
        owner_name = project.owner_name or project.manager
        return {
            "id": project.id,
            "name": project.name,
            "code": project.code,
            "project_name": project.name,
            "project_code": project.code,
            "project_short_name": project.project_short_name or project.name,
            "project_english_name": project.project_english_name,
            "description": project.description,
            "client": project.client,
            "customer_name": customer_name,
            "manager": project.manager,
            "owner_id": project.owner_id,
            "owner_name": owner_name,
            "status": project.status or self._legacy_project_status(project_status),
            "project_status": project_status,
            "progress": project.progress,
            "security_level": project.security_level,
            "project_type": project.project_type,
            "project_stage": project.project_stage,
            "raw_material_type": project.raw_material_type,
            "capacity": project.capacity,
            "process_route": project.process_route,
            "main_products": project.main_products,
            "scope_description": project.scope_description,
            "deliverables": project.deliverables,
            "department_id": project.department_id,
            "created_by": project.created_by,
            "is_deleted": project.is_deleted,
            "deleted_at": project.deleted_at,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "knowledge_base_id": knowledge_base_id,
            "document_count": document_count,
            "knowledge_count": knowledge_count,
            "parsed_document_count": parsed_document_count,
            "indexed_document_count": indexed_document_count,
            "pending_review_document_count": pending_review_document_count,
        }

    def _document_counts(self, documents: list[Document]) -> dict[str, int]:
        return {
            "document_count": len(documents),
            "knowledge_count": sum(1 for doc in documents if doc.index_status == "indexed"),
            "parsed_document_count": sum(1 for doc in documents if doc.parse_status == "success"),
            "indexed_document_count": sum(1 for doc in documents if doc.index_status == "indexed"),
            "pending_review_document_count": sum(
                1
                for doc in documents
                if doc.document_status == "pending_review" or doc.review_status in REVIEW_PENDING_STATUSES
            ),
        }

    def _empty_document_counts(self) -> dict[str, int]:
        return {
            "document_count": 0,
            "knowledge_count": 0,
            "parsed_document_count": 0,
            "indexed_document_count": 0,
            "pending_review_document_count": 0,
        }

    def _project_document_stats(self, project_id: int, user: User) -> dict[str, int]:
        return self.project_repository.document_stats_for_project(
            project_id,
            document_security_levels=allowed_security_levels(user_max_security_level(user)),
            include_document_stats=self.access_service.has_permission(
                user,
                "project:view",
                "project:view",
                "knowledge:view",
            ),
            pending_review_statuses=REVIEW_PENDING_STATUSES,
        )

    def _root_category_id(self, category_id: int | None, category_by_id: dict[int, KnowledgeCategory]) -> int | None:
        current = category_by_id.get(category_id) if category_id is not None else None
        while current and current.parent_id is not None and current.parent_id in category_by_id:
            current = category_by_id[current.parent_id]
        return current.id if current else None

    def _overview_document_to_dict(
        self,
        document: Document,
        category_by_id: dict[int, KnowledgeCategory],
        uploader_by_id: dict[int, User],
    ) -> dict:
        category_id = document.category_id or document.directory_id
        category = category_by_id.get(category_id) if category_id is not None else None
        uploader_id = document.upload_user_id or document.created_by
        uploader = uploader_by_id.get(uploader_id) if uploader_id is not None else None
        return {
            "id": document.id,
            "document_name": document.document_name or document.file_name,
            "file_name": document.file_name,
            "file_type": document.file_type,
            "file_size": document.file_size,
            "directory_id": category_id,
            "directory_name": category.name if category else None,
            "status": document.status,
            "security_level": document.security_level,
            "parse_status": document.parse_status,
            "index_status": document.index_status,
            "upload_user_id": uploader_id,
            "uploader_name": uploader.real_name if uploader else None,
            "uploader_username": uploader.username if uploader else None,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
        }

    def _project_status_label(self, project: Project) -> str:
        return self._normalize_project_status(project.project_status or project.status)

    def _normalize_project_status(self, value: str | None) -> str:
        status = (value or "").strip()
        if status in PROJECT_STATUS_OPTIONS:
            return status
        return LEGACY_STATUS_TO_PROJECT.get(status, "进行中")

    def _legacy_project_status(self, project_status: str) -> str:
        return PROJECT_STATUS_TO_LEGACY.get(project_status, "active")

    def _validate_required_basic_fields(
        self,
        *,
        project_name: str | None,
        project_code: str | None,
        project_short_name: str | None,
        customer_name: str | None,
        owner_name: str | None,
        project_status: str | None,
        security_level: str | None,
        description: str | None,
    ) -> None:
        required_fields: list[tuple[str, Any]] = [
            ("项目名称", project_name),
            ("项目编号", project_code),
            ("项目简称", project_short_name),
            ("客户名称", customer_name),
            ("项目负责人", owner_name),
            ("项目状态", project_status),
            ("项目密级", security_level),
            ("项目简介", description),
        ]
        missing = [name for name, value in required_fields if not self._clean_text(value)]
        if missing:
            raise AppException(f"项目基本信息缺少必填字段：{', '.join(missing)}")

    def _clean_text(self, value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip()
            return text or None
        return value

    def _seed_default_project_categories(self, project_id: int, created_by: int | None) -> None:
        for group_index, (group_code, group_name, child_items) in enumerate(DEFAULT_PROJECT_DIRECTORY_TEMPLATE, start=1):
            parent = KnowledgeCategory(
                scope_type="project",
                project_id=project_id,
                parent_id=None,
                name=group_name,
                code=group_code,
                sort_order=group_index * 100,
                enabled=True,
                default_security_level=DEFAULT_SECURITY_LEVEL,
                is_deleted=False,
                created_by=created_by,
            )
            self.db.add(parent)
            self.db.flush()
            for child_index, (child_code, child_name) in enumerate(child_items, start=1):
                self.db.add(
                    KnowledgeCategory(
                        scope_type="project",
                        project_id=project_id,
                        parent_id=parent.id,
                        name=child_name,
                        code=child_code,
                        sort_order=group_index * 100 + child_index,
                        enabled=True,
                        default_security_level=DEFAULT_SECURITY_LEVEL,
                        is_deleted=False,
                        created_by=created_by,
                    )
                )
