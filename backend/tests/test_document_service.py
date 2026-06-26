"""
Document Service Tests

职责：
1. 验证文档版本切换时旧索引失效逻辑
2. 验证外部向量库异常不会阻断新版本上传主流程
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.core.exceptions import AppException  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    Document,
    DocumentAsset,
    DocumentChunk,
    DocumentPage,
    DocumentVersion,
    IndexTask,
    KnowledgeBase,
    KnowledgeCategory,
    PageIndex,
    Role,
    ReviewLog,
    ReviewTask,
)
from app.models.user import User  # noqa: E402
from app.services.document_service import DocumentService  # noqa: E402
from app.services.review_service import ReviewService  # noqa: E402


def make_session() -> Session:
    """
    创建独立的内存数据库会话。

    返回：
        用于单测的 SQLAlchemy Session。
    """

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_factory()


def make_fk_session() -> Session:
    """
    创建启用外键校验的内存数据库会话，用于复现 MySQL 约束行为。
    返回：
        用于单测的 SQLAlchemy Session。
    """

    engine = create_engine("sqlite:///:memory:", future=True)

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_factory()


def make_operator() -> User:
    """创建不需要落库的测试操作人。"""

    user = User(id=1, username="tester", password_hash="x", real_name="Tester")
    user.roles = [Role(id=1, name="Admin", code="admin", enabled=True, security_level="confidential")]
    return user


def test_pdf_preview_uses_original_pdf_file() -> None:
    """PDF 文档预览应直接返回当前版本原始文件。"""

    db = make_session()
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "origin.pdf"
            source_path.write_bytes(b"%PDF-1.5 origin")
            document = Document(
                knowledge_base_id=1,
                knowledge_type="base",
                file_name="origin.pdf",
                file_type="pdf",
                file_size=source_path.stat().st_size,
                storage_path=str(source_path),
                review_status="draft",
                index_status="not_indexed",
                version_no=1,
                current_version=False,
            )
            db.add(document)
            db.flush()
            db.add(
                DocumentVersion(
                    document_id=document.id,
                    version_no=1,
                    file_name="origin.pdf",
                    file_type="pdf",
                    file_size=source_path.stat().st_size,
                    storage_path=str(source_path),
                    version_status="draft",
                    review_status="draft",
                    index_status="not_indexed",
                    is_current=False,
                )
            )
            db.commit()

            preview_source = DocumentService(db).get_document_pdf_preview(document.id, make_operator())

        assert preview_source.source_kind == "original_pdf"
        assert preview_source.file_name == "origin.pdf"
        assert preview_source.storage_path == str(source_path)
        assert preview_source.object_key is None
    finally:
        db.close()


def test_pdf_preview_creates_converted_pdf_asset_for_office_file() -> None:
    """Office 类非 PDF 文档预览应复用转换链路生成转换 PDF 资产。"""

    db = make_session()
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "proposal.docx"
            converted_pdf = Path(temp_dir) / "proposal.pdf"
            source_path.write_bytes(b"fake-docx")
            converted_pdf.write_bytes(b"%PDF-1.5 converted")
            document = Document(
                knowledge_base_id=1,
                knowledge_type="base",
                file_name="proposal.docx",
                file_type="docx",
                file_size=source_path.stat().st_size,
                storage_path=str(source_path),
                review_status="draft",
                index_status="not_indexed",
                version_no=1,
                current_version=False,
                created_by=1,
            )
            db.add(document)
            db.flush()
            db.add(
                DocumentVersion(
                    document_id=document.id,
                    version_no=1,
                    file_name="proposal.docx",
                    file_type="docx",
                    file_size=source_path.stat().st_size,
                    storage_path=str(source_path),
                    version_status="draft",
                    review_status="draft",
                    index_status="not_indexed",
                    is_current=False,
                    created_by=1,
                )
            )
            db.commit()

            rollback_count = 0
            original_rollback = db.rollback

            def spy_rollback() -> None:
                nonlocal rollback_count
                rollback_count += 1
                original_rollback()

            def convert_after_transaction_released(source: str, document_id: int, version_no: int) -> SimpleNamespace:
                assert rollback_count >= 1
                return SimpleNamespace(pdf_path=str(converted_pdf), reused=False)

            with (
                patch("app.services.document_service.LibreOfficeConversionService") as conversion_service_type,
                patch("app.services.document_asset_service.get_minio_client", return_value=None),
                patch.object(db, "rollback", side_effect=spy_rollback),
            ):
                conversion_service = conversion_service_type.return_value
                conversion_service.should_convert.return_value = True
                conversion_service.convert.side_effect = convert_after_transaction_released
                preview_source = DocumentService(db).get_document_pdf_preview(document.id, make_operator())

            assets = db.scalars(select(DocumentAsset).where(DocumentAsset.document_id == document.id)).all()

        assert preview_source.source_kind == "converted_pdf"
        assert preview_source.file_name == "proposal.pdf"
        assert preview_source.storage_path
        assert len(assets) == 1
        assert assets[0].asset_type == "converted_pdf"
        assert assets[0].version_no == 1
        conversion_service.convert.assert_called_once_with(str(source_path), document.id, 1)
        assert rollback_count >= 1
    finally:
        db.close()


def test_deactivate_document_index_artifacts_keeps_db_state_when_vector_delete_fails() -> None:
    """
    旧版本向量删除失败时，数据库 Chunk 仍应先置为失效。

    业务规则：
        新版本上传以数据库版本切换为主链路，Milvus 清理失败只能记录告警，
        不能导致文件已上传但版本记录无法创建。
    """

    db = make_session()
    try:
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="demo.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/demo.md",
            review_status="approved",
            index_status="indexed",
            version_no=1,
            current_version=True,
        )
        db.add(document)
        db.flush()

        chunk = DocumentChunk(
            knowledge_base_id=1,
            document_id=document.id,
            knowledge_type="base",
            version_no=1,
            chunk_status="active",
            chunk_index=1,
            content="demo content",
            vector_id="doc_1_chunk_1_v1",
        )
        db.add(chunk)
        db.commit()

        service = DocumentService(db)
        original_milvus_host = service.settings.milvus_host
        service.settings.milvus_host = "127.0.0.1"

        try:
            with patch(
                "app.services.document_service.IndexService.delete_document_index",
                side_effect=RuntimeError("milvus offline"),
            ) as delete_document_index:
                deactivated_count = service._deactivate_document_index_artifacts(document)
        finally:
            service.settings.milvus_host = original_milvus_host

        db.commit()
        refreshed_chunk = db.scalars(select(DocumentChunk).where(DocumentChunk.id == chunk.id)).one()

        assert deactivated_count == 1
        delete_document_index.assert_called_once_with(document.id, ["doc_1_chunk_1_v1"])
        assert refreshed_chunk.chunk_status == "obsolete"
    finally:
        db.close()


def test_deactivate_document_index_artifacts_can_skip_synchronous_vector_delete() -> None:
    """
    新版本上传路径不应同步访问外部向量库。

    业务规则：
        上传新版本只需要先让数据库中的旧 Chunk 失效；旧向量即使暂留在 Milvus，
        检索回查也会按 Chunk 状态和版本号过滤，不能让外部清理拖慢上传响应。
    """

    db = make_session()
    try:
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="demo.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/demo.md",
            review_status="approved",
            index_status="indexed",
            version_no=1,
            current_version=True,
        )
        db.add(document)
        db.flush()

        chunk = DocumentChunk(
            knowledge_base_id=1,
            document_id=document.id,
            knowledge_type="base",
            version_no=1,
            chunk_status="active",
            chunk_index=1,
            content="demo content",
            vector_id="doc_1_chunk_1_v1",
        )
        db.add(chunk)
        db.commit()

        service = DocumentService(db)
        with patch("app.services.document_service.IndexService.delete_document_index") as delete_document_index:
            deactivated_count = service._deactivate_document_index_artifacts(
                document,
                delete_external_vectors=False,
            )

        db.commit()
        refreshed_chunk = db.scalars(select(DocumentChunk).where(DocumentChunk.id == chunk.id)).one()

        assert deactivated_count == 1
        delete_document_index.assert_not_called()
        assert refreshed_chunk.chunk_status == "obsolete"
    finally:
        db.close()

def test_upload_document_creates_draft_version_without_review_task() -> None:
    """首次上传只生成草稿版本和解析任务，不自动进入审核队列。"""

    db = make_session()
    try:
        operator = make_operator()
        knowledge_base = KnowledgeBase(name="Base", code="base", type="base", enabled=True)
        category = KnowledgeCategory(scope_type="base", name="General", code="general", enabled=True)
        db.add_all([knowledge_base, category])
        db.commit()

        service = DocumentService(db)
        with (
            patch(
                "app.services.document_service.UploadService.save",
                new=AsyncMock(
                    return_value={
                        "file_name": "draft.md",
                        "file_type": "md",
                        "file_size": 20,
                        "storage_path": "storage/uploads/draft.md",
                    }
                ),
            ),
            patch("app.services.document_service.IndexTaskService.create_parse_task") as create_parse_task,
        ):
            document = asyncio.run(service.upload_document(knowledge_base.id, object(), operator, category.id))  # type: ignore[arg-type]

        version = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document.id, DocumentVersion.version_no == 1))
        assert document.review_status == "draft"
        assert document.document_status == "pending_review"
        assert document.current_version is False
        assert document.security_level == "internal"
        assert version is not None
        assert version.review_status == "draft"
        assert version.version_status == "draft"
        assert version.is_current is False
        assert version.security_level == "internal"
        assert not list(db.scalars(select(ReviewTask).where(ReviewTask.document_id == document.id)).all())
        create_parse_task.assert_called_once()
    finally:
        db.close()


def test_update_document_security_level_syncs_versions_chunks_and_page_indexes() -> None:
    """修改文档密级时，所有可作为 Evidence 来源的记录必须同步更新。"""

    db = make_session()
    try:
        operator = make_operator()
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="secure.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/secure.md",
            document_status="active",
            parse_status="success",
            review_status="approved",
            index_status="indexed",
            version_no=1,
            current_version=True,
            security_level="internal",
        )
        db.add(document)
        db.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_no=1,
            file_name="secure.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/secure.md",
            version_status="current",
            parse_status="success",
            review_status="approved",
            index_status="indexed",
            is_current=True,
            security_level="internal",
        )
        chunk = DocumentChunk(
            knowledge_base_id=1,
            document_id=document.id,
            knowledge_type="base",
            version_no=1,
            chunk_status="active",
            chunk_index=1,
            content="secure content",
            security_level="internal",
        )
        page = DocumentPage(
            knowledge_base_id=1,
            document_id=document.id,
            version_no=1,
            page_no=1,
            page_text="page content",
            security_level="internal",
        )
        db.add_all([version, chunk, page])
        db.flush()
        page_index = PageIndex(
            knowledge_base_id=1,
            document_id=document.id,
            page_id=page.id,
            chunk_id=chunk.id,
            version_no=1,
            page_no=1,
            index_text="page content",
            status="published",
            security_level="internal",
        )
        db.add(page_index)
        db.commit()

        updated = DocumentService(db).update_document_security_level(document.id, "public", operator)

        db.refresh(version)
        db.refresh(chunk)
        db.refresh(page)
        db.refresh(page_index)
        assert updated.security_level == "public"
        assert updated.index_status == "invalid"
        assert version.security_level == "public"
        assert version.index_status == "invalid"
        assert chunk.security_level == "public"
        assert page.security_level == "public"
        assert page_index.security_level == "public"
        assert page_index.status == "obsolete"
    finally:
        db.close()


def test_create_version_does_not_replace_current_document_before_review_and_index() -> None:
    """上传新版本只新增版本记录，不替换当前生效版本。"""

    db = make_session()
    try:
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="v1.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/v1.md",
            document_status="active",
            parse_status="success",
            review_status="approved",
            index_status="indexed",
            version_no=1,
            current_version=True,
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentVersion(
                document_id=document.id,
                version_no=1,
                category_id=1,
                file_name="v1.md",
                file_type="md",
                file_size=10,
                storage_path="storage/uploads/v1.md",
                version_status="current",
                parse_status="success",
                review_status="approved",
                index_status="indexed",
                is_current=True,
            )
        )
        db.commit()

        service = DocumentService(db)
        service.category_service.validate_for_document = lambda *args, **kwargs: SimpleNamespace(id=2)  # type: ignore[method-assign]
        with (
            patch(
                "app.services.document_service.UploadService.save",
                new=AsyncMock(
                    return_value={
                        "file_name": "v2.md",
                        "file_type": "md",
                        "file_size": 20,
                        "storage_path": "storage/uploads/v2.md",
                    }
                ),
            ),
            patch("app.services.document_service.IndexTaskService.create_parse_task") as create_parse_task,
        ):
            version = asyncio.run(service.create_version(document.id, object(), make_operator(), "change", 2))  # type: ignore[arg-type]

        db.refresh(document)
        current_version = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document.id, DocumentVersion.is_current.is_(True)))

        assert document.version_no == 1
        assert document.file_name == "v1.md"
        assert current_version is not None
        assert current_version.version_no == 1
        assert version.version_no == 2
        assert version.is_current is False
        assert version.review_status == "draft"
        assert version.version_status == "draft"
        assert version.parse_status == "unparsed"
        assert not list(db.scalars(select(ReviewTask).where(ReviewTask.document_id == document.id)).all())
        create_parse_task.assert_called_once()
        parse_args = create_parse_task.call_args.args
        assert parse_args[-4] == document.id
        assert parse_args[-3] == 2
        assert parse_args[-2] == version.id
        assert parse_args[-1].id == 1
    finally:
        db.close()


def test_draft_version_can_be_parsed_for_review_preview() -> None:
    """上传后的草稿版本允许先解析，供审核人员查看预览和分块。"""

    db = make_session()
    try:
        operator = make_operator()
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="draft.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/draft.md",
            document_status="pending_review",
            parse_status="unparsed",
            review_status="draft",
            index_status="not_indexed",
            version_no=1,
            current_version=False,
        )
        db.add(document)
        db.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_no=1,
            category_id=1,
            file_name="draft.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/draft.md",
            version_status="draft",
            parse_status="unparsed",
            review_status="draft",
            index_status="not_indexed",
            is_current=False,
        )
        db.add(version)
        db.commit()

        service = DocumentService(db)
        with patch.object(
            service,
            "_parse_to_chunks",
            return_value=[
                DocumentChunk(
                    knowledge_base_id=1,
                    document_id=document.id,
                    knowledge_type="base",
                    version_no=1,
                    chunk_status="active",
                    chunk_index=1,
                    content="draft preview content",
                )
            ],
        ):
            result = service.parse_document_version(document.id, 1, operator)

        db.refresh(document)
        db.refresh(version)
        chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all()

        assert result["chunk_count"] == 1
        assert document.parse_status == "success"
        assert version.parse_status == "success"
        assert len(chunks) == 1
        assert chunks[0].content == "draft preview content"
    finally:
        db.close()


def test_parse_version_commits_running_status_before_parsing() -> None:
    """解析开始状态要先提交，避免解析耗时期间锁住文档主表。"""

    db = make_session()
    try:
        operator = make_operator()
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="draft.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/draft.md",
            document_status="pending_review",
            parse_status="unparsed",
            review_status="draft",
            index_status="not_indexed",
            version_no=1,
            current_version=False,
        )
        db.add(document)
        db.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_no=1,
            category_id=1,
            file_name="draft.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/draft.md",
            version_status="draft",
            parse_status="unparsed",
            review_status="draft",
            index_status="not_indexed",
            is_current=False,
        )
        db.add(version)
        db.commit()

        service = DocumentService(db)
        original_commit = db.commit
        commit_count = 0

        def tracked_commit() -> None:
            nonlocal commit_count
            commit_count += 1
            original_commit()

        def fake_parse(_: object) -> list[DocumentChunk]:
            assert commit_count == 1
            return [
                DocumentChunk(
                    knowledge_base_id=1,
                    document_id=document.id,
                    knowledge_type="base",
                    version_no=1,
                    chunk_status="active",
                    chunk_index=1,
                    content="draft preview content",
                )
            ]

        with patch.object(db, "commit", side_effect=tracked_commit), patch.object(service, "_parse_to_chunks", side_effect=fake_parse):
            service.parse_document_version(document.id, 1, operator)

        assert commit_count == 2
    finally:
        db.close()


def test_draft_version_cannot_create_index_build_task() -> None:
    """未审核版本即使已解析，也不能创建索引构建任务。"""

    db = make_session()
    try:
        operator = make_operator()
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="draft.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/draft.md",
            document_status="pending_review",
            parse_status="success",
            review_status="draft",
            index_status="not_indexed",
            version_no=1,
            current_version=False,
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentVersion(
                document_id=document.id,
                version_no=1,
                category_id=1,
                file_name="draft.md",
                file_type="md",
                file_size=10,
                storage_path="storage/uploads/draft.md",
                version_status="draft",
                parse_status="success",
                review_status="draft",
                index_status="not_indexed",
                is_current=False,
            )
        )
        db.commit()

        service = DocumentService(db)

        try:
            service.create_index_build_task(document.id, operator)
        except AppException as exc:
            assert "审核通过" in exc.message
        else:
            raise AssertionError("draft version must not create index build task")
    finally:
        db.close()


def test_submit_review_targets_new_draft_version_and_keeps_current_document_effective() -> None:
    """提交新版本审核时只创建新版本审核任务，不影响旧版本线上检索状态。"""

    db = make_session()
    try:
        operator = make_operator()
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="v1.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/v1.md",
            document_status="active",
            parse_status="success",
            review_status="approved",
            index_status="indexed",
            version_no=1,
            current_version=True,
        )
        db.add(document)
        db.flush()
        v1 = DocumentVersion(
            document_id=document.id,
            version_no=1,
            category_id=1,
            file_name="v1.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/v1.md",
            version_status="current",
            parse_status="success",
            review_status="approved",
            index_status="indexed",
            is_current=True,
        )
        v2 = DocumentVersion(
            document_id=document.id,
            version_no=2,
            category_id=1,
            file_name="v2.md",
            file_type="md",
            file_size=20,
            storage_path="storage/uploads/v2.md",
            version_status="draft",
            parse_status="success",
            review_status="draft",
            index_status="not_indexed",
            is_current=False,
        )
        db.add_all([v1, v2])
        db.commit()

        task = ReviewService(db).submit_review(document.id, operator, "submit v2", version_no=2)

        db.refresh(document)
        db.refresh(v1)
        db.refresh(v2)
        assert task.version_id == v2.id
        assert task.version_no == 2
        assert task.review_status == "reviewing"
        assert v2.review_status == "reviewing"
        assert v2.version_status == "pending_review"
        assert document.review_status == "approved"
        assert document.index_status == "indexed"
        assert v1.is_current is True
        assert v2.is_current is False
    finally:
        db.close()


def test_list_review_tasks_includes_document_display_fields() -> None:
    """审核任务列表应携带前端表格所需的文档展示字段。"""

    db = make_session()
    try:
        uploader = User(username="uploader", password_hash="x", real_name="上传人")
        category = KnowledgeCategory(
            scope_type="base",
            name="工艺资料",
            code="process",
            sort_order=1,
            enabled=True,
        )
        db.add_all([uploader, category])
        db.flush()
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="old.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/old.md",
            category_id=category.id,
            document_status="active",
            parse_status="success",
            review_status="approved",
            index_status="indexed",
            version_no=2,
            current_version=True,
            created_by=uploader.id,
        )
        db.add(document)
        db.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_no=2,
            category_id=category.id,
            file_name="new.md",
            file_type="md",
            file_size=20,
            storage_path="storage/uploads/new.md",
            version_status="pending_review",
            parse_status="success",
            review_status="reviewing",
            index_status="not_indexed",
            is_current=False,
            created_by=uploader.id,
        )
        db.add(version)
        db.flush()
        task = ReviewTask(
            document_id=document.id,
            version_id=version.id,
            version_no=version.version_no,
            review_status="reviewing",
            review_comment="待审核",
        )
        db.add(task)
        db.commit()

        result = ReviewService(db).list_tasks()

        assert len(result) == 1
        item = result[0]
        assert item.document_file_name == "new.md"
        assert item.document_category_name == "工艺资料"
        assert item.document_category_path == "工艺资料"
        assert item.display_version_no == 2
        assert item.uploader_id == uploader.id
        assert item.uploader_name == "上传人"
        assert item.uploader_username == "uploader"
    finally:
        db.close()


def test_submit_review_lock_timeout_rolls_back_and_returns_business_error() -> None:
    """提交审核遇到 MySQL 锁等待超时时，应回滚本次状态变更并返回业务异常。"""

    db = make_session()
    try:
        operator = make_operator()
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="draft.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/draft.md",
            document_status="pending_review",
            parse_status="success",
            review_status="draft",
            index_status="not_indexed",
            version_no=1,
            current_version=False,
        )
        db.add(document)
        db.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_no=1,
            category_id=1,
            file_name="draft.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/draft.md",
            version_status="draft",
            parse_status="success",
            review_status="draft",
            index_status="not_indexed",
            is_current=False,
        )
        db.add(version)
        db.commit()

        lock_error = OperationalError(
            "UPDATE documents SET review_status=%s WHERE documents.id = %s",
            {"review_status": "submitted", "documents_id": document.id},
            Exception(1205, "Lock wait timeout exceeded; try restarting transaction"),
        )

        with patch("app.repositories.review_repository.ReviewRepository.add_task", side_effect=lock_error):
            try:
                ReviewService(db).submit_review(document.id, operator, "submit")
            except AppException as exc:
                assert exc.status_code == 409
                assert "稍后重试" in exc.message
            else:
                raise AssertionError("lock timeout must be converted to AppException")

        refreshed_document = db.get(Document, document.id)
        refreshed_version = db.get(DocumentVersion, version.id)
        assert refreshed_document is not None
        assert refreshed_version is not None
        assert refreshed_document.review_status == "draft"
        assert refreshed_version.review_status == "draft"
    finally:
        db.close()


def test_build_new_version_success_switches_current_version_and_invalidates_old_chunks() -> None:
    """新版本索引全部成功后才切换当前版本并失效旧版本 Chunk。"""

    db = make_session()
    try:
        operator = make_operator()
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="v1.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/v1.md",
            document_status="active",
            parse_status="success",
            review_status="approved",
            index_status="indexed",
            version_no=1,
            current_version=True,
        )
        db.add(document)
        db.flush()
        v1 = DocumentVersion(
            document_id=document.id,
            version_no=1,
            file_name="v1.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/v1.md",
            version_status="current",
            parse_status="success",
            review_status="approved",
            index_status="indexed",
            is_current=True,
        )
        v2 = DocumentVersion(
            document_id=document.id,
            version_no=2,
            file_name="v2.md",
            file_type="md",
            file_size=20,
            storage_path="storage/uploads/v2.md",
            version_status="approved",
            parse_status="success",
            review_status="approved",
            index_status="not_indexed",
            is_current=False,
        )
        db.add_all([v1, v2])
        db.flush()
        old_chunk = DocumentChunk(
            knowledge_base_id=1,
            document_id=document.id,
            knowledge_type="base",
            version_no=1,
            chunk_status="active",
            chunk_index=1,
            content="old",
            vector_id="old-vector",
        )
        new_chunk = DocumentChunk(
            knowledge_base_id=1,
            document_id=document.id,
            knowledge_type="base",
            version_no=2,
            chunk_status="active",
            chunk_index=1,
            content="new",
            vector_id="new-vector",
        )
        db.add_all([old_chunk, new_chunk])
        db.commit()

        with (
            patch("app.services.document_service.IndexPipelineService.build_all", return_value={"publish": {"published_page_index_count": 1}}),
            patch.object(DocumentService, "_delete_obsolete_vectors_best_effort") as delete_vectors,
        ):
            result = DocumentService(db).build_document_index(document.id, operator, version_no=2)

        db.refresh(document)
        db.refresh(v1)
        db.refresh(v2)
        db.refresh(old_chunk)
        db.refresh(new_chunk)

        assert result["version_no"] == 2
        assert document.version_no == 2
        assert document.file_name == "v2.md"
        assert v1.is_current is False
        assert v1.version_status == "historical"
        assert v1.index_status == "invalid"
        assert v2.is_current is True
        assert v2.version_status == "current"
        assert v2.index_status == "indexed"
        assert old_chunk.chunk_status == "obsolete"
        assert new_chunk.chunk_status == "active"
        delete_vectors.assert_called_once()
    finally:
        db.close()


def test_build_new_version_failure_keeps_old_version_effective() -> None:
    """新版本索引失败时，旧版本继续保持当前生效和可检索。"""

    db = make_session()
    try:
        operator = make_operator()
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="v1.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/v1.md",
            document_status="active",
            parse_status="success",
            review_status="approved",
            index_status="indexed",
            version_no=1,
            current_version=True,
        )
        db.add(document)
        db.flush()
        v1 = DocumentVersion(
            document_id=document.id,
            version_no=1,
            file_name="v1.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/v1.md",
            version_status="current",
            parse_status="success",
            review_status="approved",
            index_status="indexed",
            is_current=True,
        )
        v2 = DocumentVersion(
            document_id=document.id,
            version_no=2,
            file_name="v2.md",
            file_type="md",
            file_size=20,
            storage_path="storage/uploads/v2.md",
            version_status="approved",
            parse_status="success",
            review_status="approved",
            index_status="not_indexed",
            is_current=False,
        )
        db.add_all([v1, v2])
        db.flush()
        old_chunk = DocumentChunk(
            knowledge_base_id=1,
            document_id=document.id,
            knowledge_type="base",
            version_no=1,
            chunk_status="active",
            chunk_index=1,
            content="old",
        )
        new_chunk = DocumentChunk(
            knowledge_base_id=1,
            document_id=document.id,
            knowledge_type="base",
            version_no=2,
            chunk_status="active",
            chunk_index=1,
            content="new",
        )
        db.add_all([old_chunk, new_chunk])
        db.commit()

        with patch("app.services.document_service.IndexPipelineService.build_all", side_effect=RuntimeError("build failed")):
            try:
                DocumentService(db).build_document_index(document.id, operator, version_no=2)
                raise AssertionError("build should fail")
            except AppException:
                pass

        db.refresh(document)
        db.refresh(v1)
        db.refresh(v2)
        db.refresh(old_chunk)
        db.refresh(new_chunk)

        assert document.version_no == 1
        assert document.file_name == "v1.md"
        assert document.index_status == "indexed"
        assert v1.is_current is True
        assert v1.index_status == "indexed"
        assert v2.is_current is False
        assert v2.index_status == "failed"
        assert old_chunk.chunk_status == "active"
        assert new_chunk.chunk_status == "active"
    finally:
        db.close()


def test_build_index_rejects_when_active_full_build_task_exists() -> None:
    """同一文档已有构建任务排队或执行中时，不允许重复发起索引构建。"""

    db = make_session()
    try:
        operator = make_operator()
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="demo.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/demo.md",
            document_status="reviewed",
            parse_status="success",
            review_status="approved",
            index_status="not_indexed",
            version_no=1,
            current_version=False,
        )
        db.add(document)
        db.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_no=1,
            file_name="demo.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/demo.md",
            version_status="approved",
            parse_status="success",
            review_status="approved",
            index_status="not_indexed",
            is_current=False,
        )
        db.add(version)
        db.flush()
        db.add(
            DocumentChunk(
                knowledge_base_id=1,
                document_id=document.id,
                knowledge_type="base",
                version_no=1,
                chunk_status="active",
                chunk_index=1,
                content="content",
            )
        )
        db.add(IndexTask(document_id=document.id, version_id=version.id, version_no=1, task_type="full_build", status="pending"))
        db.commit()

        try:
            DocumentService(db).build_document_index(document.id, operator, version_no=1)
            raise AssertionError("duplicate build should be rejected")
        except AppException as exc:
            assert "索引构建中" in str(exc)
    finally:
        db.close()


def test_create_index_build_task_marks_document_and_version_indexing() -> None:
    """异步构建任务创建成功后，应立即展示索引构建中状态并禁止再次触发。"""

    db = make_session()
    try:
        operator = make_operator()
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="demo.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/demo.md",
            document_status="reviewed",
            parse_status="success",
            review_status="approved",
            index_status="not_indexed",
            version_no=1,
            current_version=False,
        )
        db.add(document)
        db.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_no=1,
            file_name="demo.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/demo.md",
            version_status="approved",
            parse_status="success",
            review_status="approved",
            index_status="not_indexed",
            is_current=False,
        )
        db.add(version)
        db.commit()

        def fake_create_build_task(document_id: int, version_no: int, user: User, version_id: int | None = None) -> IndexTask:
            task = IndexTask(
                document_id=document_id,
                version_id=version_id,
                version_no=version_no,
                task_type="full_build",
                status="pending",
                progress=0,
                created_by=user.id,
            )
            db.add(task)
            db.flush()
            return task

        with patch("app.services.document_service.IndexTaskService.create_build_task", side_effect=fake_create_build_task):
            task = DocumentService(db).create_index_build_task(document.id, operator, version_no=1)

        db.refresh(document)
        db.refresh(version)
        assert task.task_type == "full_build"
        assert document.index_status == "indexing"
        assert version.index_status == "indexing"
        assert document.build_started_at is not None
        assert version.build_started_at is not None
    finally:
        db.close()


def test_delete_document_queues_external_cleanup_without_waiting_for_milvus() -> None:
    """删除文档只同步清理数据库记录，外部向量和文件交给后台清理。"""

    db = make_session()
    try:
        operator = make_operator()
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="demo.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/demo.md",
            review_status="approved",
            index_status="indexed",
            version_no=1,
            current_version=True,
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentVersion(
                document_id=document.id,
                version_no=1,
                file_name="demo.md",
                file_type="md",
                file_size=10,
                storage_path="storage/uploads/demo.md",
                version_status="current",
                parse_status="success",
                review_status="approved",
                index_status="indexed",
                is_current=True,
            )
        )
        db.add(
            DocumentChunk(
                knowledge_base_id=1,
                document_id=document.id,
                knowledge_type="base",
                version_no=1,
                chunk_status="active",
                chunk_index=1,
                content="demo content",
                vector_id="doc_1_chunk_1_v1",
            )
        )
        db.add(
            DocumentAsset(
                document_id=document.id,
                version_no=1,
                asset_type="mineru_result",
                file_name="result.json",
                mime_type="application/json",
                storage_backend="local",
                storage_path="libreoffice_work/1/v1/mineru/result.json",
                object_key="document-assets/1/v1/mineru/result.json",
                file_size=100,
                status="ready",
            )
        )
        db.commit()

        with (
            patch("app.services.document_service.IndexService.delete_document_index") as sync_delete,
            patch.object(DocumentService, "_schedule_document_external_cleanup") as schedule_cleanup,
        ):
            result = DocumentService(db).delete_document(document.id, operator)

        assert result["deleted"] is True
        assert result["document_chunks"] == 1
        assert result["document_versions"] == 1
        assert result["document_assets"] == 1
        assert result["deleted_asset_files"] == 0
        assert result["deleted_asset_objects"] == 0
        assert result["external_cleanup_queued"] is True
        assert result["pending_vector_count"] == 1
        assert result["pending_file_count"] == 2
        assert result["pending_asset_object_count"] == 1
        sync_delete.assert_not_called()
        schedule_cleanup.assert_called_once()
    finally:
        db.close()


def test_delete_document_clears_version_fk_dependents_before_versions() -> None:
    """删除文档时应先清理引用版本的任务和审核记录，避免外键阻塞版本删除。"""

    db = make_fk_session()
    try:
        operator = make_operator()
        db.add(operator)
        db.flush()
        knowledge_base = KnowledgeBase(
            name="Base Knowledge",
            code="base-knowledge-delete-fk",
            type="base",
            created_by=operator.id,
        )
        db.add(knowledge_base)
        db.flush()
        document = Document(
            knowledge_base_id=knowledge_base.id,
            knowledge_type="base",
            file_name="demo.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/demo.md",
            review_status="approved",
            index_status="indexed",
            version_no=1,
            current_version=True,
            created_by=operator.id,
        )
        db.add(document)
        db.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_no=1,
            file_name="demo.md",
            file_type="md",
            file_size=10,
            storage_path="storage/uploads/demo.md",
            version_status="current",
            parse_status="success",
            review_status="approved",
            index_status="indexed",
            is_current=True,
            created_by=operator.id,
        )
        db.add(version)
        db.flush()
        db.add(
            IndexTask(
                document_id=document.id,
                version_id=version.id,
                version_no=1,
                task_type="full_build",
                status="pending",
                created_by=operator.id,
            )
        )
        db.add(
            ReviewTask(
                document_id=document.id,
                version_id=version.id,
                version_no=1,
                reviewer_id=operator.id,
                review_status="reviewing",
            )
        )
        db.add(
            ReviewLog(
                document_id=document.id,
                version_id=version.id,
                version_no=1,
                action="submit",
                operator_id=operator.id,
            )
        )
        document_id = document.id
        db.commit()

        with patch.object(DocumentService, "_schedule_document_external_cleanup") as schedule_cleanup:
            result = DocumentService(db).delete_document(document_id, operator)

        assert result["deleted"] is True
        assert result["index_tasks"] == 1
        assert result["review_tasks"] == 1
        assert result["review_logs"] == 1
        assert result["document_versions"] == 1
        assert not list(db.scalars(select(IndexTask).where(IndexTask.document_id == document_id)).all())
        assert not list(db.scalars(select(ReviewTask).where(ReviewTask.document_id == document_id)).all())
        assert not list(db.scalars(select(ReviewLog).where(ReviewLog.document_id == document_id)).all())
        assert not list(db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document_id)).all())
        schedule_cleanup.assert_called_once()
    finally:
        db.close()
