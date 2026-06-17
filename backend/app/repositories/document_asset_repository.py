"""
Document Asset Repository

负责：
1. 读写文档派生资产表
2. 支持按文档版本查询和失效旧资产
3. 为预览接口和解析重试提供统一数据访问入口
"""

from __future__ import annotations

from sqlalchemy import Select, delete, select, update
from sqlalchemy.orm import Session

from app.models.document_asset import DocumentAsset


class DocumentAssetRepository:
    """
    文档派生资产仓储

    职责：
    - 新增和查询资产
    - 失效同版本旧资产
    - 查询预览所需页级和块级图片
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, asset: DocumentAsset) -> DocumentAsset:
        """新增文档派生资产。"""

        self.db.add(asset)
        self.db.flush()
        return asset

    def get(self, asset_id: int) -> DocumentAsset | None:
        """按主键查询文档派生资产。"""

        return self.db.get(DocumentAsset, asset_id)

    def list_by_document_version(
        self,
        document_id: int,
        version_no: int,
        asset_type: str | None = None,
        status: str | None = None,
    ) -> list[DocumentAsset]:
        """按文档版本查询资产列表。"""

        stmt: Select[tuple[DocumentAsset]] = (
            select(DocumentAsset)
            .where(DocumentAsset.document_id == document_id, DocumentAsset.version_no == version_no)
            .order_by(DocumentAsset.page_id, DocumentAsset.block_id, DocumentAsset.id)
        )
        if asset_type:
            stmt = stmt.where(DocumentAsset.asset_type == asset_type)
        if status:
            stmt = stmt.where(DocumentAsset.status == status)
        return list(self.db.scalars(stmt).all())

    def list_ready_page_image_assets(
        self,
        document_id: int,
        version_no: int,
        page_id: int,
        asset_types: set[str],
    ) -> list[DocumentAsset]:
        """
        查询指定页面可用于视觉问答的图片资产。

        只返回 ready 且 MIME 为图片的资产，避免把解析失败或非图片文件交给视觉模型。
        """

        stmt: Select[tuple[DocumentAsset]] = (
            select(DocumentAsset)
            .where(
                DocumentAsset.document_id == document_id,
                DocumentAsset.version_no == version_no,
                DocumentAsset.page_id == page_id,
                DocumentAsset.status == "ready",
                DocumentAsset.asset_type.in_(sorted(asset_types)),
            )
            .order_by(DocumentAsset.asset_type, DocumentAsset.block_id, DocumentAsset.id)
        )
        return [
            asset
            for asset in self.db.scalars(stmt).all()
            if str(asset.mime_type or "").lower().startswith("image/")
        ]

    def get_latest_ready_asset(self, document_id: int, version_no: int, asset_type: str) -> DocumentAsset | None:
        """查询同一文档版本下某类最新可用资产。"""

        return self.db.scalar(
            select(DocumentAsset)
            .where(
                DocumentAsset.document_id == document_id,
                DocumentAsset.version_no == version_no,
                DocumentAsset.asset_type == asset_type,
                DocumentAsset.status == "ready",
            )
            .order_by(DocumentAsset.id.desc())
        )

    def list_by_document(self, document_id: int) -> list[DocumentAsset]:
        """
        查询文档全部版本的派生资产。

        参数:
            document_id: 文档ID。

        返回:
            资产列表。
        """

        stmt: Select[tuple[DocumentAsset]] = (
            select(DocumentAsset)
            .where(DocumentAsset.document_id == document_id)
            .order_by(DocumentAsset.version_no.desc(), DocumentAsset.page_id, DocumentAsset.block_id, DocumentAsset.id)
        )
        return list(self.db.scalars(stmt).all())

    def delete_by_document(self, document_id: int) -> int:
        """
        物理删除文档全部版本的派生资产记录。

        参数:
            document_id: 文档ID。

        返回:
            删除的资产数量。
        """

        result = self.db.execute(delete(DocumentAsset).where(DocumentAsset.document_id == document_id))
        self.db.flush()
        return int(result.rowcount or 0)

    def obsolete_version_assets(self, document_id: int, version_no: int, keep_asset_types: set[str] | None = None) -> int:
        """
        将同版本旧资产标记为 obsolete。

        说明：
            解析重试时，旧的页图和块图仍需保留历史记录，但不能继续参与当前版本预览，
            同时还要断开 page_id/block_id，避免页表重建后产生悬挂引用。
        """

        keep_asset_types = keep_asset_types or set()
        stmt = update(DocumentAsset).where(
            DocumentAsset.document_id == document_id,
            DocumentAsset.version_no == version_no,
            DocumentAsset.status != "obsolete",
        )
        if keep_asset_types:
            stmt = stmt.where(DocumentAsset.asset_type.notin_(sorted(keep_asset_types)))
        result = self.db.execute(
            stmt.values(
                status="obsolete",
                page_id=None,
                block_id=None,
            )
        )
        self.db.flush()
        return int(result.rowcount or 0)
