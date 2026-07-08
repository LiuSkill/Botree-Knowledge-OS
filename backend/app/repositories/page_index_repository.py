"""
PageIndex Repository

负责：
1. 读写文档页、页块和 PageIndex
2. 支持页级修正、发布和检索回溯
3. 保持 Service 层不直接操作数据库查询细节
"""

from __future__ import annotations

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk
from app.models.page_index import DocumentPage, DocumentPageBlock, PageIndex

STATUS_UPDATE_BATCH_SIZE = 200


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

    def list_published_indexes(self, security_levels: list[str] | None = None) -> list[PageIndex]:
        """查询已发布 PageIndex，用于在线检索。"""

        stmt = select(PageIndex).where(PageIndex.status == "published").order_by(PageIndex.id.desc())
        if security_levels is not None:
            stmt = stmt.where(PageIndex.security_level.in_(security_levels))
        return list(self.db.scalars(stmt).all())

    def list_searchable_index_rows(
        self,
        security_levels: list[str] | None = None,
        *,
        knowledge_type: str | None = None,
        project_id: int | None = None,
        query_terms: list[str] | None = None,
        document_ids: list[int] | None = None,
        chunk_ids: list[int] | None = None,
        page_numbers_by_document: dict[int, list[int]] | None = None,
        require_text_mirror: bool = False,
        match_document_metadata: bool = False,
        diagram_only: bool = False,
        row_limit: int | None = None,
    ) -> list[tuple[PageIndex, Document, DocumentChunk]]:
        """一次性加载检索需要的 PageIndex、Document 和 Chunk，避免检索器内重复查库。"""

        stmt = (
            select(PageIndex, Document, DocumentChunk)
            .join(Document, Document.id == PageIndex.document_id)
            .join(DocumentChunk, DocumentChunk.id == PageIndex.chunk_id)
            .where(PageIndex.status == "published", PageIndex.chunk_id.is_not(None))
            # PageIndex 已发布且 chunk 仍有效时，应允许页级检索独立于主文档向量索引状态工作，
            # 否则 page_index / ripgrep 会被 Document.index_status 人为卡住。
            .where(Document.is_deleted.is_(False), Document.is_current_version.is_(True))
            .where(PageIndex.version_no == Document.version_no, DocumentChunk.version_no == Document.version_no)
            .where(DocumentChunk.document_id == Document.id, DocumentChunk.chunk_status == "active")
            .where(or_(Document.project_id.is_not(None), Document.review_status == "approved"))
            .order_by(PageIndex.id.desc())
        )
        if security_levels is not None:
            stmt = stmt.where(
                PageIndex.security_level.in_(security_levels),
                Document.security_level.in_(security_levels),
                DocumentChunk.security_level.in_(security_levels),
            )
        if knowledge_type:
            stmt = stmt.where(Document.knowledge_type == knowledge_type, DocumentChunk.knowledge_type == knowledge_type)
        if project_id is not None:
            stmt = stmt.where(
                PageIndex.project_id == project_id,
                Document.project_id == project_id,
                DocumentChunk.project_id == project_id,
            )
        if document_ids:
            stmt = stmt.where(
                PageIndex.document_id.in_(document_ids),
                Document.id.in_(document_ids),
                DocumentChunk.document_id.in_(document_ids),
            )
        if chunk_ids:
            stmt = stmt.where(PageIndex.chunk_id.in_(chunk_ids), DocumentChunk.id.in_(chunk_ids))
        page_scope = self._page_scope_filters(page_numbers_by_document)
        if page_scope:
            stmt = stmt.where(or_(*page_scope))
        if require_text_mirror:
            stmt = stmt.where(PageIndex.text_mirror_path.is_not(None))
        if diagram_only:
            stmt = stmt.where(self._diagram_document_filter())
        limited_terms = self._limited_query_terms(query_terms)
        if limited_terms:
            term_filters = [PageIndex.index_text.ilike(f"%{term}%") for term in limited_terms]
            term_filters.extend(DocumentChunk.content.ilike(f"%{term}%") for term in limited_terms)
            if match_document_metadata:
                term_filters.extend(self._document_metadata_term_filters(limited_terms))
            stmt = stmt.where(or_(*term_filters))
        safe_row_limit = self._safe_row_limit(row_limit)
        if safe_row_limit is not None:
            stmt = stmt.limit(safe_row_limit)
        return list(self.db.execute(stmt).all())

    def _page_scope_filters(self, page_numbers_by_document: dict[int, list[int]] | None) -> list[object]:
        filters: list[object] = []
        for document_id, page_numbers in (page_numbers_by_document or {}).items():
            if not page_numbers:
                continue
            filters.append(and_(PageIndex.document_id == document_id, PageIndex.page_no.in_(page_numbers)))
        return filters

    def list_document_indexes(self, document_id: int, status: str | None = None) -> list[PageIndex]:
        """查询指定文档的 PageIndex。"""

        stmt = select(PageIndex).where(PageIndex.document_id == document_id).order_by(PageIndex.page_no, PageIndex.id)
        if status:
            stmt = stmt.where(PageIndex.status == status)
        return list(self.db.scalars(stmt).all())

    def publish_document_indexes(self, document_id: int, version_no: int) -> int:
        """发布指定文档版本的 staging PageIndex。"""

        old_published_ids = self._list_page_index_ids(document_id, "published", exclude_version_no=version_no)
        current_staging_ids = self._list_page_index_ids(document_id, "staging", version_no=version_no)

        self._update_page_index_status_by_ids(old_published_ids, "obsolete")
        published_count = self._update_page_index_status_by_ids(current_staging_ids, "published")
        self.db.flush()
        return published_count

    def _list_page_index_ids(
        self,
        document_id: int,
        status: str,
        *,
        version_no: int | None = None,
        exclude_version_no: int | None = None,
    ) -> list[int]:
        """
        先按确定条件取主键，再按主键更新状态。

        MySQL 在 `status + version_no != ?` 条件上可能选择单列 status 索引，导致发布索引时锁住大量
        published 行。这里用普通一致性读拿到目标 id，再按主键小批量更新，将锁范围收敛到当前文档。
        """

        stmt = select(PageIndex.id).where(PageIndex.document_id == document_id, PageIndex.status == status)
        if version_no is not None:
            stmt = stmt.where(PageIndex.version_no == version_no)
        if exclude_version_no is not None:
            stmt = stmt.where(PageIndex.version_no != exclude_version_no)
        return list(self.db.scalars(stmt.order_by(PageIndex.id)).all())

    def _update_page_index_status_by_ids(self, page_index_ids: list[int], status: str) -> int:
        updated_count = 0
        for start in range(0, len(page_index_ids), STATUS_UPDATE_BATCH_SIZE):
            batch_ids = page_index_ids[start : start + STATUS_UPDATE_BATCH_SIZE]
            if not batch_ids:
                continue
            result = self.db.execute(update(PageIndex).where(PageIndex.id.in_(batch_ids)).values(status=status))
            updated_count += int(result.rowcount or 0)
        return updated_count

    def _limited_query_terms(self, query_terms: list[str] | None) -> list[str]:
        return [term.strip() for term in (query_terms or []) if len(term.strip()) >= 2][:8]

    def _safe_row_limit(self, row_limit: int | None) -> int | None:
        if row_limit is None:
            return None
        try:
            normalized = int(row_limit)
        except (TypeError, ValueError):
            return None
        if normalized <= 0:
            return None
        return max(1, min(normalized, 5000))

    def _document_metadata_term_filters(self, query_terms: list[str]) -> list[object]:
        filters: list[object] = []
        searchable_columns = (
            Document.file_name,
            Document.document_name,
            Document.drawing_name,
            Document.drawing_no,
            PageIndex.drawing_no,
        )
        for term in query_terms:
            like_pattern = f"%{term}%"
            for column in searchable_columns:
                filters.append(column.ilike(like_pattern))
        return filters

    def _diagram_document_filter(self) -> object:
        patterns = (
            "%pid%",
            "%p&id%",
            "%pfd%",
            "%flow diagram%",
            "%process flow%",
            "%diagram%",
            "%流程图%",
            "%工艺流程%",
            "%图纸%",
        )
        pattern_filters: list[object] = []
        for pattern in patterns:
            pattern_filters.extend(
                [
                    Document.file_name.ilike(pattern),
                    Document.document_name.ilike(pattern),
                    Document.drawing_name.ilike(pattern),
                ]
            )
        return or_(
            Document.document_type == "图纸",
            Document.discipline.in_(["工艺", "管道", "仪表"]),
            *pattern_filters,
        )
