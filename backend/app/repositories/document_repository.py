"""
Document Repository

负责：
1. 文档、版本、Chunk 数据库访问
2. 支持审核、解析、索引和检索服务
3. 保持来源追踪字段完整
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import and_, delete, false, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk, DocumentVersion


class DocumentRepository:
    """
    文档仓储

    职责：
    - 文档 CRUD
    - Chunk 查询与保存
    - 按审核和索引状态过滤可检索内容
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(
        self,
        knowledge_base_id: int | None = None,
        project_id: int | None = None,
        review_status: str | None = None,
        category_ids: list[int] | None = None,
        index_status: str | None = None,
        knowledge_type: str | None = None,
        keyword: str | None = None,
    ) -> list[Document]:
        """查询文档列表。"""

        stmt = select(Document).where(Document.is_deleted.is_(False)).order_by(Document.id.desc())
        if knowledge_type:
            stmt = stmt.where(Document.knowledge_type == knowledge_type)
        if knowledge_base_id is not None:
            stmt = stmt.where(Document.knowledge_base_id == knowledge_base_id)
        if project_id is not None:
            stmt = stmt.where(Document.project_id == project_id)
        if review_status:
            stmt = stmt.where(Document.review_status == review_status)
        if category_ids:
            stmt = stmt.where(Document.category_id.in_(category_ids))
        if index_status:
            stmt = stmt.where(Document.index_status == index_status)
        if keyword:
            stmt = stmt.where((Document.file_name.like(f"%{keyword}%")) | (Document.document_name.like(f"%{keyword}%")))
        return list(self.db.scalars(stmt).all())

    def list_approved_page(
        self,
        *,
        page: int,
        page_size: int,
        security_levels: list[str],
        include_base_documents: bool,
        include_project_documents: bool,
        accessible_project_ids: list[int] | None = None,
        project_id: int | None = None,
        category_ids: list[int] | None = None,
        index_status: str | None = None,
        knowledge_type: str | None = None,
        keyword: str | None = None,
    ) -> dict[str, object]:
        """分页查询已审核通过资料，并将密级和项目访问范围下推到数据库。"""

        safe_page = max(page, 1)
        safe_size = max(min(page_size, 100), 1)
        offset = (safe_page - 1) * safe_size
        filters = self._approved_document_filters(
            security_levels=security_levels,
            include_base_documents=include_base_documents,
            include_project_documents=include_project_documents,
            accessible_project_ids=accessible_project_ids,
            project_id=project_id,
            category_ids=category_ids,
            index_status=index_status,
            knowledge_type=knowledge_type,
            keyword=keyword,
        )
        total = int(self.db.scalar(select(func.count(Document.id)).where(*filters)) or 0)
        items = list(
            self.db.scalars(
                select(Document)
                .where(*filters)
                .order_by(Document.id.desc())
                .offset(offset)
                .limit(safe_size)
            ).all()
        )
        return {"items": items, "total": total, "page": safe_page, "page_size": safe_size}

    def _approved_document_filters(
        self,
        *,
        security_levels: list[str],
        include_base_documents: bool,
        include_project_documents: bool,
        accessible_project_ids: list[int] | None,
        project_id: int | None,
        category_ids: list[int] | None,
        index_status: str | None,
        knowledge_type: str | None,
        keyword: str | None,
    ) -> list[object]:
        filters: list[object] = [
            Document.is_deleted.is_(False),
            Document.review_status == "approved",
            Document.security_level.in_(security_levels),
        ]
        access_filters: list[object] = []
        if include_base_documents and project_id is None:
            access_filters.append(or_(Document.knowledge_type == "base", Document.project_id.is_(None)))
        if include_project_documents:
            if project_id is not None:
                access_filters.append(Document.project_id == project_id)
            elif accessible_project_ids:
                access_filters.append(Document.project_id.in_(accessible_project_ids))
        filters.append(or_(*access_filters) if access_filters else false())

        if project_id is not None:
            filters.append(Document.project_id == project_id)
        if knowledge_type:
            filters.append(Document.knowledge_type == knowledge_type)
        if category_ids:
            filters.append(or_(Document.category_id.in_(category_ids), Document.directory_id.in_(category_ids)))
        if index_status:
            filters.append(Document.index_status == index_status)
        if keyword:
            like = f"%{keyword}%"
            filters.append(or_(Document.file_name.like(like), Document.document_name.like(like)))
        return filters

    def list_by_ids(self, document_ids: Iterable[int]) -> list[Document]:
        """按 ID 批量查询文档，用于列表展示字段补齐。"""

        ids = list({int(document_id) for document_id in document_ids})
        if not ids:
            return []
        return list(self.db.scalars(select(Document).where(Document.id.in_(ids))).all())

    def list_versions_by_ids(self, version_ids: Iterable[int]) -> list[DocumentVersion]:
        """按 ID 批量查询文档版本。"""

        ids = list({int(version_id) for version_id in version_ids})
        if not ids:
            return []
        return list(self.db.scalars(select(DocumentVersion).where(DocumentVersion.id.in_(ids))).all())

    def list_versions_by_document_numbers(self, pairs: Iterable[tuple[int, int]]) -> list[DocumentVersion]:
        """按文档 ID 和版本号批量查询版本记录。"""

        keys = list({(int(document_id), int(version_no)) for document_id, version_no in pairs})
        if not keys:
            return []
        conditions = [
            and_(DocumentVersion.document_id == document_id, DocumentVersion.version_no == version_no)
            for document_id, version_no in keys
        ]
        return list(self.db.scalars(select(DocumentVersion).where(or_(*conditions))).all())

    def list_project_page(
        self,
        *,
        project_id: int,
        security_levels: list[str],
        page: int,
        page_size: int,
        category_ids: list[int] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        security_level: str | None = None,
        parse_status: str | None = None,
        index_status: str | None = None,
        document_type: str | None = None,
        discipline: str | None = None,
        upload_user_id: int | None = None,
    ) -> dict[str, object]:
        """按项目资料查询条件返回分页结果和总数，避免前端加载全量数据后再统计。"""

        safe_page = max(page, 1)
        safe_size = max(min(page_size, 100), 1)
        offset = (safe_page - 1) * safe_size
        filters = self._project_document_filters(
            project_id=project_id,
            security_levels=security_levels,
            category_ids=category_ids,
            keyword=keyword,
            status=status,
            security_level=security_level,
            parse_status=parse_status,
            index_status=index_status,
            document_type=document_type,
            discipline=discipline,
            upload_user_id=upload_user_id,
        )
        total = int(self.db.scalar(select(func.count(Document.id)).where(*filters)) or 0)
        items = list(
            self.db.scalars(
                select(Document)
                .where(*filters)
                .order_by(Document.id.desc())
                .offset(offset)
                .limit(safe_size)
            ).all()
        )
        return {"items": items, "total": total, "page": safe_page, "page_size": safe_size}

    def _project_document_filters(
        self,
        *,
        project_id: int,
        security_levels: list[str],
        category_ids: list[int] | None,
        keyword: str | None,
        status: str | None,
        security_level: str | None,
        parse_status: str | None,
        index_status: str | None,
        document_type: str | None,
        discipline: str | None,
        upload_user_id: int | None,
    ) -> list[object]:
        filters: list[object] = [
            Document.is_deleted.is_(False),
            Document.project_id == project_id,
            Document.knowledge_type == "project",
            Document.security_level.in_(security_levels),
        ]
        if category_ids:
            filters.append(or_(Document.category_id.in_(category_ids), Document.directory_id.in_(category_ids)))
        if keyword:
            like = f"%{keyword}%"
            filters.append(
                or_(
                    Document.file_name.like(like),
                    Document.document_name.like(like),
                    Document.document_type.like(like),
                    Document.discipline.like(like),
                )
            )
        if status:
            filters.append(self._project_document_status_filter(status))
        if security_level:
            filters.append(Document.security_level == security_level)
        if parse_status:
            filters.append(Document.parse_status == parse_status)
        if index_status:
            filters.append(Document.index_status == index_status)
        if document_type:
            filters.append(Document.document_type == document_type)
        if discipline:
            filters.append(Document.discipline == discipline)
        if upload_user_id is not None:
            filters.append(or_(Document.upload_user_id == upload_user_id, Document.created_by == upload_user_id))
        return filters

    def _project_document_status_filter(self, status: str) -> object:
        if status == "published":
            return or_(
                Document.status.in_(("已发布", "published", "active")),
                Document.document_status.in_(("reviewed", "active")),
                Document.review_status == "approved",
            )
        if status == "pending_review":
            return or_(
                Document.status.in_(("待审核", "pending", "pending_review")),
                Document.document_status == "pending_review",
                Document.review_status.in_(("draft", "reviewing", "rejected")),
            )
        return Document.status == status

    def get(self, document_id: int) -> Document | None:
        """按 ID 查询文档。"""

        return self.db.get(Document, document_id)

    def add(self, document: Document) -> Document:
        """新增文档。"""

        self.db.add(document)
        self.db.flush()
        return document

    def add_version(self, version: DocumentVersion) -> DocumentVersion:
        """新增文档版本。"""

        self.db.add(version)
        self.db.flush()
        return version

    def list_versions(self, document_id: int) -> list[DocumentVersion]:
        """查询文档版本。"""

        return list(
            self.db.scalars(
                select(DocumentVersion).where(DocumentVersion.document_id == document_id).order_by(DocumentVersion.version_no.desc())
            ).all()
        )

    def get_version(self, document_id: int, version_no: int) -> DocumentVersion | None:
        """
        按文档和版本号查询版本记录。

        参数:
            document_id: 文档ID。
            version_no: 同一文档内的版本号。

        返回:
            匹配的文档版本记录，不存在时返回 None。
        """

        return self.db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.version_no == version_no,
            )
        )

    def get_version_by_id(self, version_id: int) -> DocumentVersion | None:
        """按版本主键查询文档版本。"""

        return self.db.get(DocumentVersion, version_id)

    def get_current_version(self, document_id: int) -> DocumentVersion | None:
        """查询当前生效版本记录。"""

        return self.db.scalar(
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == document_id,
                or_(DocumentVersion.is_current.is_(True), DocumentVersion.is_current_version.is_(True)),
            )
            .order_by(DocumentVersion.version_no.desc())
        )

    def latest_version(self, document_id: int) -> DocumentVersion | None:
        """查询文档最新上传版本记录。"""

        return self.db.scalar(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_no.desc())
        )

    def delete(self, document: Document) -> None:
        """删除文档。"""

        self.db.delete(document)
        self.db.flush()

    def clear_versions(self, document_id: int) -> int:
        """
        物理删除文档版本记录。

        参数:
            document_id: 文档ID。

        返回:
            删除的版本记录数量。
        """

        result = self.db.execute(delete(DocumentVersion).where(DocumentVersion.document_id == document_id))
        self.db.flush()
        return int(result.rowcount or 0)

    def replace_chunks(
        self,
        document_id: int,
        chunks: list[DocumentChunk],
        version_no: int | None = None,
    ) -> list[DocumentChunk]:
        """替换文档 Chunk。"""

        self.deactivate_chunks(document_id, version_no=version_no)
        for chunk in chunks:
            self.db.add(chunk)
        self.db.flush()
        return chunks

    def deactivate_chunks(
        self,
        document_id: int,
        version_no: int | None = None,
        exclude_version_no: int | None = None,
    ) -> int:
        """
        将文档现有有效 Chunk 置为失效。

        参数:
            document_id: 文档ID。

        返回:
            置为失效的 Chunk 数量。
        """

        stmt = update(DocumentChunk).where(DocumentChunk.document_id == document_id, DocumentChunk.chunk_status == "active")
        if version_no is not None:
            stmt = stmt.where(DocumentChunk.version_no == version_no)
        if exclude_version_no is not None:
            stmt = stmt.where(DocumentChunk.version_no != exclude_version_no)
        result = self.db.execute(stmt.values(chunk_status="obsolete"))
        self.db.flush()
        return int(result.rowcount or 0)

    def clear_chunks(self, document_id: int) -> int:
        """
        物理删除文档 Chunk。

        参数:
            document_id: 文档ID。

        返回:
            删除的 Chunk 数量。

        说明:
            仅用于明确删除文档等维护场景。版本构建流程不得调用该方法，
            避免破坏 chat_citations 等历史引用。
        """

        result = self.db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        self.db.flush()
        return int(result.rowcount or 0)

    def list_chunks(
        self,
        document_id: int,
        include_obsolete: bool = False,
        version_no: int | None = None,
    ) -> list[DocumentChunk]:
        """
        查询文档 Chunk。

        参数:
            document_id: 文档ID。
            include_obsolete: 是否包含旧版本失效 Chunk。

        返回:
            Chunk 列表。
        """

        stmt = select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        if version_no is not None:
            stmt = stmt.where(DocumentChunk.version_no == version_no)
        if not include_obsolete:
            stmt = stmt.where(DocumentChunk.chunk_status == "active")
        return list(
            self.db.scalars(
                stmt.order_by(DocumentChunk.version_no.desc(), DocumentChunk.chunk_index)
            ).all()
        )

    def get_chunk(self, chunk_id: int) -> DocumentChunk | None:
        """
        按 ID 查询 Chunk。

        参数:
            chunk_id: Chunk ID。

        返回:
            Chunk 记录，不存在时返回 None。
        """

        return self.db.get(DocumentChunk, chunk_id)

    def searchable_chunks(
        self,
        security_levels: list[str] | None = None,
        *,
        knowledge_type: str | None = None,
        project_id: int | None = None,
        query_terms: list[str] | None = None,
        document_ids: list[int] | None = None,
        chunk_ids: list[int] | None = None,
        page_numbers_by_document: dict[int, list[int]] | None = None,
    ) -> list[tuple[DocumentChunk, Document]]:
        """查询可参与检索的 Chunk 和文档。"""

        stmt = (
            select(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.review_status == "approved", Document.index_status == "indexed")
            .where(Document.review_status != "archived")
            .where(Document.is_deleted.is_(False), Document.is_current_version.is_(True))
            .where(DocumentChunk.chunk_status == "active", DocumentChunk.version_no == Document.version_no)
        )
        if security_levels is not None:
            stmt = stmt.where(Document.security_level.in_(security_levels), DocumentChunk.security_level.in_(security_levels))
        if knowledge_type:
            stmt = stmt.where(Document.knowledge_type == knowledge_type, DocumentChunk.knowledge_type == knowledge_type)
        if project_id is not None:
            stmt = stmt.where(Document.project_id == project_id, DocumentChunk.project_id == project_id)
        if document_ids:
            stmt = stmt.where(Document.id.in_(document_ids), DocumentChunk.document_id.in_(document_ids))
        if chunk_ids:
            stmt = stmt.where(DocumentChunk.id.in_(chunk_ids))
        page_scope = self._chunk_page_scope_filters(page_numbers_by_document)
        if page_scope:
            stmt = stmt.where(or_(*page_scope))
        limited_terms = self._limited_query_terms(query_terms)
        if limited_terms:
            stmt = stmt.where(or_(*[DocumentChunk.content.ilike(f"%{term}%") for term in limited_terms]))
        return list(self.db.execute(stmt).all())

    def _limited_query_terms(self, query_terms: list[str] | None) -> list[str]:
        return [term.strip() for term in (query_terms or []) if len(term.strip()) >= 2][:8]

    def _chunk_page_scope_filters(self, page_numbers_by_document: dict[int, list[int]] | None) -> list[object]:
        filters: list[object] = []
        for document_id, page_numbers in (page_numbers_by_document or {}).items():
            if not page_numbers:
                continue
            filters.append(and_(DocumentChunk.document_id == document_id, DocumentChunk.page_number.in_(page_numbers)))
        return filters
