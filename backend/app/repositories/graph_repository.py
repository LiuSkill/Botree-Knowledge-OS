"""
Graph Repository

负责：
1. 读写 GraphRAG 实体和关系
2. 按文档版本清理和发布图谱数据
3. 为在线图谱检索提供关键词查询能力
"""

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.models.graph import GraphEntity, GraphRelation


class GraphRepository:
    """
    GraphRAG 仓储

    职责：
    - 管理实体和关系表
    - 保留来源追踪字段
    - 支持 MySQL 第一阶段图谱检索
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def clear_document_graph(self, document_id: int, version_no: int) -> None:
        """清理指定文档版本的 staging 图谱数据。"""

        entity_ids = list(
            self.db.scalars(
                select(GraphEntity.id).where(GraphEntity.document_id == document_id, GraphEntity.version_no == version_no)
            ).all()
        )
        if entity_ids:
            self.db.execute(
                delete(GraphRelation).where(
                    or_(
                        GraphRelation.source_entity_id.in_(entity_ids),
                        GraphRelation.target_entity_id.in_(entity_ids),
                    )
                )
            )
        self.db.execute(delete(GraphEntity).where(GraphEntity.document_id == document_id, GraphEntity.version_no == version_no))
        self.db.flush()

    def clear_all_document_graph(self, document_id: int) -> int:
        """
        物理删除文档全部版本的图谱实体和关系。

        参数:
            document_id: 文档ID。

        返回:
            删除的实体数量。
        """

        entity_ids = [
            entity_id
            for entity_id in self.db.scalars(select(GraphEntity.id).where(GraphEntity.document_id == document_id)).all()
        ]
        if entity_ids:
            self.db.execute(
                delete(GraphRelation).where(
                    or_(
                        GraphRelation.source_entity_id.in_(entity_ids),
                        GraphRelation.target_entity_id.in_(entity_ids),
                    )
                )
            )
        entity_result = self.db.execute(delete(GraphEntity).where(GraphEntity.document_id == document_id))
        self.db.flush()
        return int(entity_result.rowcount or 0)

    def add_entity(self, entity: GraphEntity) -> GraphEntity:
        """新增图谱实体。"""

        self.db.add(entity)
        self.db.flush()
        return entity

    def add_relation(self, relation: GraphRelation) -> GraphRelation:
        """新增图谱关系。"""

        self.db.add(relation)
        self.db.flush()
        return relation

    def publish_document_graph(self, document_id: int, version_no: int) -> int:
        """发布指定文档版本的图谱数据。"""

        self.db.execute(
            update(GraphEntity)
            .where(GraphEntity.document_id == document_id, GraphEntity.version_no != version_no, GraphEntity.status == "published")
            .values(status="obsolete")
        )
        self.db.execute(
            update(GraphRelation)
            .where(GraphRelation.document_id == document_id, GraphRelation.version_no != version_no, GraphRelation.status == "published")
            .values(status="obsolete")
        )
        entity_result = self.db.execute(
            update(GraphEntity)
            .where(GraphEntity.document_id == document_id, GraphEntity.version_no == version_no, GraphEntity.status == "staging")
            .values(status="published")
        )
        self.db.execute(
            update(GraphRelation)
            .where(GraphRelation.document_id == document_id, GraphRelation.version_no == version_no, GraphRelation.status == "staging")
            .values(status="published")
        )
        self.db.flush()
        return int(entity_result.rowcount or 0)

    def search_entities(self, terms: list[str], limit: int = 20) -> list[GraphEntity]:
        """按关键词查询已发布实体。"""

        if not terms:
            return []
        conditions = []
        for term in terms:
            pattern = f"%{term}%"
            conditions.append(GraphEntity.entity_name.like(pattern))
            conditions.append(GraphEntity.entity_code.like(pattern))
        stmt = select(GraphEntity).where(GraphEntity.status == "published", or_(*conditions)).limit(limit)
        return list(self.db.scalars(stmt).all())

    def relations_for_entities(self, entity_ids: list[int], limit: int = 20) -> list[GraphRelation]:
        """查询实体相关的已发布关系。"""

        if not entity_ids:
            return []
        stmt = (
            select(GraphRelation)
            .where(
                GraphRelation.status == "published",
                or_(GraphRelation.source_entity_id.in_(entity_ids), GraphRelation.target_entity_id.in_(entity_ids)),
            )
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def get_entity(self, entity_id: int) -> GraphEntity | None:
        """按 ID 查询实体。"""

        return self.db.get(GraphEntity, entity_id)
