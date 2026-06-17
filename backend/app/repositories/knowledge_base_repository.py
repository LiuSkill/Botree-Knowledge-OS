"""
Knowledge Base Repository

负责：
1. 知识库数据库访问
2. 基础知识和项目知识查询
3. 支持文档上传前的知识库校验
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge_base import KnowledgeBase, KnowledgeBasePermission


class KnowledgeBaseRepository:
    """
    知识库仓储

    职责：
    - 知识库 CRUD
    - 查询项目绑定知识库
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, kb_type: str | None = None, project_id: int | None = None) -> list[KnowledgeBase]:
        """查询知识库列表。"""

        stmt = select(KnowledgeBase).order_by(KnowledgeBase.id.desc())
        if kb_type:
            stmt = stmt.where(KnowledgeBase.type == kb_type)
        if project_id is not None:
            stmt = stmt.where(KnowledgeBase.project_id == project_id)
        return list(self.db.scalars(stmt).all())

    def get(self, kb_id: int) -> KnowledgeBase | None:
        """按 ID 查询知识库。"""

        return self.db.get(KnowledgeBase, kb_id)

    def get_by_code(self, code: str) -> KnowledgeBase | None:
        """按编码查询知识库。"""

        return self.db.scalar(select(KnowledgeBase).where(KnowledgeBase.code == code))

    def get_project_base(self, project_id: int) -> KnowledgeBase | None:
        """查询项目绑定知识库。"""

        return self.db.scalar(
            select(KnowledgeBase).where(KnowledgeBase.type == "project", KnowledgeBase.project_id == project_id)
        )

    def add(self, knowledge_base: KnowledgeBase) -> KnowledgeBase:
        """新增知识库。"""

        self.db.add(knowledge_base)
        self.db.flush()
        return knowledge_base

    def delete(self, knowledge_base: KnowledgeBase) -> None:
        """删除知识库。"""

        self.db.delete(knowledge_base)
        self.db.flush()

    def list_permissions(self) -> list[KnowledgeBasePermission]:
        """查询知识库授权记录。"""

        return list(self.db.scalars(select(KnowledgeBasePermission).order_by(KnowledgeBasePermission.id.desc())).all())
