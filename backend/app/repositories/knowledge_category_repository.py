"""Knowledge category repository."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.knowledge_category import KnowledgeCategory

_UNSET_PARENT = object()


class KnowledgeCategoryRepository:
    """知识分类/项目资料目录仓储。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_scope(
        self,
        scope_type: str,
        project_id: int | None = None,
        include_deleted: bool = False,
    ) -> list[KnowledgeCategory]:
        """按范围查询分类。"""

        stmt = (
            select(KnowledgeCategory)
            .where(KnowledgeCategory.scope_type == scope_type)
            .order_by(KnowledgeCategory.sort_order, KnowledgeCategory.id)
        )
        if not include_deleted:
            stmt = stmt.where(KnowledgeCategory.is_deleted.is_(False))
        if project_id is None:
            stmt = stmt.where(KnowledgeCategory.project_id.is_(None))
        else:
            stmt = stmt.where(KnowledgeCategory.project_id == project_id)
        return list(self.db.scalars(stmt).all())

    def get(self, category_id: int, include_deleted: bool = False) -> KnowledgeCategory | None:
        """按 ID 查询分类。"""

        category = self.db.get(KnowledgeCategory, category_id)
        if category and category.is_deleted and not include_deleted:
            return None
        return category

    def get_by_code(
        self,
        scope_type: str,
        code: str,
        project_id: int | None = None,
        exclude_id: int | None = None,
        parent_id: int | None | object = _UNSET_PARENT,
    ) -> KnowledgeCategory | None:
        """查询未删除分类编码，可按父级目录进一步限定。"""

        stmt = select(KnowledgeCategory).where(
            KnowledgeCategory.scope_type == scope_type,
            KnowledgeCategory.code == code,
            KnowledgeCategory.is_deleted.is_(False),
        )
        if project_id is None:
            stmt = stmt.where(KnowledgeCategory.project_id.is_(None))
        else:
            stmt = stmt.where(KnowledgeCategory.project_id == project_id)
        if parent_id is not _UNSET_PARENT:
            if parent_id is None:
                stmt = stmt.where(KnowledgeCategory.parent_id.is_(None))
            else:
                stmt = stmt.where(KnowledgeCategory.parent_id == parent_id)
        if exclude_id is not None:
            stmt = stmt.where(KnowledgeCategory.id != exclude_id)
        return self.db.scalar(stmt)

    def add(self, category: KnowledgeCategory) -> KnowledgeCategory:
        """新增分类。"""

        self.db.add(category)
        self.db.flush()
        return category

    def delete(self, category: KnowledgeCategory) -> None:
        """物理删除分类，仅保留给维护场景。业务删除请使用 Service 软删除。"""

        self.db.delete(category)
        self.db.flush()

    def count_children(self, category_id: int) -> int:
        """统计未删除直接子分类数量。"""

        return int(
            self.db.scalar(
                select(func.count(KnowledgeCategory.id)).where(
                    KnowledgeCategory.parent_id == category_id,
                    KnowledgeCategory.is_deleted.is_(False),
                )
            )
            or 0
        )

    def count_documents(self, category_id: int) -> int:
        """统计直接挂载到分类的文档数量。"""

        category_ref = func.coalesce(Document.category_id, Document.directory_id)
        return int(
            self.db.scalar(
                select(func.count(Document.id)).where(
                    category_ref == category_id,
                    Document.is_deleted.is_(False),
                )
            )
            or 0
        )

    def count_documents_by_category(
        self,
        category_ids: list[int],
        security_levels: list[str] | None = None,
    ) -> dict[int, int]:
        """批量统计分类文档数量。"""

        if not category_ids:
            return {}
        category_ref = func.coalesce(Document.category_id, Document.directory_id)
        stmt = (
            select(category_ref.label("category_id"), func.count(Document.id))
            .where(category_ref.in_(category_ids), Document.is_deleted.is_(False))
            .group_by(category_ref)
        )
        if security_levels is not None:
            stmt = stmt.where(Document.security_level.in_(security_levels))
        return {int(category_id): int(count) for category_id, count in self.db.execute(stmt).all() if category_id is not None}
