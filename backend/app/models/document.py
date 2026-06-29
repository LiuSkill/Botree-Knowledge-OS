"""
Document models.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security_levels import DEFAULT_SECURITY_LEVEL
from app.models.base import Base, TimestampMixin


class Document(TimestampMixin, Base):
    """Document main record."""

    __tablename__ = "documents"
    __table_args__ = {"comment": "文档主表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True, nullable=False, comment="所属知识库ID")
    knowledge_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False, comment="知识类型：base/project")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True, nullable=True, comment="所属项目ID")
    directory_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_categories.id"), index=True, nullable=True, comment="所属项目资料目录ID")
    document_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="文件名称")
    document_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="文档类型")
    discipline: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="所属专业")
    version: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="版本号")
    status: Mapped[str] = mapped_column(String(30), default="待审核", index=True, nullable=False, comment="轻量文件状态：待审核/已发布")
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否参与AI问答")
    upload_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="上传人ID")
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="文件名")
    file_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="文件类型")
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="文件大小字节")
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="文件存储路径")
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="文件路径")
    category_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_categories.id"), index=True, nullable=True, comment="知识分类ID")
    document_status: Mapped[str] = mapped_column(String(30), default="pending_review", index=True, nullable=False, comment="文档状态")
    parse_status: Mapped[str] = mapped_column(String(30), default="unparsed", index=True, nullable=False, comment="解析状态")
    parse_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="解析开始时间")
    parse_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="解析完成时间")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="解析失败原因")
    parse_log: Mapped[str | None] = mapped_column(Text, nullable=True, comment="解析日志")
    review_status: Mapped[str] = mapped_column(String(30), default="draft", index=True, nullable=False, comment="审核状态")
    index_status: Mapped[str] = mapped_column(String(30), default="not_indexed", index=True, nullable=False, comment="索引状态")
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="当前版本号")
    current_version: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否当前版本")
    is_current_version: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否当前版本")
    parent_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True, comment="父文档ID")
    drawing_no: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="图纸编号")
    drawing_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="图纸名称")
    security_level: Mapped[str] = mapped_column(
        String(30),
        default=DEFAULT_SECURITY_LEVEL,
        nullable=False,
        comment="文档密级：public/internal/confidential",
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="创建人ID")
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="提交人ID")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="审核人ID")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="提交审核时间")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="审核完成时间")
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="审核意见")
    build_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="解析并构建索引开始时间")
    build_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="解析并构建索引完成时间")
    build_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="索引构建失败信息")
    built_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="构建人ID")
    preview_url: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="预览地址")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否删除")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="删除时间")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class DocumentVersion(TimestampMixin, Base):
    """Document version record."""

    __tablename__ = "document_versions"
    __table_args__ = {"comment": "文档版本表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False, comment="关联文档ID")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True, nullable=True, comment="所属项目ID")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号")
    version: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="版本号")
    category_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_categories.id"), index=True, nullable=True, comment="版本所属分类ID")
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="文件名")
    file_type: Mapped[str] = mapped_column(String(50), default="", nullable=False, comment="文件类型")
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="文件大小字节")
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="文件存储路径")
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="文件路径")
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="版本变更说明")
    version_status: Mapped[str] = mapped_column(String(30), default="draft", index=True, nullable=False, comment="版本状态")
    status: Mapped[str] = mapped_column(String(30), default="待审核", nullable=False, comment="轻量文件状态：待审核/已发布")
    parse_status: Mapped[str] = mapped_column(String(30), default="unparsed", index=True, nullable=False, comment="解析状态")
    parse_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="解析开始时间")
    parse_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="解析完成时间")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="解析失败原因")
    parse_log: Mapped[str | None] = mapped_column(Text, nullable=True, comment="解析日志")
    review_status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, comment="审核状态")
    index_status: Mapped[str] = mapped_column(String(30), default="not_indexed", nullable=False, comment="索引状态")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否当前版本")
    is_current_version: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否当前版本")
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否参与AI问答")
    security_level: Mapped[str] = mapped_column(
        String(30),
        default=DEFAULT_SECURITY_LEVEL,
        nullable=False,
        comment="版本密级：public/internal/confidential",
    )
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="审核人ID")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="审核完成时间")
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="审核意见")
    build_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="索引构建开始时间")
    build_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="索引构建完成时间")
    build_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="索引构建失败原因")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="创建人ID")
    upload_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="上传人ID")
    version_note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="版本备注")


class DocumentChunk(TimestampMixin, Base):
    """Document chunk record."""

    __tablename__ = "document_chunks"
    __table_args__ = {"comment": "文档分块表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True, nullable=False, comment="所属知识库ID")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False, comment="关联文档ID")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True, nullable=True, comment="所属项目ID")
    knowledge_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False, comment="知识类型：base/project")
    version_no: Mapped[int] = mapped_column(Integer, default=1, index=True, nullable=False, comment="所属文档版本号")
    chunk_status: Mapped[str] = mapped_column(String(30), default="active", index=True, nullable=False, comment="Chunk状态")
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="Chunk序号")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="Chunk内容")
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="页码")
    section_title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="章节标题")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="扩展元数据JSON")
    vector_id: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="向量ID")
    security_level: Mapped[str] = mapped_column(
        String(30),
        default=DEFAULT_SECURITY_LEVEL,
        nullable=False,
        comment="Chunk密级：public/internal/confidential",
    )
