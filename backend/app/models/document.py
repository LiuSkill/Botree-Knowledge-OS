"""
Document Models

负责：
1. 文档、版本和知识分块建模
2. 保存审核状态、索引状态与来源追踪字段
3. 支撑 GraphRAG 可追溯回答
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Document(TimestampMixin, Base):
    """
    文档表

    职责：
    - 保存上传资料元数据
    - 控制审核状态和索引状态
    - 作为问答引用来源的文档级追踪对象
    """

    __tablename__ = "documents"
    __table_args__ = {"comment": "文档主表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True, nullable=False, comment="所属知识库ID，关联knowledge_bases.id")
    knowledge_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False, comment="知识类型：base/project")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True, nullable=True, comment="所属项目ID，项目知识关联projects.id")
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="文件名")
    file_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="文件类型")
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="文件大小，单位字节")
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="文件存储路径")
    category_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_categories.id"), index=True, nullable=True, comment="知识分类ID，关联knowledge_categories.id")
    document_status: Mapped[str] = mapped_column(String(30), default="pending_review", index=True, nullable=False, comment="文档状态：pending_review/reviewed/active/inactive/archived")
    parse_status: Mapped[str] = mapped_column(String(30), default="unparsed", index=True, nullable=False, comment="解析状态：unparsed/parsing/success/failed")
    parse_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="解析开始时间")
    parse_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="解析完成时间")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="解析失败原因")
    parse_log: Mapped[str | None] = mapped_column(Text, nullable=True, comment="解析日志")
    review_status: Mapped[str] = mapped_column(String(30), default="draft", index=True, nullable=False, comment="审核状态：draft/submitted/reviewing/approved/rejected/archived")
    index_status: Mapped[str] = mapped_column(String(30), default="not_indexed", index=True, nullable=False, comment="索引状态：not_indexed/parsing/parsed/indexing/indexed/failed")
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="当前版本号")
    current_version: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否当前版本")
    parent_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True, comment="父文档ID，关联documents.id")
    drawing_no: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="图纸编号")
    drawing_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="图纸名称")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="创建人ID，关联users.id")
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="提交人ID，关联users.id")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="审核人ID，关联users.id")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="提交审核时间")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="审核完成时间")
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="审核意见")
    build_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="解析并构建索引开始时间")
    build_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="解析并构建索引完成时间")
    build_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="解析并构建索引失败信息")
    built_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="构建操作人ID，关联users.id")


class DocumentVersion(TimestampMixin, Base):
    """
    文档版本表

    职责：
    - 保存文档历史版本
    - 支持后续版本回滚和变更追踪
    """

    __tablename__ = "document_versions"
    __table_args__ = {"comment": "文档版本表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False, comment="关联文档ID，关联documents.id")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号")
    category_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_categories.id"), index=True, nullable=True, comment="版本所属知识分类ID，关联knowledge_categories.id")
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="文件名")
    file_type: Mapped[str] = mapped_column(String(50), default="", nullable=False, comment="文件类型")
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="文件大小，单位字节")
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="文件存储路径")
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="版本变更说明")
    version_status: Mapped[str] = mapped_column(String(30), default="draft", index=True, nullable=False, comment="版本状态：draft/pending_review/approved/current/historical/inactive/rejected")
    parse_status: Mapped[str] = mapped_column(String(30), default="unparsed", index=True, nullable=False, comment="解析状态：unparsed/parsing/success/failed")
    parse_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="解析开始时间")
    parse_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="解析完成时间")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="解析失败原因")
    parse_log: Mapped[str | None] = mapped_column(Text, nullable=True, comment="解析日志")
    review_status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, comment="审核状态：draft/submitted/reviewing/approved/rejected/archived")
    index_status: Mapped[str] = mapped_column(String(30), default="not_indexed", nullable=False, comment="索引状态：not_indexed/parsing/parsed/indexing/indexed/failed")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否当前版本")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="审核人ID，关联users.id")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="审核完成时间")
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="审核意见")
    build_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="索引构建开始时间")
    build_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="索引构建完成时间")
    build_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="索引构建失败原因")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="创建人ID，关联users.id")


class DocumentChunk(TimestampMixin, Base):
    """
    文档切块表

    职责：
    - 保存解析后的知识片段
    - 保留 project_id、document_id、page_number、chunk_id 等来源追踪字段
    - 作为检索和问答引用的最小证据单元
    """

    __tablename__ = "document_chunks"
    __table_args__ = {"comment": "文档切块表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True, nullable=False, comment="所属知识库ID，关联knowledge_bases.id")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False, comment="关联文档ID，关联documents.id")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True, nullable=True, comment="所属项目ID，项目知识关联projects.id")
    knowledge_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False, comment="知识类型：base/project")
    version_no: Mapped[int] = mapped_column(Integer, default=1, index=True, nullable=False, comment="所属文档版本号")
    chunk_status: Mapped[str] = mapped_column(String(30), default="active", index=True, nullable=False, comment="Chunk状态：active/obsolete")
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="Chunk序号")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="Chunk内容")
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="页码")
    section_title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="章节标题")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="扩展元数据JSON")
    vector_id: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="向量ID，后续关联Milvus")
