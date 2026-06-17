"""
Document Asset Models

负责：
1. 保存文档解析阶段产生的派生文件资产
2. 统一管理转换 PDF、MinerU 原始结果、页预览图和块级图片
3. 为原始内容预览、问题排查和后续历史版本能力提供来源追踪
"""

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DocumentAsset(TimestampMixin, Base):
    """
    文档派生资产表

    职责：
    - 记录文档版本级派生文件元数据
    - 关联页级和块级预览资产
    - 维护资产状态，避免解析重试时污染已发布数据
    """

    __tablename__ = "document_assets"
    __table_args__ = (
        Index("idx_document_assets_document_id", "document_id"),
        Index("idx_document_assets_version_no", "version_no"),
        Index("idx_document_assets_asset_type", "asset_type"),
        Index("idx_document_assets_status", "status"),
        Index("idx_document_assets_page_id", "page_id"),
        Index("idx_document_assets_block_id", "block_id"),
        {"comment": "文档派生资产表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, comment="关联文档ID，关联documents.id")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="所属文档版本号")
    page_id: Mapped[int | None] = mapped_column(ForeignKey("document_pages.id"), nullable=True, comment="所属页ID，关联document_pages.id")
    block_id: Mapped[int | None] = mapped_column(ForeignKey("document_page_blocks.id"), nullable=True, comment="所属块ID，关联document_page_blocks.id")
    asset_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="资产类型：converted_pdf/mineru_result/page_preview/block_image",
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="资产文件名")
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="资产MIME类型")
    storage_backend: Mapped[str] = mapped_column(String(30), nullable=False, default="local", comment="存储后端：local/minio")
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="本地存储路径")
    object_key: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="对象存储Key")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="文件大小，单位字节")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ready", comment="资产状态：ready/failed/obsolete")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="资产扩展元数据JSON")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="创建人ID，关联users.id")
