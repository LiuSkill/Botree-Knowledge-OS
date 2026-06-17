"""
PageIndex Models

负责：
1. 保存 MinerU 页级解析结果
2. 维护 PageIndex 文档树和 ripgrep 文本镜像映射
3. 为长文档问答提供 page_no、drawing_no、chunk_id 来源追踪
"""

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DocumentPage(TimestampMixin, Base):
    """
    文档页级模型

    职责：
    - 保存页级正文、摘要和版面结构
    - 关联项目、知识库、文档、版本和图纸号
    - 支撑 PageIndex、ripgrep 和 citation 页级追踪
    """

    __tablename__ = "document_pages"
    __table_args__ = (
        Index("idx_document_pages_knowledge_base_id", "knowledge_base_id"),
        Index("idx_document_pages_project_id", "project_id"),
        Index("idx_document_pages_document_id", "document_id"),
        Index("idx_document_pages_version_no", "version_no"),
        Index("idx_document_pages_page_no", "page_no"),
        Index("idx_document_pages_drawing_no", "drawing_no"),
        Index("idx_document_pages_correction_status", "correction_status"),
        {"comment": "文档页级解析表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), nullable=False, comment="所属知识库ID，关联knowledge_bases.id")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, comment="所属项目ID，关联projects.id")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, comment="关联文档ID，关联documents.id")
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="所属文档版本号")
    page_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="页码")
    drawing_no: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="图纸编号")
    page_title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="页标题或章节标题")
    page_text: Mapped[str] = mapped_column(Text, nullable=False, comment="页级原始正文文本")
    clean_content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="清洗后页文本，用于分块和索引")
    filtered_content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="清洗过滤掉的页文本")
    cleaning_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="解析清洗摘要JSON")
    page_summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="页级摘要")
    layout_json: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql"),
        nullable=True,
        comment="MinerU版面结构JSON",
    )
    mineru_json_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="MinerU原始JSON对象存储Key")
    page_image_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="页面图片对象存储Key")
    source_hash: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="页内容哈希")
    correction_status: Mapped[str] = mapped_column(String(30), default="raw", nullable=False, comment="修正状态：raw/corrected/confirmed")
    corrected_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="人工修正后的页文本")
    corrected_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="修正人ID，关联users.id")


class DocumentPageBlock(TimestampMixin, Base):
    """
    文档页块模型

    职责：
    - 保存标题、正文、表格、图片等块级结构
    - 保留 bbox 和扩展元数据
    - 为人工校正、版面定位和图谱抽取提供结构化来源
    """

    __tablename__ = "document_page_blocks"
    __table_args__ = (
        Index("idx_document_page_blocks_page_id", "page_id"),
        Index("idx_document_page_blocks_document_id", "document_id"),
        {"comment": "文档页块解析表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    page_id: Mapped[int] = mapped_column(ForeignKey("document_pages.id"), nullable=False, comment="所属页ID，关联document_pages.id")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, comment="关联文档ID，关联documents.id")
    block_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="页内块序号")
    block_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="块类型：title/text/table/image/formula")
    text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="块原始文本内容")
    clean_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="清洗后块文本")
    filter_status: Mapped[str] = mapped_column(String(30), default="kept", nullable=False, comment="清洗状态：kept/filtered")
    filter_reason: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="清洗过滤原因")
    bbox_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="块坐标JSON")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="块扩展元数据JSON")


class PageIndex(TimestampMixin, Base):
    """
    PageIndex 页级索引

    职责：
    - 保存页级索引文本和发布状态
    - 映射页面、Chunk、图纸号和本地文本镜像路径
    - 支撑长文档内部定位和精确检索结果回溯
    """

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
        {"comment": "PageIndex页级索引表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), nullable=False, comment="所属知识库ID，关联knowledge_bases.id")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, comment="所属项目ID，关联projects.id")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, comment="关联文档ID，关联documents.id")
    page_id: Mapped[int] = mapped_column(ForeignKey("document_pages.id"), nullable=False, comment="关联页ID，关联document_pages.id")
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("document_chunks.id"), nullable=True, comment="关联Chunk ID，关联document_chunks.id")
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="所属文档版本号")
    page_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="页码")
    drawing_no: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="图纸编号")
    index_text: Mapped[str] = mapped_column(Text, nullable=False, comment="用于页级检索的文本")
    text_mirror_path: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="ripgrep本地文本镜像路径")
    status: Mapped[str] = mapped_column(String(30), default="staging", nullable=False, comment="索引状态：staging/published/obsolete")
