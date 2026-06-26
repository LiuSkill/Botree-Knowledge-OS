"""
Document Repository

负责：
1. 文档、版本、Chunk 数据库访问
2. 支持审核、解析、索引和检索服务
3. 保持来源追踪字段完整
"""

from __future__ import annotations

from sqlalchemy import delete, select, update
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

        stmt = select(Document).order_by(Document.id.desc())
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
            stmt = stmt.where(Document.file_name.like(f"%{keyword}%"))
        return list(self.db.scalars(stmt).all())

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
            select(DocumentVersion).where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.is_current.is_(True),
            )
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

    def searchable_chunks(self, security_levels: list[str] | None = None) -> list[tuple[DocumentChunk, Document]]:
        """查询可参与检索的 Chunk 和文档。"""

        stmt = (
            select(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.review_status == "approved", Document.index_status == "indexed")
            .where(Document.review_status != "archived")
            .where(DocumentChunk.chunk_status == "active", DocumentChunk.version_no == Document.version_no)
        )
        if security_levels is not None:
            stmt = stmt.where(Document.security_level.in_(security_levels), DocumentChunk.security_level.in_(security_levels))
        return list(self.db.execute(stmt).all())
