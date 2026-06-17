"""
Knowledge Category Service

负责：
1. 管理企业知识和项目资料分类树
2. 校验分类范围、父子关系和项目隔离边界
3. 为文档上传、筛选和构建进度页面提供分类路径
"""

import logging

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.models.knowledge_category import KnowledgeCategory
from app.models.user import User
from app.repositories.knowledge_category_repository import KnowledgeCategoryRepository
from app.schemas.knowledge_category import KnowledgeCategoryCreate, KnowledgeCategoryUpdate
from app.services.project_service import ProjectService
from app.services.system_service import SystemService

logger = logging.getLogger(__name__)

VALID_CATEGORY_SCOPES = {"base", "project"}


class KnowledgeCategoryService:
    """
    知识分类服务

    职责：
    - 维护无限层级分类树
    - 确保企业分类与项目分类互不串用
    - 保护已有文档引用的分类不被误删
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = KnowledgeCategoryRepository(db)

    def list_tree(self, user: User, scope_type: str, project_id: int | None = None) -> list[dict]:
        """
        查询分类树

        参数:
            user: 当前用户
            scope_type: 分类范围，base/project
            project_id: 项目ID，项目分类必填

        返回:
            分类树节点字典列表。
        """

        normalized_project_id = self._normalize_scope(scope_type, project_id, user)
        categories = self.repository.list_by_scope(scope_type, normalized_project_id)
        direct_counts = self.repository.count_documents_by_category([category.id for category in categories])
        return self._build_tree(categories, direct_counts)

    def create_category(self, payload: KnowledgeCategoryCreate, operator: User) -> KnowledgeCategory:
        """创建知识分类。"""

        project_id = self._normalize_scope(payload.scope_type, payload.project_id, operator)
        self._ensure_code_unique(payload.scope_type, payload.code, project_id)
        self._ensure_parent_matches_scope(payload.parent_id, payload.scope_type, project_id)

        category = KnowledgeCategory(
            scope_type=payload.scope_type,
            project_id=project_id,
            parent_id=payload.parent_id,
            name=payload.name.strip(),
            code=payload.code.strip(),
            description=payload.description,
            sort_order=payload.sort_order,
            enabled=payload.enabled,
            created_by=operator.id,
        )
        self.repository.add(category)
        SystemService(self.db).record_operation(operator, "创建知识分类", "knowledge_category", category.id, f"创建分类 {category.name}")
        self.db.commit()
        logger.info("知识分类创建完成: category_id=%s scope=%s", category.id, category.scope_type)
        return category

    def update_category(self, category_id: int, payload: KnowledgeCategoryUpdate, operator: User) -> KnowledgeCategory:
        """更新知识分类。"""

        category = self.get_category(category_id)
        self._normalize_scope(category.scope_type, category.project_id, operator)

        if payload.parent_id is not None:
            if payload.parent_id == category.id:
                raise AppException("分类不能将自身设置为父级")
            self._ensure_parent_matches_scope(payload.parent_id, category.scope_type, category.project_id)
            if category.id in self.descendant_ids(payload.parent_id):
                raise AppException("分类不能移动到自身子级下")
            category.parent_id = payload.parent_id
        elif "parent_id" in payload.model_fields_set:
            category.parent_id = None

        if payload.code is not None and payload.code.strip() != category.code:
            self._ensure_code_unique(category.scope_type, payload.code.strip(), category.project_id, exclude_id=category.id)
            category.code = payload.code.strip()
        if payload.name is not None:
            category.name = payload.name.strip()
        if payload.description is not None:
            category.description = payload.description
        if payload.sort_order is not None:
            category.sort_order = payload.sort_order
        if payload.enabled is not None:
            category.enabled = payload.enabled

        SystemService(self.db).record_operation(operator, "编辑知识分类", "knowledge_category", category.id, f"编辑分类 {category.name}")
        self.db.commit()
        logger.info("知识分类更新完成: category_id=%s", category.id)
        return category

    def delete_category(self, category_id: int, operator: User) -> None:
        """删除知识分类。"""

        category = self.get_category(category_id)
        self._normalize_scope(category.scope_type, category.project_id, operator)
        if self.repository.count_children(category.id) > 0:
            raise AppException("分类下存在子分类，请先调整子分类")
        if self.repository.count_documents(category.id) > 0:
            raise AppException("分类下存在文档，请先迁移文档或禁用分类")

        self.repository.delete(category)
        SystemService(self.db).record_operation(operator, "删除知识分类", "knowledge_category", category_id, "删除知识分类")
        self.db.commit()
        logger.info("知识分类删除完成: category_id=%s", category_id)

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
        """
        校验文档分类是否可用

        参数:
            category_id: 分类ID
            knowledge_type: 文档知识类型
            project_id: 文档项目ID
            operator: 当前用户

        返回:
            合法分类。
        """

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
        current = self.repository.get(category_id)
        if not current:
            return None
        names: list[str] = []
        while current:
            names.append(current.name)
            current = self.repository.get(current.parent_id) if current.parent_id is not None else None
        return " / ".join(reversed(names))

    def category_name(self, category_id: int | None) -> str | None:
        """获取分类名称。"""

        if category_id is None:
            return None
        category = self.repository.get(category_id)
        return category.name if category else None

    def descendant_ids(self, category_id: int | None) -> list[int]:
        """查询分类及其所有子孙分类ID。"""

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

    def _normalize_scope(self, scope_type: str, project_id: int | None, user: User) -> int | None:
        """校验并归一化分类范围。"""

        if scope_type not in VALID_CATEGORY_SCOPES:
            raise AppException("分类范围必须为 base 或 project")
        if scope_type == "base":
            return None
        if project_id is None:
            raise AppException("项目分类必须指定 project_id")
        ProjectService(self.db).ensure_project_access(project_id, user)
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
    ) -> None:
        """校验同范围分类编码唯一。"""

        if self.repository.get_by_code(scope_type, code, project_id, exclude_id):
            raise AppException("分类编码已存在")

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
            """递归汇总子分类文档数量。"""

            total = node["document_count"]
            for child in node["children"]:
                total += accumulate(child)
            node["total_document_count"] = total
            return total

        for root in roots:
            accumulate(root)
        return roots
