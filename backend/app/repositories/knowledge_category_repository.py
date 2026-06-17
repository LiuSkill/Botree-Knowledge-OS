"""
Knowledge Category Repository

负责：
1. 封装知识分类表的数据库访问
2. 支持按企业范围和项目范围查询分类
3. 为服务层提供删除校验所需的子级和文档引用统计
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.knowledge_category import KnowledgeCategory


class KnowledgeCategoryRepository:
    """
    知识分类仓储

    职责：
    - 分类 CRUD
    - 同范围编码唯一性查询
    - 分类树构建所需的平铺数据查询
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_scope(self, scope_type: str, project_id: int | None = None) -> list[KnowledgeCategory]:
        """
        按范围查询分类

        参数:
            scope_type: 分类范围，base/project
            project_id: 项目ID，项目分类必填

        返回:
            分类列表。
        """

        stmt = (
            select(KnowledgeCategory)
            .where(KnowledgeCategory.scope_type == scope_type)
            .order_by(KnowledgeCategory.sort_order, KnowledgeCategory.id)
        )
        if project_id is None:
            stmt = stmt.where(KnowledgeCategory.project_id.is_(None))
        else:
            stmt = stmt.where(KnowledgeCategory.project_id == project_id)
        return list(self.db.scalars(stmt).all())

    def get(self, category_id: int) -> KnowledgeCategory | None:
        """按 ID 查询分类。"""

        return self.db.get(KnowledgeCategory, category_id)

    def get_by_code(
        self,
        scope_type: str,
        code: str,
        project_id: int | None = None,
        exclude_id: int | None = None,
    ) -> KnowledgeCategory | None:
        """
        查询同一范围内的分类编码

        参数:
            scope_type: 分类范围
            code: 分类编码
            project_id: 项目ID
            exclude_id: 编辑时排除自身ID

        返回:
            匹配的分类。
        """

        stmt = select(KnowledgeCategory).where(KnowledgeCategory.scope_type == scope_type, KnowledgeCategory.code == code)
        if project_id is None:
            stmt = stmt.where(KnowledgeCategory.project_id.is_(None))
        else:
            stmt = stmt.where(KnowledgeCategory.project_id == project_id)
        if exclude_id is not None:
            stmt = stmt.where(KnowledgeCategory.id != exclude_id)
        return self.db.scalar(stmt)

    def add(self, category: KnowledgeCategory) -> KnowledgeCategory:
        """新增分类。"""

        self.db.add(category)
        self.db.flush()
        return category

    def delete(self, category: KnowledgeCategory) -> None:
        """删除分类。"""

        self.db.delete(category)
        self.db.flush()

    def count_children(self, category_id: int) -> int:
        """统计直接子分类数量。"""

        return int(
            self.db.scalar(select(func.count(KnowledgeCategory.id)).where(KnowledgeCategory.parent_id == category_id)) or 0
        )

    def count_documents(self, category_id: int) -> int:
        """统计直接挂载到分类的文档数量。"""

        return int(self.db.scalar(select(func.count(Document.id)).where(Document.category_id == category_id)) or 0)

    def count_documents_by_category(self, category_ids: list[int]) -> dict[int, int]:
        """
        批量统计分类文档数

        参数:
            category_ids: 分类ID列表

        返回:
            分类ID到直接文档数的映射。
        """

        if not category_ids:
            return {}
        stmt = select(Document.category_id, func.count(Document.id)).where(Document.category_id.in_(category_ids)).group_by(Document.category_id)
        return {int(category_id): int(count) for category_id, count in self.db.execute(stmt).all() if category_id is not None}
