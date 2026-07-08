"""
Page index models.
"""

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security_levels import DEFAULT_SECURITY_LEVEL
from app.models.base import Base, TimestampMixin


class DocumentPage(TimestampMixin, Base):
    """Parsed page record."""

    __tablename__ = "document_pages"
    __table_args__ = (
        Index("idx_document_pages_knowledge_base_id", "knowledge_base_id"),
        Index("idx_document_pages_project_id", "project_id"),
        Index("idx_document_pages_document_id", "document_id"),
        Index("idx_document_pages_version_no", "version_no"),
        Index("idx_document_pages_page_no", "page_no"),
        Index("idx_document_pages_drawing_no", "drawing_no"),
        Index("idx_document_pages_correction_status", "correction_status"),
        {"comment": "文档页解析表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), nullable=False, comment="所属知识库ID")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, comment="所属项目ID")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, comment="关联文档ID")
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="所属文档版本号")
    page_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="页码")
    drawing_no: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="图纸编号")
    page_title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="页标题或章节标题")
    page_text: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=False, comment="页原始正文文本")
    clean_content: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True, comment="清洗后页文本")
    filtered_content: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True, comment="过滤后页文本")
    cleaning_metadata_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True, comment="清洗摘要JSON")
    page_summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="页摘要")
    layout_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True, comment="版面结构JSON")
    mineru_json_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="MinerU JSON 对象 Key")
    page_image_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="页面图片对象 Key")
    source_hash: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="页内容哈希")
    correction_status: Mapped[str] = mapped_column(String(30), default="raw", nullable=False, comment="修正状态")
    corrected_text: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True, comment="人工修正后的文本")
    corrected_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="修正人ID")
    security_level: Mapped[str] = mapped_column(
        String(30),
        default=DEFAULT_SECURITY_LEVEL,
        nullable=False,
        comment="页面密级：public/internal/confidential",
    )


class DocumentPageBlock(TimestampMixin, Base):
    """Parsed page block record."""

    __tablename__ = "document_page_blocks"
    __table_args__ = (
        Index("idx_document_page_blocks_page_id", "page_id"),
        Index("idx_document_page_blocks_document_id", "document_id"),
        {"comment": "文档页块解析表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    page_id: Mapped[int] = mapped_column(ForeignKey("document_pages.id"), nullable=False, comment="所属页ID")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, comment="关联文档ID")
    block_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="页内块序号")
    block_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="块类型")
    text: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True, comment="块原始文本")
    clean_text: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True, comment="清洗后块文本")
    filter_status: Mapped[str] = mapped_column(String(30), default="kept", nullable=False, comment="清洗状态")
    filter_reason: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="清洗过滤原因")
    bbox_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="块坐标JSON")
    metadata_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True, comment="块扩展元数据JSON")


class PageIndex(TimestampMixin, Base):
    """Page-level search index."""

    __tablename__ = "page_indexes"
    __table_args__ = (
        Index("idx_page_indexes_knowledge_base_id", "knowledge_base_id"),
        Index("idx_page_indexes_project_id", "project_id"),
        Index("idx_page_indexes_document_id", "document_id"),
        Index("idx_page_indexes_page_id", "page_id"),
        Index("idx_page_indexes_chunk_id", "chunk_id"),
        Index("idx_page_indexes_version_no", "version_no"),
        Index("idx_page_indexes_page_no", "page_no"),
        Index("idx_page_indexes_drawing_no", "drawing_no"),
        Index("idx_page_indexes_status", "status"),
        Index("idx_page_indexes_doc_status_ver", "document_id", "status", "version_no"),
        {"comment": "PageIndex表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), nullable=False, comment="所属知识库ID")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, comment="所属项目ID")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, comment="关联文档ID")
    page_id: Mapped[int] = mapped_column(ForeignKey("document_pages.id"), nullable=False, comment="关联页ID")
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("document_chunks.id"), nullable=True, comment="关联 Chunk ID")
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="所属文档版本号")
    page_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="页码")
    drawing_no: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="图纸编号")
    index_text: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=False, comment="用于页面索引的文本")
    text_mirror_path: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="ripgrep 本地文本镜像路径")
    status: Mapped[str] = mapped_column(String(30), default="staging", nullable=False, comment="索引状态")
    security_level: Mapped[str] = mapped_column(
        String(30),
        default=DEFAULT_SECURITY_LEVEL,
        nullable=False,
        comment="PageIndex密级：public/internal/confidential",
    )
