"""
PageIndex Repository

负责：
1. 读写文档页、页块和 PageIndex
2. 支持页级修正、发布和检索回溯
3. 保持 Service 层不直接操作数据库查询细节
"""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.page_index import DocumentPage, DocumentPageBlock, PageIndex


class PageIndexRepository:
    """
    PageIndex 仓储

    职责：
    - 管理页级解析结果
    - 管理 PageIndex staging/published 状态
    - 查询文档页、页块和页级索引
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def clear_document_pages(self, document_id: int, version_no: int) -> None:
        """清理指定文档版本的页级解析结果。"""

        page_ids = list(
            self.db.scalars(
                select(DocumentPage.id).where(DocumentPage.document_id == document_id, DocumentPage.version_no == version_no)
            ).all()
        )
        if page_ids:
            self.db.execute(delete(DocumentPageBlock).where(DocumentPageBlock.page_id.in_(page_ids)))
        self.db.execute(delete(PageIndex).where(PageIndex.document_id == document_id, PageIndex.version_no == version_no))
        self.db.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id, DocumentPage.version_no == version_no))
        self.db.flush()

    def clear_all_document_pages(self, document_id: int) -> int:
        """
        物理删除文档全部版本的页级解析结果和 PageIndex。

        参数:
            document_id: 文档ID。

        返回:
            删除的页记录数量。
        """

        page_ids = list(self.db.scalars(select(DocumentPage.id).where(DocumentPage.document_id == document_id)).all())
        if page_ids:
            self.db.execute(delete(DocumentPageBlock).where(DocumentPageBlock.page_id.in_(page_ids)))
        self.db.execute(delete(PageIndex).where(PageIndex.document_id == document_id))
        page_result = self.db.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
        self.db.flush()
        return int(page_result.rowcount or 0)

    def clear_document_indexes(self, document_id: int, version_no: int) -> None:
        """清理指定文档版本的 PageIndex 记录。"""

        self.db.execute(delete(PageIndex).where(PageIndex.document_id == document_id, PageIndex.version_no == version_no))
        self.db.flush()

    def add_page(self, page: DocumentPage) -> DocumentPage:
        """新增文档页。"""

        self.db.add(page)
        self.db.flush()
        return page

    def add_blocks(self, blocks: list[DocumentPageBlock]) -> list[DocumentPageBlock]:
        """批量新增文档页块。"""

        for block in blocks:
            self.db.add(block)
        self.db.flush()
        return blocks

    def add_page_index(self, page_index: PageIndex) -> PageIndex:
        """新增 PageIndex 记录。"""

        self.db.add(page_index)
        self.db.flush()
        return page_index

    def get_page_index(self, page_index_id: int) -> PageIndex | None:
        """按主键查询 PageIndex，用于从检索证据回溯页面资产。"""

        return self.db.get(PageIndex, page_index_id)

    def list_pages(self, document_id: int, version_no: int | None = None) -> list[DocumentPage]:
        """按文档查询页列表。"""

        stmt = select(DocumentPage).where(DocumentPage.document_id == document_id).order_by(DocumentPage.page_no)
        if version_no is not None:
            stmt = stmt.where(DocumentPage.version_no == version_no)
        return list(self.db.scalars(stmt).all())

    def list_blocks(self, document_id: int, version_no: int | None = None) -> list[DocumentPageBlock]:
        """按文档查询页块列表。"""

        stmt = (
            select(DocumentPageBlock)
            .join(DocumentPage, DocumentPage.id == DocumentPageBlock.page_id)
            .where(DocumentPageBlock.document_id == document_id)
            .order_by(DocumentPage.page_no, DocumentPageBlock.block_index)
        )
        if version_no is not None:
            stmt = stmt.where(DocumentPage.version_no == version_no)
        return list(self.db.scalars(stmt).all())

    def get_page(self, document_id: int, page_no: int, version_no: int | None = None) -> DocumentPage | None:
        """按文档和页码查询页记录。"""

        stmt = select(DocumentPage).where(DocumentPage.document_id == document_id, DocumentPage.page_no == page_no)
        if version_no is not None:
            stmt = stmt.where(DocumentPage.version_no == version_no)
        return self.db.scalar(stmt.order_by(DocumentPage.version_no.desc()))

    def list_published_indexes(self) -> list[PageIndex]:
        """查询已发布 PageIndex，用于在线检索。"""

        return list(self.db.scalars(select(PageIndex).where(PageIndex.status == "published").order_by(PageIndex.id.desc())).all())

    def list_document_indexes(self, document_id: int, status: str | None = None) -> list[PageIndex]:
        """查询指定文档的 PageIndex。"""

        stmt = select(PageIndex).where(PageIndex.document_id == document_id).order_by(PageIndex.page_no, PageIndex.id)
        if status:
            stmt = stmt.where(PageIndex.status == status)
        return list(self.db.scalars(stmt).all())

    def publish_document_indexes(self, document_id: int, version_no: int) -> int:
        """发布指定文档版本的 staging PageIndex。"""

        self.db.execute(
            update(PageIndex)
            .where(PageIndex.document_id == document_id, PageIndex.version_no != version_no, PageIndex.status == "published")
            .values(status="obsolete")
        )
        result = self.db.execute(
            update(PageIndex)
            .where(PageIndex.document_id == document_id, PageIndex.version_no == version_no, PageIndex.status == "staging")
            .values(status="published")
        )
        self.db.flush()
        return int(result.rowcount or 0)
