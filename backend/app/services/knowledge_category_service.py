"""Knowledge category service."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.project_directory_template import DEFAULT_PROJECT_DIRECTORY_TEMPLATE
from app.core.security_levels import (
    DEFAULT_SECURITY_LEVEL,
    allowed_security_levels,
    ensure_security_level_access,
    normalize_security_level,
    user_max_security_level,
)
from app.models.knowledge_category import KnowledgeCategory
from app.models.user import User
from app.repositories.knowledge_category_repository import KnowledgeCategoryRepository
from app.schemas.knowledge_category import KnowledgeCategoryCreate, KnowledgeCategoryUpdate
from app.services.project_service import ProjectService
from app.services.system_service import SystemService

logger = logging.getLogger(__name__)
_UNSET_PARENT = object()

VALID_CATEGORY_SCOPES = {"base", "project"}


class KnowledgeCategoryService:
    """知识分类/项目资料目录服务。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = KnowledgeCategoryRepository(db)

    def list_tree(
        self,
        user: User,
        scope_type: str,
        project_id: int | None = None,
        *,
        keyword: str | None = None,
        document_status: str | None = None,
        security_level: str | None = None,
        parse_status: str | None = None,
        index_status: str | None = None,
    ) -> list[dict]:
        """查询分类树。"""

        normalized_project_id = self._normalize_scope(
            scope_type,
            project_id,
            user,
            permission_codes=(
                "project:view",
                "project:directory:create",
                "project:directory:edit",
                "project:directory:delete",
                "project:directory:create",
                "project:view",
                "project:view",
                "project:view",
                "project",
            ),
        )
        categories = self.repository.list_by_scope(scope_type, normalized_project_id)
        direct_counts = self.repository.count_documents_by_category(
            [category.id for category in categories],
            security_levels=allowed_security_levels(user_max_security_level(user)),
            keyword=keyword,
            document_status=document_status,
            security_level=security_level,
            parse_status=parse_status,
            index_status=index_status,
        )
        return self._build_tree(categories, direct_counts)

    def create_category(self, payload: KnowledgeCategoryCreate, operator: User) -> KnowledgeCategory:
        """创建知识分类或项目目录。"""

        project_id = self._normalize_scope(payload.scope_type, payload.project_id, operator, permission_codes=("project:directory:create",))
        self._ensure_parent_matches_scope(payload.parent_id, payload.scope_type, project_id)
        unique_parent_id = payload.parent_id if payload.scope_type == "project" else _UNSET_PARENT
        self._ensure_code_unique(payload.scope_type, payload.code, project_id, parent_id=unique_parent_id)
        default_security_level = normalize_security_level(payload.default_security_level, default=DEFAULT_SECURITY_LEVEL)
        ensure_security_level_access(operator, default_security_level)

        category = KnowledgeCategory(
            scope_type=payload.scope_type,
            project_id=project_id,
            parent_id=payload.parent_id,
            name=payload.name.strip(),
            code=payload.code.strip(),
            description=payload.description,
            sort_order=payload.sort_order,
            enabled=payload.enabled,
            default_security_level=default_security_level,
            is_deleted=False,
            created_by=operator.id,
        )
        self.repository.add(category)
        action = "新建项目目录" if category.scope_type == "project" else "创建知识分类"
        SystemService(self.db).record_operation(operator, action, "knowledge_category", category.id, f"{action} {category.name}")
        self.db.commit()
        logger.info("knowledge category created: category_id=%s scope=%s", category.id, category.scope_type)
        return category

    def update_category(self, category_id: int, payload: KnowledgeCategoryUpdate, operator: User) -> KnowledgeCategory:
        """更新知识分类或项目目录。"""

        category = self.get_category(category_id)
        self._normalize_scope(category.scope_type, category.project_id, operator, permission_codes=("project:directory:edit",))

        parent_changed = False
        if payload.parent_id is not None:
            if payload.parent_id == category.id:
                raise AppException("分类不能将自身设置为父级")
            self._ensure_parent_matches_scope(payload.parent_id, category.scope_type, category.project_id)
            if category.id in self.descendant_ids(payload.parent_id):
                raise AppException("分类不能移动到自身子级下")
            parent_changed = payload.parent_id != category.parent_id
            category.parent_id = payload.parent_id
        elif "parent_id" in payload.model_fields_set:
            parent_changed = category.parent_id is not None
            category.parent_id = None

        if payload.code is not None and payload.code.strip() != category.code:
            self._ensure_code_unique(
                category.scope_type,
                payload.code.strip(),
                category.project_id,
                exclude_id=category.id,
                parent_id=category.parent_id if category.scope_type == "project" else _UNSET_PARENT,
            )
            category.code = payload.code.strip()
        elif parent_changed:
            self._ensure_code_unique(
                category.scope_type,
                category.code,
                category.project_id,
                exclude_id=category.id,
                parent_id=category.parent_id if category.scope_type == "project" else _UNSET_PARENT,
            )
        if payload.name is not None:
            category.name = payload.name.strip()
        if payload.description is not None:
            category.description = payload.description
        if payload.sort_order is not None:
            category.sort_order = payload.sort_order
        if payload.enabled is not None:
            category.enabled = payload.enabled
        if payload.default_security_level is not None:
            default_security_level = normalize_security_level(payload.default_security_level, default=category.default_security_level)
            ensure_security_level_access(operator, default_security_level)
            category.default_security_level = default_security_level

        action = "编辑项目目录" if category.scope_type == "project" else "编辑知识分类"
        SystemService(self.db).record_operation(operator, action, "knowledge_category", category.id, f"{action} {category.name}")
        self.db.commit()
        logger.info("knowledge category updated: category_id=%s", category.id)
        return category

    def delete_category(self, category_id: int, operator: User) -> None:
        """软删除知识分类或项目目录。"""

        category = self.get_category(category_id)
        self._normalize_scope(category.scope_type, category.project_id, operator, permission_codes=("project:directory:delete",))
        if self.repository.count_children(category.id) > 0:
            raise AppException("目录下存在子目录，请先调整子目录")
        if self.repository.count_documents(category.id) > 0:
            raise AppException("目录下存在文件，请先迁移文件或更换目录")

        category.is_deleted = True
        category.deleted_at = datetime.utcnow()
        category.enabled = False
        action = "删除项目目录" if category.scope_type == "project" else "删除知识分类"
        SystemService(self.db).record_operation(operator, action, "knowledge_category", category_id, action)
        self.db.commit()
        logger.info("knowledge category soft deleted: category_id=%s", category_id)

    def init_default_project_template(self, project_id: int, operator: User) -> dict[str, int]:
        """为项目初始化默认资料目录模板，同级目录编码已存在时不会重复创建。"""

        ProjectService(self.db).ensure_project_access(project_id, operator, ("project:directory:create",))
        existing = {
            (category.parent_id, category.code): category
            for category in self.repository.list_by_scope("project", project_id, include_deleted=False)
        }
        created_count = 0
        for group_index, (root_code, root_name, children) in enumerate(DEFAULT_PROJECT_DIRECTORY_TEMPLATE, start=1):
            parent = existing.get((None, root_code))
            if parent is None:
                parent = KnowledgeCategory(
                    scope_type="project",
                    project_id=project_id,
                    parent_id=None,
                    name=root_name,
                    code=root_code,
                    sort_order=group_index * 100,
                    enabled=True,
                    default_security_level=DEFAULT_SECURITY_LEVEL,
                    is_deleted=False,
                    created_by=operator.id,
                )
                self.repository.add(parent)
                existing[(None, root_code)] = parent
                created_count += 1
            for child_index, (child_code, child_name) in enumerate(children, start=1):
                if (parent.id, child_code) in existing:
                    continue
                child = KnowledgeCategory(
                    scope_type="project",
                    project_id=project_id,
                    parent_id=parent.id,
                    name=child_name,
                    code=child_code,
                    sort_order=group_index * 100 + child_index,
                    enabled=True,
                    default_security_level=DEFAULT_SECURITY_LEVEL,
                    is_deleted=False,
                    created_by=operator.id,
                )
                self.repository.add(child)
                existing[(parent.id, child_code)] = child
                created_count += 1
        SystemService(self.db).record_operation(operator, "初始化项目目录模板", "project", project_id, f"新增目录 {created_count} 个")
        self.db.commit()
        logger.info("project directory template initialized: project_id=%s created=%s", project_id, created_count)
        return {"created_count": created_count}

    def get_category(self, category_id: int) -> KnowledgeCategory:
        """查询分类详情。"""

        category = self.repository.get(category_id)
        if not category:
            raise AppException("知识分类不存在", status_code=404, code=404)
        return category

    def validate_for_document(
        self,
        category_id: int,
        knowledge_type: str,
        project_id: int | None,
        operator: User,
    ) -> KnowledgeCategory:
        """校验文档分类是否可用。"""

        category = self.get_category(category_id)
        if not category.enabled:
            raise AppException("知识分类已停用")
        expected_project_id = self._normalize_scope(knowledge_type, project_id, operator)
        if category.scope_type != knowledge_type or category.project_id != expected_project_id:
            raise AppException("文档分类与知识范围不匹配")
        return category

    def category_path(self, category_id: int | None) -> str | None:
        """获取分类路径。"""

        if category_id is None:
            return None
        current = self.repository.get(category_id, include_deleted=True)
        if not current:
            return None
        names: list[str] = []
        while current:
            names.append(current.name)
            current = self.repository.get(current.parent_id, include_deleted=True) if current.parent_id is not None else None
        return " / ".join(reversed(names))

    def category_name(self, category_id: int | None) -> str | None:
        """获取分类名称。"""

        if category_id is None:
            return None
        category = self.repository.get(category_id, include_deleted=True)
        return category.name if category else None

    def descendant_ids(self, category_id: int | None) -> list[int]:
        """查询分类及所有未删除子孙分类 ID。"""

        if category_id is None:
            return []
        category = self.get_category(category_id)
        categories = self.repository.list_by_scope(category.scope_type, category.project_id)
        children_by_parent: dict[int | None, list[KnowledgeCategory]] = {}
        for item in categories:
            children_by_parent.setdefault(item.parent_id, []).append(item)

        result: list[int] = []
        stack = [category]
        while stack:
            current = stack.pop()
            result.append(current.id)
            stack.extend(children_by_parent.get(current.id, []))
        return result

    def _normalize_scope(
        self,
        scope_type: str,
        project_id: int | None,
        user: User,
        permission_codes: tuple[str, ...] | None = None,
    ) -> int | None:
        """校验并归一化分类范围。"""

        if scope_type not in VALID_CATEGORY_SCOPES:
            raise AppException("分类范围必须为 base 或 project")
        if scope_type == "base":
            return None
        if project_id is None:
            raise AppException("项目目录必须指定 project_id")
        ProjectService(self.db).ensure_project_access(project_id, user, permission_codes or ("project:view", "project"))
        return project_id

    def _ensure_parent_matches_scope(self, parent_id: int | None, scope_type: str, project_id: int | None) -> None:
        """校验父分类与当前分类范围一致。"""

        if parent_id is None:
            return
        parent = self.get_category(parent_id)
        if parent.scope_type != scope_type or parent.project_id != project_id:
            raise AppException("父分类与当前分类范围不一致")

    def _ensure_code_unique(
        self,
        scope_type: str,
        code: str,
        project_id: int | None,
        exclude_id: int | None = None,
        parent_id: int | None | object = _UNSET_PARENT,
    ) -> None:
        """校验目录编码唯一。

        项目资料目录模板允许不同一级目录下复用 01/02 等编码，因此编码唯一性按同一父目录限定。
        """

        if parent_id is _UNSET_PARENT:
            duplicate = self.repository.get_by_code(scope_type, code, project_id, exclude_id)
        else:
            duplicate = self.repository.get_by_code(scope_type, code, project_id, exclude_id, parent_id)
        if duplicate:
            message = "同一目录下编码已存在" if scope_type == "project" else "分类编码已存在"
            raise AppException(message)

    def _build_tree(self, categories: list[KnowledgeCategory], direct_counts: dict[int, int]) -> list[dict]:
        """将平铺分类组装为无限层级树。"""

        node_map: dict[int, dict] = {}
        for category in categories:
            node_map[category.id] = {
                "id": category.id,
                "scope_type": category.scope_type,
                "project_id": category.project_id,
                "parent_id": category.parent_id,
                "name": category.name,
                "code": category.code,
                "description": category.description,
                "sort_order": category.sort_order,
                "enabled": category.enabled,
                "default_security_level": category.default_security_level,
                "is_deleted": category.is_deleted,
                "deleted_at": category.deleted_at,
                "document_count": direct_counts.get(category.id, 0),
                "total_document_count": direct_counts.get(category.id, 0),
                "children": [],
                "created_by": category.created_by,
                "created_at": category.created_at,
                "updated_at": category.updated_at,
            }

        roots: list[dict] = []
        for category in categories:
            node = node_map[category.id]
            parent = node_map.get(category.parent_id) if category.parent_id is not None else None
            if parent:
                parent["children"].append(node)
            else:
                roots.append(node)

        def accumulate(node: dict) -> int:
            total = node["document_count"]
            for child in node["children"]:
                total += accumulate(child)
            node["total_document_count"] = total
            return total

        for root in roots:
            accumulate(root)
        return roots
