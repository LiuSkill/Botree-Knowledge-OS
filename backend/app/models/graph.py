"""
GraphRAG Models

负责：
1. 预留知识图谱实体与关系表
2. 保存实体、关系与来源 Chunk 的追踪信息
3. 支撑后续 GraphRAG 检索扩展
"""

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class GraphEntity(TimestampMixin, Base):
    """
    知识图谱实体表

    职责：
    - 保存从文档 Chunk 抽取的实体
    - 保留实体类型、编码、名称与来源信息
    """

    __tablename__ = "graph_entities"
    __table_args__ = (
        Index("idx_graph_entities_document_id", "document_id"),
        Index("idx_graph_entities_knowledge_base_id", "knowledge_base_id"),
        Index("idx_graph_entities_project_id", "project_id"),
        Index("idx_graph_entities_version_no", "version_no"),
        Index("idx_graph_entities_drawing_no", "drawing_no"),
        Index("idx_graph_entities_page_number", "page_number"),
        Index("idx_graph_entities_status", "status"),
        Index("idx_graph_entities_doc_status_ver", "document_id", "status", "version_no"),
        {"comment": "知识图谱实体表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), nullable=False, comment="知识库ID，关联knowledge_bases.id")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, comment="所属项目ID，项目知识关联projects.id")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, comment="文档ID，关联documents.id")
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("document_chunks.id"), nullable=True, comment="Chunk ID，关联document_chunks.id")
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="来源文档版本号")
    drawing_no: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="图纸编号")
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="来源页码")
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, comment="实体类型")
    entity_code: Mapped[str | None] = mapped_column(String(150), nullable=True, comment="实体编码")
    entity_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="实体名称")
    status: Mapped[str] = mapped_column(String(30), default="staging", nullable=False, comment="实体状态：staging/published/obsolete")
    properties_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="实体属性JSON")


class GraphRelation(TimestampMixin, Base):
    """
    知识图谱关系表

    职责：
    - 保存实体之间的关系
    - 保留关系来源，方便回答追溯
    """

    __tablename__ = "graph_relations"
    __table_args__ = (
        Index("idx_graph_relations_knowledge_base_id", "knowledge_base_id"),
        Index("idx_graph_relations_project_id", "project_id"),
        Index("idx_graph_relations_source_entity_id", "source_entity_id"),
        Index("idx_graph_relations_target_entity_id", "target_entity_id"),
        Index("idx_graph_relations_document_id", "document_id"),
        Index("idx_graph_relations_version_no", "version_no"),
        Index("idx_graph_relations_drawing_no", "drawing_no"),
        Index("idx_graph_relations_page_number", "page_number"),
        Index("idx_graph_relations_status", "status"),
        Index("idx_graph_relations_doc_status_ver", "document_id", "status", "version_no"),
        {"comment": "知识图谱关系表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), nullable=False, comment="知识库ID，关联knowledge_bases.id")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, comment="所属项目ID，项目知识关联projects.id")
    source_entity_id: Mapped[int] = mapped_column(ForeignKey("graph_entities.id"), nullable=False, comment="源实体ID，关联graph_entities.id")
    target_entity_id: Mapped[int] = mapped_column(ForeignKey("graph_entities.id"), nullable=False, comment="目标实体ID，关联graph_entities.id")
    relation_type: Mapped[str] = mapped_column(String(100), nullable=False, comment="关系类型")
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True, comment="来源文档ID，关联documents.id")
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("document_chunks.id"), nullable=True, comment="来源Chunk ID，关联document_chunks.id")
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="来源文档版本号")
    drawing_no: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="图纸编号")
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="来源页码")
    status: Mapped[str] = mapped_column(String(30), default="staging", nullable=False, comment="关系状态：staging/published/obsolete")
    properties_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="关系属性JSON")
