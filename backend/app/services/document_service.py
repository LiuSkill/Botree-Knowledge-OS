"""
Document Service

负责：
1. 文档上传、版本管理、删除与下载信息返回
2. 文档解析、Chunk 生成、PageIndex 落库与索引构建
3. 统一控制项目隔离、审核状态、索引状态与失败信息回写
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import shutil
from threading import Thread
from types import SimpleNamespace

from fastapi import UploadFile
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException, is_database_lock_error
from app.core.minio import get_minio_client
from app.knowledge.chunking.chunk_builder import ChunkBuilder
from app.knowledge.indexing.milvus_indexer import MilvusIndexer
from app.knowledge.indexing.index_service import IndexService
from app.knowledge.ingestion.upload_service import UploadService
from app.knowledge.parsing.parsed_content_cleaner import ParsedContentCleaner
from app.knowledge.parsing.parser_service import ParserService
from app.models.document_asset import DocumentAsset
from app.models.document import Document, DocumentChunk, DocumentVersion
from app.models.index_task import IndexTask
from app.models.page_index import DocumentPage, DocumentPageBlock
from app.services.document_asset_service import DocumentAssetService
from app.services.libreoffice_conversion_service import LibreOfficeConversionService
from app.models.user import User
from app.repositories.chat_repository import ChatRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.repositories.index_task_repository import IndexTaskRepository
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.retrieval_trace_repository import RetrievalTraceRepository
from app.repositories.review_repository import ReviewRepository
from app.services.index_pipeline_service import IndexPipelineService
from app.services.index_task_service import IndexTaskService
from app.services.knowledge_category_service import KnowledgeCategoryService
from app.services.page_index_service import PageIndexService
from app.services.project_service import ProjectService
from app.services.system_service import SystemService
from app.utils.file_utils import file_type
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

TARGET_TYPE_DOCUMENT = "document"
TARGET_TYPE_DOCUMENT_PAGE = "document_page"

REVIEW_STATUS_DRAFT = "draft"
REVIEW_STATUS_REVIEWING = "reviewing"
REVIEW_STATUS_APPROVED = "approved"
REVIEW_STATUS_REJECTED = "rejected"
REVIEW_STATUS_ARCHIVED = "archived"

DOCUMENT_STATUS_PENDING_REVIEW = "pending_review"
DOCUMENT_STATUS_REVIEWED = "reviewed"
DOCUMENT_STATUS_ACTIVE = "active"
DOCUMENT_STATUS_INACTIVE = "inactive"
DOCUMENT_STATUS_ARCHIVED = "archived"

PARSE_STATUS_UNPARSED = "unparsed"
PARSE_STATUS_PARSING = "parsing"
PARSE_STATUS_SUCCESS = "success"
PARSE_STATUS_FAILED = "failed"

VERSION_STATUS_PENDING_REVIEW = "pending_review"
VERSION_STATUS_DRAFT = "draft"
VERSION_STATUS_APPROVED = "approved"
VERSION_STATUS_CURRENT = "current"
VERSION_STATUS_HISTORICAL = "historical"
VERSION_STATUS_INACTIVE = "inactive"
VERSION_STATUS_REJECTED = "rejected"

INDEX_STATUS_NOT_INDEXED = "not_indexed"
INDEX_STATUS_PARSING = "parsing"
INDEX_STATUS_PARSED = "parsed"
INDEX_STATUS_PARSED_PENDING_REVIEW = "parsed_pending_review"
INDEX_STATUS_INDEXING = "indexing"
INDEX_STATUS_INDEXED = "indexed"
INDEX_STATUS_FAILED = "failed"
INDEX_STATUS_INVALID = "invalid"

CHUNK_STATUS_ACTIVE = "active"
RESULT_FAILED = "failed"

ASSET_TYPE_CONVERTED_PDF = "converted_pdf"
ASSET_TYPE_MINERU_RESULT = "mineru_result"
ASSET_TYPE_PAGE_PREVIEW = "page_preview"
ASSET_TYPE_BLOCK_IMAGE = "block_image"
ASSET_STATUS_READY = "ready"
ASSET_STATUS_OBSOLETE = "obsolete"
PDF_FILE_TYPE = "pdf"
MARKDOWN_FIELD_CANDIDATES = ("md_content", "markdown", "md", "text", "content", "cleaned_markdown", "botree_cleaned_markdown")
PREVIEW_MARKDOWN_SOURCE_MINERU = "mineru_result"
PREVIEW_MARKDOWN_SOURCE_PAGE_TEXT = "page_text_fallback"
INDEX_BUILD_TASK_TYPE = "full_build"
INDEX_BUILD_ACTIVE_STATUSES = {"pending", "running"}

ACTION_UPLOAD_DOCUMENT = "上传文件"
ACTION_UPLOAD_NEW_VERSION = "上传新版本"
ACTION_DELETE_DOCUMENT = "删除文件"
ACTION_PARSE_DOCUMENT = "文档解析"
ACTION_INDEX_DOCUMENT = "构建索引"
ACTION_BUILD_DOCUMENT_INDEX = "解析并构建索引"
ACTION_BUILD_DOCUMENT_INDEX_FAILED = "解析并构建索引失败"
ACTION_ROLLBACK_DOCUMENT = "版本回滚"
ACTION_ARCHIVE_DOCUMENT = "归档文档"


@dataclass(slots=True)
class DocumentPdfPreviewSource:
    """文档 PDF 预览源，统一描述原始 PDF 和转换 PDF 的读取位置。"""

    file_name: str
    media_type: str = "application/pdf"
    storage_path: str | None = None
    object_key: str | None = None
    source_kind: str = "original_pdf"


class DocumentService:
    """
    文档服务

    职责：
    - 管理文档生命周期
    - 生成页级解析结果与 Chunk
    - 协调索引构建、版本切换与失败治理
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.repository = DocumentRepository(db)
        self.kb_repository = KnowledgeBaseRepository(db)
        self.chat_repository = ChatRepository(db)
        self.category_service = KnowledgeCategoryService(db)
        self.graph_repository = GraphRepository(db)
        self.index_task_repository = IndexTaskRepository(db)
        self.review_repository = ReviewRepository(db)
        self.retrieval_trace_repository = RetrievalTraceRepository(db)

    def list_documents(
        self,
        user: User,
        knowledge_base_id: int | None = None,
        project_id: int | None = None,
        review_status: str | None = None,
        category_id: int | None = None,
        index_status: str | None = None,
        knowledge_type: str | None = None,
        keyword: str | None = None,
    ) -> list[Document]:
        """
        查询文档列表。

        参数:
            user: 当前用户
            knowledge_base_id: 可选知识库范围
            project_id: 可选项目范围
            review_status: 可选审核状态
            category_id: 可选分类
            index_status: 可选索引状态
            knowledge_type: 可选知识范围 base/project
            keyword: 文件名关键字

        返回:
            过滤后的文档列表
        """

        if knowledge_base_id is not None:
            knowledge_base = self.kb_repository.get(knowledge_base_id)
            if not knowledge_base:
                raise AppException("知识库不存在", status_code=404, code=404)
            if knowledge_base.type == "project" and knowledge_base.project_id is not None:
                ProjectService(self.db).ensure_project_access(knowledge_base.project_id, user)

        if project_id is not None:
            ProjectService(self.db).ensure_project_access(project_id, user)

        category_ids = self.category_service.descendant_ids(category_id) if category_id is not None else None
        documents = self.repository.list(
            knowledge_base_id=knowledge_base_id,
            project_id=project_id,
            review_status=review_status,
            category_ids=category_ids,
            index_status=index_status,
            knowledge_type=knowledge_type,
            keyword=keyword,
        )

        result: list[Document] = []
        for document in documents:
            if document.project_id is not None:
                ProjectService(self.db).ensure_project_access(document.project_id, user)
            self._enrich_category_fields(document)
            result.append(document)
        return result

    def get_document(self, document_id: int, user: User) -> Document:
        """
        查询单个文档详情。

        参数:
            document_id: 文档 ID
            user: 当前用户

        返回:
            文档对象
        """

        document = self.repository.get(document_id)
        if not document:
            raise AppException("文档不存在", status_code=404, code=404)
        if document.project_id is not None:
            ProjectService(self.db).ensure_project_access(document.project_id, user)
        self._enrich_category_fields(document)
        return document

    async def upload_document(
        self,
        knowledge_base_id: int,
        upload_file: UploadFile,
        operator: User,
        category_id: int,
    ) -> Document:
        """
        上传文档并创建首个版本。

        参数:
            knowledge_base_id: 目标知识库 ID
            upload_file: 上传文件
            operator: 当前操作人
            category_id: 文档分类 ID

        返回:
            新建的文档对象
        """

        knowledge_base = self.kb_repository.get(knowledge_base_id)
        if not knowledge_base:
            raise AppException("知识库不存在", status_code=404, code=404)
        if knowledge_base.type == "project" and knowledge_base.project_id is not None:
            ProjectService(self.db).ensure_project_access(knowledge_base.project_id, operator)

        category = self.category_service.validate_for_document(
            category_id,
            knowledge_base.type,
            knowledge_base.project_id,
            operator,
        )
        file_info = await UploadService().save(upload_file)

        document = Document(
            knowledge_base_id=knowledge_base.id,
            knowledge_type=knowledge_base.type,
            project_id=knowledge_base.project_id,
            category_id=category.id,
            file_name=file_info["file_name"],
            file_type=file_info["file_type"],
            file_size=file_info["file_size"],
            storage_path=file_info["storage_path"],
            document_status=DOCUMENT_STATUS_PENDING_REVIEW,
            parse_status=PARSE_STATUS_UNPARSED,
            review_status=REVIEW_STATUS_DRAFT,
            index_status=INDEX_STATUS_NOT_INDEXED,
            version_no=1,
            current_version=False,
            created_by=operator.id,
        )
        self.repository.add(document)
        version = self.repository.add_version(
            DocumentVersion(
                document_id=document.id,
                version_no=1,
                category_id=document.category_id,
                file_name=document.file_name,
                file_type=document.file_type,
                file_size=document.file_size,
                storage_path=document.storage_path,
                change_summary="初始上传",
                version_status=VERSION_STATUS_DRAFT,
                parse_status=PARSE_STATUS_UNPARSED,
                review_status=REVIEW_STATUS_DRAFT,
                index_status=document.index_status,
                is_current=False,
                created_by=operator.id,
            )
        )
        SystemService(self.db).record_operation(
            operator,
            ACTION_UPLOAD_DOCUMENT,
            TARGET_TYPE_DOCUMENT,
            document.id,
            f"上传文件 {document.file_name}",
        )
        self.db.commit()
        IndexTaskService(self.db).create_parse_task(document.id, version.version_no, version.id, operator)
        self._enrich_category_fields(document)
        logger.info(
            "文件上传成功: document_id=%s version_id=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s",
            document.id,
            version.id,
            document.project_id,
            document.file_name,
            "upload",
            "success",
            None,
            now_utc().isoformat(),
        )
        return document

    async def create_version(
        self,
        document_id: int,
        upload_file: UploadFile,
        operator: User,
        change_summary: str | None = None,
        category_id: int | None = None,
    ) -> DocumentVersion:
        """
        为文档上传新版本。

        参数:
            document_id: 文档 ID
            upload_file: 新版本文件
            operator: 当前操作人
            change_summary: 变更说明
            category_id: 可选的新分类 ID

        返回:
            新建的版本记录
        """

        document = self.get_document(document_id, operator)
        target_category_id = category_id or document.category_id
        if target_category_id is None:
            raise AppException("上传新版本前必须指定文档分类")

        category = self.category_service.validate_for_document(
            target_category_id,
            document.knowledge_type,
            document.project_id,
            operator,
        )
        file_info = await UploadService().save(upload_file)

        latest_version = self.repository.latest_version(document.id)
        next_version_no = (latest_version.version_no if latest_version else document.version_no) + 1

        version = self.repository.add_version(
            DocumentVersion(
                document_id=document.id,
                version_no=next_version_no,
                category_id=category.id,
                file_name=file_info["file_name"],
                file_type=file_info["file_type"],
                file_size=file_info["file_size"],
                storage_path=file_info["storage_path"],
                change_summary=change_summary,
                version_status=VERSION_STATUS_DRAFT,
                parse_status=PARSE_STATUS_UNPARSED,
                review_status=REVIEW_STATUS_DRAFT,
                index_status=INDEX_STATUS_NOT_INDEXED,
                is_current=False,
                created_by=operator.id,
            )
        )
        SystemService(self.db).record_operation(
            operator,
            ACTION_UPLOAD_NEW_VERSION,
            TARGET_TYPE_DOCUMENT,
            document.id,
            change_summary or "上传新版本",
        )
        self.db.commit()
        IndexTaskService(self.db).create_parse_task(document.id, version.version_no, version.id, operator)
        logger.info(
            "文件版本创建: document_id=%s version_id=%s version_no=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s",
            document.id,
            version.id,
            version.version_no,
            document.project_id,
            version.file_name,
            "create_version",
            "success",
            None,
            now_utc().isoformat(),
        )
        return version

    def delete_document(self, document_id: int, operator: User) -> dict[str, int | bool]:
        """
        删除文档。

        参数:
            document_id: 文档 ID
            operator: 当前操作人
        """

        document = self.get_document(document_id, operator)
        versions = self.repository.list_versions(document.id)
        all_chunks = self.repository.list_chunks(document.id, include_obsolete=True)
        vector_ids = [chunk.vector_id for chunk in all_chunks if chunk.vector_id]
        page_indexes = PageIndexService(self.db).repository.list_document_indexes(document.id)
        text_mirror_paths = sorted({item.text_mirror_path for item in page_indexes if item.text_mirror_path})
        source_storage_paths = sorted({path for path in [document.storage_path, *(version.storage_path for version in versions if version.storage_path)] if path})
        asset_service = DocumentAssetService(self.db)
        assets = asset_service.list_document_assets(document.id)
        asset_storage_paths = sorted({asset.storage_path for asset in assets if asset.storage_path})
        asset_object_keys = sorted({asset.object_key for asset in assets if asset.object_key})
        citation_message_ids = self.chat_repository.list_citation_message_ids_by_document(document.id)

        cleanup_summary = self._delete_document_retrieval_artifacts(
            document=document,
            vector_ids=vector_ids,
            citation_message_ids=citation_message_ids,
            document_asset_count=len(assets),
        )
        self.repository.delete(document)
        SystemService(self.db).record_operation(
            operator,
            ACTION_DELETE_DOCUMENT,
            TARGET_TYPE_DOCUMENT,
            document_id,
            json.dumps(cleanup_summary, ensure_ascii=False),
        )
        self.db.commit()
        self._schedule_document_external_cleanup(
            document_id=document_id,
            vector_ids=vector_ids,
            source_storage_paths=source_storage_paths,
            asset_storage_paths=asset_storage_paths,
            text_mirror_paths=text_mirror_paths,
            asset_object_keys=asset_object_keys,
        )
        logger.info("文档删除完成: document_id=%s cleanup=%s", document_id, cleanup_summary)
        return {
            "deleted": True,
            **cleanup_summary,
            "external_cleanup_queued": bool(vector_ids or source_storage_paths or asset_storage_paths or text_mirror_paths or asset_object_keys),
            "pending_vector_count": len(vector_ids),
            "pending_file_count": len(source_storage_paths) + len(asset_storage_paths) + len(text_mirror_paths),
            "pending_asset_object_count": len(asset_object_keys),
        }

    def download_url(self, document_id: int, user: User) -> dict:
        """
        获取文档下载信息。

        参数:
            document_id: 文档 ID
            user: 当前用户

        返回:
            下载信息
        """

        document = self.get_document(document_id, user)
        return {
            "file_name": document.file_name,
            "storage_path": document.storage_path,
            "url": f"/api/documents/{document.id}/download-url",
        }

    def get_document_pdf_preview(
        self,
        document_id: int,
        user: User,
        version_no: int | None = None,
    ) -> DocumentPdfPreviewSource:
        """获取 PDF 预览源，并将并发删除/处理中导致的锁等待转换为业务提示。"""

        try:
            return self._get_document_pdf_preview(document_id, user, version_no)
        except OperationalError as exc:
            self.db.rollback()
            if is_database_lock_error(exc):
                logger.warning(
                    "文档 PDF 预览锁等待失败: document_id=%s version_no=%s operator_id=%s operation=%s status=%s",
                    document_id,
                    version_no,
                    user.id,
                    "preview_pdf",
                    "lock_wait_timeout",
                )
                raise AppException("当前文档正在被删除或处理，请稍后重试", status_code=409, code=409) from exc
            raise

    def _get_document_pdf_preview(
        self,
        document_id: int,
        user: User,
        version_no: int | None = None,
    ) -> DocumentPdfPreviewSource:
        """
        获取文档详情页使用的 PDF 预览源。

        业务规则：
            - 原文件为 PDF 时直接预览该版本原始文件。
            - Office 类非 PDF 文件预览同版本 LibreOffice 转换后的 PDF，并按需生成缓存资产。
            - 暂不支持转换的非 PDF 文件返回业务提示，避免前端展示错误格式。
        """

        document = self.get_document(document_id, user)
        target_version_no = version_no if version_no is not None else document.version_no
        version = self.repository.get_version(document.id, target_version_no)
        if version_no is not None and version is None:
            raise AppException("目标版本不存在", status_code=404, code=404)

        active_version_no = version.version_no if version else document.version_no
        file_name_for_preview = version.file_name if version else document.file_name
        file_type_for_preview = (version.file_type or file_type(version.file_name)) if version else document.file_type
        storage_path_for_preview = version.storage_path if version else document.storage_path
        asset_context = SimpleNamespace(
            id=document.id,
            version_no=active_version_no,
            file_name=file_name_for_preview,
        )

        if self._is_pdf_file(file_name_for_preview, file_type_for_preview):
            self.db.rollback()
            self._ensure_storage_file_exists(storage_path_for_preview, asset_context.id, active_version_no)
            return DocumentPdfPreviewSource(
                file_name=file_name_for_preview,
                storage_path=storage_path_for_preview,
                source_kind="original_pdf",
            )

        asset_service = DocumentAssetService(self.db)
        converted_asset = self._get_ready_converted_pdf_asset(asset_service, asset_context.id, active_version_no)
        if converted_asset is None or not self._asset_has_available_source(converted_asset):
            self.db.rollback()
            return self._create_converted_pdf_preview_asset(
                document=asset_context,
                version=None,
                storage_path=storage_path_for_preview,
                active_version_no=active_version_no,
                operator_id=user.id,
            )

        if not self._asset_has_available_source(converted_asset):
            raise AppException("转换 PDF 文件不存在，请重新解析或联系管理员", status_code=404, code=404)

        preview_source = DocumentPdfPreviewSource(
            file_name=converted_asset.file_name,
            storage_path=converted_asset.storage_path,
            object_key=converted_asset.object_key,
            source_kind="converted_pdf",
        )
        self.db.rollback()
        return preview_source

    def list_chunks(self, document_id: int, user: User, version_no: int | None = None) -> list[DocumentChunk]:
        """
        查询文档有效 Chunk。

        参数:
            document_id: 文档 ID
            user: 当前用户

        返回:
            Chunk 列表
        """

        self.get_document(document_id, user)
        return self.repository.list_chunks(document_id, version_no=version_no)

    def _resolve_index_build_version(self, document: Document, version_no: int | None = None) -> DocumentVersion:
        """解析前端要构建的目标版本。"""

        if version_no is not None:
            version = self.repository.get_version(document.id, version_no)
            if not version:
                raise AppException("目标版本不存在", status_code=404, code=404)
            return version

        for version in self.repository.list_versions(document.id):
            if version.review_status == REVIEW_STATUS_APPROVED and not version.is_current:
                return version

        current_version = self.repository.get_current_version(document.id) or self.repository.get_version(document.id, document.version_no)
        if current_version:
            return current_version
        raise AppException("文档没有可构建索引的版本")

    def _ensure_version_review_approved(self, version: DocumentVersion, action: str) -> None:
        """校验版本是否已经审核通过，避免未审核资料进入解析或索引链路。"""

        if version.review_status != REVIEW_STATUS_APPROVED:
            raise AppException(f"版本审核通过后才能{action}")

    def _ensure_version_can_build_index(self, version: DocumentVersion) -> None:
        """校验版本是否允许进入索引构建。"""

        self._ensure_version_review_approved(version, "构建索引")
        if version.parse_status != PARSE_STATUS_SUCCESS:
            raise AppException("版本解析成功后才能构建索引")

    def _ensure_no_active_index_build(
        self,
        document: Document,
        version: DocumentVersion,
        active_task_id: int | None = None,
        allow_status_in_progress: bool = False,
    ) -> None:
        """
        校验同一文档没有正在排队或执行中的索引构建。

        同一文档只能有一个 full_build 任务推进，避免重复请求导致新旧版本状态互相覆盖。
        RQ worker 执行自身任务时会传入 active_task_id，用于排除当前任务记录。
        """

        active_task = self.index_task_repository.active_task(
            document.id,
            INDEX_BUILD_TASK_TYPE,
            exclude_task_id=active_task_id,
        )
        if active_task is not None:
            raise AppException("当前文档索引构建中，请勿重复发起")

        if allow_status_in_progress:
            return

        if document.index_status in {INDEX_STATUS_PARSING, INDEX_STATUS_INDEXING} or version.index_status in {
            INDEX_STATUS_PARSING,
            INDEX_STATUS_INDEXING,
        }:
            raise AppException("当前文档索引构建中，请勿重复发起")

    def _mark_index_build_started(self, document: Document, version: DocumentVersion, operator_id: int | None) -> None:
        """
        将目标版本标记为索引构建中。

        异步任务创建成功后立即写入状态，让前端列表可以展示“索引构建中”，并阻止重复触发。
        """

        started_at = now_utc()
        next_status = INDEX_STATUS_INDEXING if version.parse_status == PARSE_STATUS_SUCCESS else INDEX_STATUS_PARSING
        version.index_status = next_status
        version.build_started_at = started_at
        version.build_finished_at = None
        version.build_error = None

        if not self.repository.get_current_version(document.id) or document.version_no == version.version_no:
            document.index_status = next_status
            document.build_started_at = started_at
            document.build_finished_at = None
            document.build_error = None
            document.built_by = operator_id

    def _switch_current_version(self, document: Document, target_version: DocumentVersion, operator_id: int | None) -> None:
        """
        将目标版本切换为当前生效版本。

        只有索引全部构建并发布成功后才能调用，保证任意时刻最多一个 current 版本。
        """

        for version in self.repository.list_versions(document.id):
            was_current = version.is_current
            if version.id == target_version.id:
                version.is_current = True
                version.version_status = VERSION_STATUS_CURRENT
                version.index_status = INDEX_STATUS_INDEXED
            else:
                version.is_current = False
                if was_current or version.version_status == VERSION_STATUS_CURRENT or version.index_status == INDEX_STATUS_INDEXED:
                    version.version_status = VERSION_STATUS_HISTORICAL
                if version.index_status == INDEX_STATUS_INDEXED:
                    version.index_status = INDEX_STATUS_INVALID

        document.version_no = target_version.version_no
        document.file_name = target_version.file_name
        document.file_type = target_version.file_type or file_type(target_version.file_name)
        document.file_size = target_version.file_size
        document.storage_path = target_version.storage_path
        document.category_id = target_version.category_id
        document.document_status = DOCUMENT_STATUS_ACTIVE
        document.parse_status = target_version.parse_status
        document.parse_started_at = target_version.parse_started_at
        document.parse_finished_at = target_version.parse_finished_at
        document.parse_error = target_version.parse_error
        document.parse_log = target_version.parse_log
        document.review_status = REVIEW_STATUS_APPROVED
        document.index_status = INDEX_STATUS_INDEXED
        document.current_version = True
        document.reviewed_by = target_version.reviewed_by
        document.reviewed_at = target_version.reviewed_at
        document.review_comment = target_version.review_comment
        document.built_by = operator_id
        logger.info(
            "当前生效版本切换成功: document_id=%s version_id=%s version_no=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s",
            document.id,
            target_version.id,
            target_version.version_no,
            document.project_id,
            target_version.file_name,
            "switch_current_version",
            "success",
            None,
            now_utc().isoformat(),
        )

    def _build_document_version_index(
        self,
        document_id: int,
        operator: User,
        version_no: int | None = None,
        active_task_id: int | None = None,
    ) -> dict:
        """构建目标版本索引；成功后切换当前版本，失败时保持旧版本生效。"""

        document = self.get_document(document_id, operator)
        version = self._resolve_index_build_version(document, version_no)
        self._ensure_version_review_approved(version, "解析并构建索引")
        self._ensure_no_active_index_build(
            document,
            version,
            active_task_id=active_task_id,
            allow_status_in_progress=active_task_id is not None,
        )
        failed_version_no = version.version_no
        try:
            if version.parse_status != PARSE_STATUS_SUCCESS:
                self.parse_document_version(document.id, version.version_no, operator)
                document = self.get_document(document_id, operator)
                version = self.repository.get_version(document.id, failed_version_no)
                if version is None:
                    raise AppException("目标版本不存在", status_code=404, code=404)

            self._ensure_version_can_build_index(version)
            context = self._build_version_context(document, version, operator.id)
            chunks = self.repository.list_chunks(document.id, version_no=version.version_no)
            if not chunks:
                raise AppException("目标版本尚未生成 Chunk，无法构建索引")

            started_at = now_utc()
            version.index_status = INDEX_STATUS_INDEXING
            version.build_started_at = started_at
            version.build_finished_at = None
            version.build_error = None
            if not self.repository.get_current_version(document.id) or document.version_no == version.version_no:
                document.index_status = INDEX_STATUS_INDEXING
                document.build_started_at = started_at
                document.build_finished_at = None
                document.build_error = None
                document.built_by = operator.id
            self.db.flush()
            logger.info(
                "新版本索引构建开始: document_id=%s version_id=%s version_no=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s",
                document.id,
                version.id,
                version.version_no,
                document.project_id,
                version.file_name,
                "index_build",
                "running",
                None,
                started_at.isoformat(),
            )
            result = IndexPipelineService(self.db).build_all(context, publish=True)  # type: ignore[arg-type]
            old_active_chunks = [
                chunk
                for chunk in self.repository.list_chunks(document.id)
                if chunk.version_no != version.version_no
            ]
            old_vector_ids = [chunk.vector_id for chunk in old_active_chunks if chunk.vector_id]
            logger.info(
                "旧版本索引失效开始: document_id=%s version_id=%s version_no=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s old_chunk_count=%s",
                document.id,
                version.id,
                version.version_no,
                document.project_id,
                version.file_name,
                "invalidate_old_indexes",
                "running",
                None,
                now_utc().isoformat(),
                len(old_active_chunks),
            )
            deactivated_count = self.repository.deactivate_chunks(document.id, exclude_version_no=version.version_no)
            self._switch_current_version(document, version, operator.id)
            finished_at = now_utc()
            version.index_status = INDEX_STATUS_INDEXED
            version.build_finished_at = finished_at
            version.build_error = None
            document.index_status = INDEX_STATUS_INDEXED
            document.build_finished_at = finished_at
            document.build_error = None
            document.built_by = operator.id
            self.db.commit()
            self._delete_obsolete_vectors_best_effort(context, old_vector_ids)  # type: ignore[arg-type]
            logger.info(
                "PageIndex 失效结果: document_id=%s version_id=%s version_no=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s result=%s",
                document.id,
                version.id,
                version.version_no,
                document.project_id,
                version.file_name,
                "pageindex_invalidate",
                "success",
                None,
                finished_at.isoformat(),
                (result.get("publish") or {}).get("published_page_index_count"),
            )
            logger.info(
                "Ripgrep 失效结果: document_id=%s version_id=%s version_no=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s result=%s",
                document.id,
                version.id,
                version.version_no,
                document.project_id,
                version.file_name,
                "ripgrep_invalidate",
                "success",
                None,
                finished_at.isoformat(),
                "pageindex_status_filtered",
            )
            logger.info(
                "Milvus 失效结果: document_id=%s version_id=%s version_no=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s result=%s",
                document.id,
                version.id,
                version.version_no,
                document.project_id,
                version.file_name,
                "milvus_invalidate",
                "success",
                None,
                finished_at.isoformat(),
                len(old_vector_ids),
            )
            logger.info(
                "新版本索引构建成功: document_id=%s version_id=%s version_no=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s chunks=%s invalidated_chunks=%s",
                document.id,
                version.id,
                version.version_no,
                document.project_id,
                version.file_name,
                "index_build",
                "success",
                None,
                finished_at.isoformat(),
                len(chunks),
                deactivated_count,
            )
            return {
                **result,
                "document_id": document.id,
                "version_id": version.id,
                "version_no": version.version_no,
                "chunk_count": len(chunks),
                "invalidated_chunk_count": deactivated_count,
                "index_status": document.index_status,
            }
        except Exception as exc:
            self.db.rollback()
            document = self.get_document(document_id, operator)
            version = self.repository.get_version(document.id, failed_version_no)
            if version is None:
                raise
            finished_at = now_utc()
            error_message = str(exc)[:2000]
            version.index_status = INDEX_STATUS_FAILED
            version.build_finished_at = finished_at
            version.build_error = error_message
            if not self.repository.get_current_version(document.id) or document.version_no == version.version_no:
                document.index_status = INDEX_STATUS_FAILED
                document.build_finished_at = finished_at
                document.build_error = error_message
            self.db.commit()
            logger.exception(
                "新版本索引构建失败: document_id=%s version_id=%s version_no=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s",
                document.id,
                version.id,
                version.version_no,
                document.project_id,
                version.file_name,
                "index_build",
                "failed",
                error_message,
                finished_at.isoformat(),
            )
            raise AppException(f"文档索引构建失败：{error_message}") from exc

    def build_document_index(
        self,
        document_id: int,
        operator: User,
        version_no: int | None = None,
        active_task_id: int | None = None,
    ) -> dict:
        """
        同步执行“解析并构建索引”。

        说明：
            1. 该接口保留兼容，但新的审核中心主入口应使用异步 index task。
            2. 只要配置了 MinerU，解析阶段必须强依赖 MinerU，失败后整条链路直接失败。
            3. 失败信息会回写到 documents.build_error，便于前端展示。

        参数:
            document_id: 文档 ID
            operator: 当前操作人

        返回:
            构建结果摘要
        """

        return self._build_document_version_index(document_id, operator, version_no, active_task_id)

        document = self.get_document(document_id, operator)
        self._ensure_document_is_approved(document)

        document.build_started_at = now_utc()
        document.build_finished_at = None
        document.build_error = None
        document.built_by = operator.id

        try:
            document.index_status = INDEX_STATUS_PARSING
            self.db.flush()

            # 每次重建前都先失效旧版有效索引，确保线上只会命中最新发布结果。
            self._deactivate_document_index_artifacts(document)
            chunks = self._parse_to_chunks(document)
            self.repository.replace_chunks(document.id, chunks)

            document.index_status = INDEX_STATUS_INDEXING
            self.db.flush()
            result = IndexPipelineService(self.db).build_all(document, publish=True)

            document.index_status = INDEX_STATUS_INDEXED
            document.build_finished_at = now_utc()
            document.build_error = None
            SystemService(self.db).record_operation(
                operator,
                ACTION_BUILD_DOCUMENT_INDEX,
                TARGET_TYPE_DOCUMENT,
                document.id,
                f"解析并索引 {len(chunks)} 个 Chunk",
            )
            self.db.commit()
            logger.info("文档解析并构建索引完成: document_id=%s chunks=%s", document.id, len(chunks))
            return {
                **result,
                "document_id": document.id,
                "chunk_count": len(chunks),
                "index_status": document.index_status,
            }
        except Exception as exc:
            self._mark_build_failed(document, exc)
            SystemService(self.db).record_operation(
                operator,
                ACTION_BUILD_DOCUMENT_INDEX_FAILED,
                TARGET_TYPE_DOCUMENT,
                document.id,
                document.build_error,
                result=RESULT_FAILED,
            )
            self.db.commit()
            logger.exception("文档解析并构建索引失败: document_id=%s", document.id)
            raise AppException(f"文档解析并构建索引失败：{document.build_error}") from exc

    def parse_document(self, document_id: int, operator: User) -> dict:
        """兼容旧手动解析接口，默认解析当前主文档版本。"""

        document = self.get_document(document_id, operator)
        return self.parse_document_version(document.id, document.version_no, operator)

    def parse_document_version(self, document_id: int, version_no: int, operator: User) -> dict:
        """
        异步解析指定文件版本。

        解析阶段只写入目标版本的 MinerU 结果、页级内容和 Chunk，不触发索引构建，
        也不改变当前生效版本，保证新版本审核前不影响线上检索。
        """

        document = self.get_document(document_id, operator)
        version = self.repository.get_version(document.id, version_no)
        if not version:
            raise AppException("目标版本不存在", status_code=404, code=404)

        context = self._build_version_context(document, version, operator.id)
        started_at = now_utc()
        version.parse_status = PARSE_STATUS_PARSING
        version.parse_started_at = started_at
        version.parse_finished_at = None
        version.parse_error = None
        version.parse_log = None
        if not self.repository.get_current_version(document.id) or document.version_no == version.version_no:
            document.parse_status = PARSE_STATUS_PARSING
            document.parse_started_at = started_at
            document.parse_finished_at = None
            document.parse_error = None
            document.parse_log = None
        # 解析可能调用外部服务，开始状态必须先提交，避免长事务持续锁住 documents 行。
        self.db.commit()
        logger.info(
            "MinerU 解析开始: document_id=%s version_id=%s version_no=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s",
            document.id,
            version.id,
            version.version_no,
            document.project_id,
            version.file_name,
            "mineru_parse",
            "running",
            None,
            started_at.isoformat(),
        )

        try:
            chunks = self._parse_to_chunks(context)  # type: ignore[arg-type]
            self.repository.replace_chunks(document.id, chunks, version_no=version.version_no)
            finished_at = now_utc()
            parse_log = json.dumps(
                {"chunk_count": len(chunks), "version_no": version.version_no, "finished_at": finished_at.isoformat()},
                ensure_ascii=False,
            )
            version.parse_status = PARSE_STATUS_SUCCESS
            version.parse_finished_at = finished_at
            version.parse_error = None
            version.parse_log = parse_log
            if not self.repository.get_current_version(document.id) or document.version_no == version.version_no:
                document.parse_status = PARSE_STATUS_SUCCESS
                document.parse_finished_at = finished_at
                document.parse_error = None
                document.parse_log = parse_log
            self.db.commit()
            logger.info(
                "MinerU 解析成功: document_id=%s version_id=%s version_no=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s chunks=%s",
                document.id,
                version.id,
                version.version_no,
                document.project_id,
                version.file_name,
                "mineru_parse",
                "success",
                None,
                finished_at.isoformat(),
                len(chunks),
            )
            return {"document_id": document.id, "version_id": version.id, "version_no": version.version_no, "chunk_count": len(chunks)}
        except Exception as exc:
            self.db.rollback()
            document = self.get_document(document_id, operator)
            version = self.repository.get_version(document.id, version_no)
            if version is None:
                raise
            finished_at = now_utc()
            error_message = str(exc)[:2000]
            version.parse_status = PARSE_STATUS_FAILED
            version.parse_finished_at = finished_at
            version.parse_error = error_message
            version.parse_log = json.dumps({"error_message": error_message, "finished_at": finished_at.isoformat()}, ensure_ascii=False)
            if not self.repository.get_current_version(document.id) or document.version_no == version.version_no:
                document.parse_status = PARSE_STATUS_FAILED
                document.parse_finished_at = finished_at
                document.parse_error = error_message
                document.parse_log = version.parse_log
            self.db.commit()
            logger.exception(
                "MinerU 解析失败: document_id=%s version_id=%s version_no=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s",
                document.id,
                version.id,
                version.version_no,
                document.project_id,
                version.file_name,
                "mineru_parse",
                "failed",
                error_message,
                finished_at.isoformat(),
            )
            raise AppException(f"文档解析失败：{error_message}") from exc

    def index_document(self, document_id: int, operator: User) -> dict:
        """
        仅执行文档索引构建。

        参数:
            document_id: 文档 ID
            operator: 当前操作人

        返回:
            索引结果摘要
        """

        document = self.get_document(document_id, operator)
        self._ensure_document_is_approved(document)
        if document.index_status == INDEX_STATUS_PARSED_PENDING_REVIEW:
            raise AppException("解析结果尚未质量确认，不能构建索引")

        chunks = self.repository.list_chunks(document.id, version_no=document.version_no)
        if not chunks:
            raise AppException("文档尚未解析，无法构建索引")

        document.build_started_at = now_utc()
        document.build_finished_at = None
        document.build_error = None

        try:
            document.index_status = INDEX_STATUS_INDEXING
            self.db.flush()

            result = IndexPipelineService(self.db).build_all(document, publish=True)

            document.index_status = INDEX_STATUS_INDEXED
            document.build_finished_at = now_utc()
            SystemService(self.db).record_operation(
                operator,
                ACTION_INDEX_DOCUMENT,
                TARGET_TYPE_DOCUMENT,
                document.id,
                f"索引 {len(chunks)} 个 Chunk",
            )
            self.db.commit()
            logger.info("文档索引完成: document_id=%s", document.id)
            return {**result, "index_status": document.index_status}
        except Exception as exc:
            self._mark_build_failed(document, exc)
            SystemService(self.db).record_operation(
                operator,
                f"{ACTION_INDEX_DOCUMENT}失败",
                TARGET_TYPE_DOCUMENT,
                document.id,
                document.build_error,
                result=RESULT_FAILED,
            )
            self.db.commit()
            logger.exception("文档索引失败: document_id=%s", document.id)
            raise AppException(f"文档索引失败：{document.build_error}") from exc

    def list_versions(self, document_id: int, user: User) -> list[DocumentVersion]:
        """
        查询文档版本列表。

        参数:
            document_id: 文档 ID
            user: 当前用户

        返回:
            版本记录列表
        """

        self.get_document(document_id, user)
        return self.repository.list_versions(document_id)

    def get_version_file(self, document_id: int, version_no: int, user: User) -> DocumentVersion:
        """
        获取指定版本的原始文件记录。

        参数:
            document_id: 文档 ID
            version_no: 版本号
            user: 当前用户

        返回:
            版本记录
        """

        self.get_document(document_id, user)
        version = self.repository.get_version(document_id, version_no)
        if not version:
            raise AppException("目标版本不存在", status_code=404, code=404)

        version_path = self.settings.resolve_local_path(version.storage_path)
        if not version_path.is_file():
            logger.warning(
                "文档版本文件缺失: document_id=%s version_no=%s path=%s",
                document_id,
                version_no,
                version.storage_path,
            )
            raise AppException("版本文件不存在", status_code=404, code=404)
        return version

    def rollback_document(self, document_id: int, operator: User, version_no: int | None = None) -> Document:
        """
        回滚文档到目标版本。

        参数:
            document_id: 文档 ID
            operator: 当前操作人
            version_no: 目标版本号；为空时回滚到上一版

        返回:
            回滚后的文档对象
        """

        document = self.get_document(document_id, operator)
        versions = self.repository.list_versions(document.id)
        if not versions:
            raise AppException("文档没有可回滚版本")

        target: DocumentVersion | None = None
        for version in versions:
            if version_no is not None and version.version_no == version_no:
                target = version
                break
        if target is None and version_no is None:
            target = next((version for version in versions if version.version_no < document.version_no), None)
        if not target:
            raise AppException("目标版本不存在")

        # 回滚后必须让当前有效索引失效，确保重新审核和重建后再参与检索。
        self._deactivate_document_index_artifacts(document)
        for version in versions:
            version.is_current = version.id == target.id

        document.version_no = target.version_no
        document.file_name = target.file_name
        document.file_type = file_type(target.file_name)
        document.storage_path = target.storage_path
        document.file_size = self._resolve_file_size(target.storage_path)
        document.category_id = target.category_id
        document.review_status = target.review_status
        document.index_status = INDEX_STATUS_NOT_INDEXED
        document.build_started_at = None
        document.build_finished_at = None
        document.build_error = None
        document.built_by = None
        target.index_status = INDEX_STATUS_NOT_INDEXED

        SystemService(self.db).record_operation(
            operator,
            ACTION_ROLLBACK_DOCUMENT,
            TARGET_TYPE_DOCUMENT,
            document.id,
            f"回滚到版本 {target.version_no}",
        )
        self.db.commit()
        self._enrich_category_fields(document)
        logger.info("文档版本回滚完成: document_id=%s target_version=%s", document.id, target.version_no)
        return document

    def _build_version_context(
        self,
        document: Document,
        version: DocumentVersion,
        operator_id: int | None = None,
    ) -> SimpleNamespace:
        """
        构造版本级解析/索引上下文。

        新版本在生效前不能写回 Document 主表，因此解析和索引链路统一使用这个只读上下文。
        """

        return SimpleNamespace(
            id=document.id,
            knowledge_base_id=document.knowledge_base_id,
            knowledge_type=document.knowledge_type,
            project_id=document.project_id,
            category_id=version.category_id,
            file_name=version.file_name,
            file_type=version.file_type or file_type(version.file_name),
            file_size=version.file_size,
            storage_path=version.storage_path,
            version_no=version.version_no,
            drawing_no=document.drawing_no,
            drawing_name=document.drawing_name,
            created_by=version.created_by or document.created_by,
            built_by=operator_id or document.built_by,
        )

    def _is_pdf_file(self, file_name: str, raw_file_type: str | None) -> bool:
        """同时依据文件类型字段和文件扩展名判断是否为 PDF。"""

        normalized_type = str(raw_file_type or "").lower().lstrip(".")
        return normalized_type == PDF_FILE_TYPE or Path(file_name).suffix.lower() == ".pdf"

    def _ensure_storage_file_exists(self, storage_path: str, document_id: int, version_no: int) -> None:
        """校验原始文件仍可读取，避免 FileResponse 暴露内部路径异常。"""

        resolved_path = self.settings.resolve_local_path(storage_path)
        if not resolved_path.is_file():
            logger.warning(
                "文档预览源文件缺失: document_id=%s version_no=%s path=%s",
                document_id,
                version_no,
                storage_path,
            )
            raise AppException("文档源文件不存在，无法预览", status_code=404, code=404)

    def _get_ready_converted_pdf_asset(
        self,
        asset_service: DocumentAssetService,
        document_id: int,
        version_no: int,
    ) -> DocumentAsset | None:
        """查询同版本最新可用的转换 PDF 资产。"""

        converted_assets = [
            asset
            for asset in asset_service.list_version_assets(document_id, version_no)
            if asset.asset_type == ASSET_TYPE_CONVERTED_PDF and asset.status == ASSET_STATUS_READY
        ]
        return converted_assets[-1] if converted_assets else None

    def _asset_has_available_source(self, asset: DocumentAsset) -> bool:
        """判断资产是否仍有本地文件或对象存储副本可用于预览。"""

        if asset.storage_path and self.settings.resolve_local_path(asset.storage_path).is_file():
            return True
        return bool(asset.object_key)

    def _create_converted_pdf_preview_asset(
        self,
        document: Document | SimpleNamespace,
        version: DocumentVersion | None,
        storage_path: str,
        active_version_no: int,
        operator_id: int | None,
    ) -> DocumentPdfPreviewSource:
        """
        按需生成非 PDF 文件的预览 PDF 资产。

        说明：
            只沿用现有 LibreOffice 转换能力，不在预览接口中扩展新的转换格式。
        """

        conversion_service = LibreOfficeConversionService()
        if not conversion_service.should_convert(storage_path):
            raise AppException("当前文件类型暂不支持 PDF 预览，请下载原文件查看", status_code=400, code=400)

        self._ensure_storage_file_exists(storage_path, document.id, active_version_no)
        conversion = conversion_service.convert(storage_path, document.id, active_version_no)
        version_context = self._build_version_context(document, version, operator_id) if version else document
        asset = DocumentAssetService(self.db).get_or_create_converted_pdf(
            document=version_context,
            pdf_path=conversion.pdf_path,
            created_by=operator_id,
        )
        preview_source = DocumentPdfPreviewSource(
            file_name=asset.file_name,
            storage_path=asset.storage_path,
            object_key=asset.object_key,
            source_kind="converted_pdf",
        )
        asset_id = asset.id
        self.db.commit()
        logger.info(
            "文档预览 PDF 已生成: document_id=%s version_no=%s source_file=%s pdf_asset_id=%s reused=%s",
            document.id,
            active_version_no,
            Path(storage_path).name,
            asset_id,
            conversion.reused,
        )
        return preview_source

    def _parse_to_chunks(self, document: Document) -> list[DocumentChunk]:
        """
        解析源文件并转换为 Chunk ORM 对象。

        参数:
            document: 文档对象

        返回:
            待写入数据库的 Chunk 列表
        """

        resolved_storage_path = self.settings.resolve_local_path(document.storage_path)
        if not resolved_storage_path.exists():
            raise AppException("源文件不存在，无法解析")

        asset_service = DocumentAssetService(self.db)
        asset_service.prepare_version_parse_refresh(document.id, document.version_no)

        parser_service = ParserService()
        parsed_result = parser_service.parse_document(
            str(resolved_storage_path),
            document_id=document.id,
            version_no=document.version_no,
        )
        parsed_result = ParsedContentCleaner().clean_result(parsed_result)
        cleaning_summary = parsed_result.metadata.get("content_cleaning", {})
        logger.info(
            "MinerU解析数据清洗完成: document_id=%s version_no=%s parser=%s removed_lines=%s removed_blocks=%s toc_pages=%s repeated_noise_lines=%s cleaned_markdown=%s",
            document.id,
            document.version_no,
            parsed_result.parser_name,
            cleaning_summary.get("removed_line_count"),
            cleaning_summary.get("removed_block_count"),
            cleaning_summary.get("removed_toc_page_numbers"),
            cleaning_summary.get("repeated_noise_line_count"),
            cleaning_summary.get("cleaned_markdown"),
        )
        if parsed_result.parse_source.converted_pdf_path:
            asset_service.get_or_create_converted_pdf(
                document=document,
                pdf_path=parsed_result.parse_source.converted_pdf_path,
                created_by=document.built_by or document.created_by,
            )
        mineru_artifact_summary = asset_service.materialize_mineru_output(document, parsed_result)

        page_replace_result = PageIndexService(self.db).replace_pages_from_parse(document, parsed_result.pages)
        mineru_result_asset: DocumentAsset | None = None
        if parsed_result.raw_payload is not None:
            mineru_result_asset = asset_service.save_mineru_result(
                document=document,
                payload=parsed_result.raw_payload,
                task_id=parsed_result.task_id,
                created_by=document.built_by or document.created_by,
            )
        image_summary = asset_service.persist_page_and_block_images(
            document=document,
            parsed_pages=parsed_result.pages,
            saved_pages=page_replace_result.pages,
            saved_blocks=page_replace_result.blocks,
            mineru_result_asset=mineru_result_asset,
            created_by=document.built_by or document.created_by,
        )
        logger.info(
            "文档解析结果已落库: document_id=%s parser=%s pages=%s page_blocks=%s image_ready=%s image_failed=%s copied_artifact_count=%s image_resolution_failures=%s",
            document.id,
            parsed_result.parser_name,
            len(page_replace_result.pages),
            len(page_replace_result.blocks),
            image_summary["ready"],
            image_summary["failed"],
            mineru_artifact_summary["copied_artifact_count"],
            mineru_artifact_summary["image_resolution_failures"],
        )
        chunk_payloads = ChunkBuilder().build(parsed_result.pages)

        return [
            DocumentChunk(
                knowledge_base_id=document.knowledge_base_id,
                document_id=document.id,
                project_id=document.project_id,
                knowledge_type=document.knowledge_type,
                version_no=document.version_no,
                chunk_status=CHUNK_STATUS_ACTIVE,
                chunk_index=item["chunk_index"],
                content=item["content"],
                page_number=item["page_number"],
                section_title=item["section_title"],
                metadata_json=json.dumps(
                    {
                        "file_name": document.file_name,
                        "version_no": document.version_no,
                        "project_id": document.project_id,
                        "knowledge_base_id": document.knowledge_base_id,
                        "category_id": document.category_id,
                    },
                    ensure_ascii=False,
                ),
            )
            for item in chunk_payloads
        ]

    def _deactivate_document_index_artifacts(self, document: Document, delete_external_vectors: bool = True) -> int:
        """
        失效文档当前有效 Chunk 与外部向量索引。

        参数:
            document: 文档对象
            delete_external_vectors: 是否同步删除外部向量索引

        返回:
            被置为 obsolete 的 Chunk 数量
        """

        old_chunks = self.repository.list_chunks(document.id)
        vector_ids = [chunk.vector_id for chunk in old_chunks if chunk.vector_id]
        deactivated_count = self.repository.deactivate_chunks(document.id)
        if delete_external_vectors:
            self._delete_obsolete_vectors_best_effort(document, vector_ids)
        elif vector_ids:
            logger.info(
                "已跳过同步旧版本向量删除: document_id=%s version_no=%s vector_count=%s",
                document.id,
                document.version_no,
                len(vector_ids),
            )
        if deactivated_count:
            logger.info(
                "文档旧版本索引已失效: document_id=%s chunks=%s vectors=%s",
                document.id,
                deactivated_count,
                len(vector_ids),
            )
        return deactivated_count

    def _delete_obsolete_vectors_best_effort(self, document: Document, vector_ids: list[str]) -> None:
        """
        尽力删除旧版本外部向量索引。

        新版本上传的核心状态以数据库版本号和 Chunk 状态为准；外部向量库短时不可用时，
        已失效 Chunk 会在检索回查中被过滤，因此清理失败不应阻断用户上传新版本。
        """

        if not vector_ids:
            return

        if not self.settings.milvus_enabled:
            logger.warning(
                "Milvus 未启用，跳过旧版本向量删除: document_id=%s version_no=%s vector_count=%s",
                document.id,
                document.version_no,
                len(vector_ids),
            )
            return

        try:
            IndexService(self.db).delete_document_index(document.id, vector_ids)
        except Exception:  # noqa: BLE001
            logger.warning(
                "旧版本向量删除失败，已将数据库 Chunk 置为失效: document_id=%s version_no=%s vector_count=%s",
                document.id,
                document.version_no,
                len(vector_ids),
                exc_info=True,
            )

    def _enrich_category_fields(self, document: Document) -> None:
        """
        为文档补充分类展示字段。

        参数:
            document: 文档对象
        """

        setattr(document, "category_name", self.category_service.category_name(document.category_id))
        setattr(document, "category_path", self.category_service.category_path(document.category_id))

    def list_pages(self, document_id: int, user: User, version_no: int | None = None) -> list[DocumentPage]:
        """
        查询文档页级解析结果。

        参数:
            document_id: 文档 ID
            user: 当前用户

        返回:
            页级解析结果列表
        """

        return PageIndexService(self.db).list_pages(document_id, user, version_no)

    def preview_document(self, document_id: int, user: User, version_no: int | None = None) -> dict[str, object]:
        """
        组装当前版本文档的原始内容预览。

        参数:
            document_id: 文档 ID
            user: 当前用户

        返回:
            供前端原始内容预览使用的结构化数据
        """

        document = self.get_document(document_id, user)
        version = self.repository.get_version(document.id, version_no) if version_no is not None else None
        if version_no is not None and version is None:
            raise AppException("目标版本不存在", status_code=404, code=404)
        active_version_no = version.version_no if version else document.version_no
        file_name_for_preview = version.file_name if version else document.file_name
        file_type_for_preview = (version.file_type or file_type(version.file_name)) if version else document.file_type
        index_status_for_preview = version.index_status if version else document.index_status
        page_service = PageIndexService(self.db)
        pages = page_service.list_pages(document.id, user, active_version_no)
        blocks = page_service.list_blocks(document.id, user, active_version_no)
        asset_service = DocumentAssetService(self.db)
        assets = asset_service.list_version_assets(document.id, active_version_no)

        blocks_by_page_id: dict[int, list[DocumentPageBlock]] = {}
        for block in blocks:
            blocks_by_page_id.setdefault(block.page_id, []).append(block)

        page_preview_by_page_id: dict[int, DocumentAsset] = {}
        block_image_by_block_id: dict[int, DocumentAsset] = {}
        converted_pdf_asset: DocumentAsset | None = None
        mineru_result_asset: DocumentAsset | None = None
        markdown_image_assets: list[dict[str, object]] = []
        for asset in assets:
            if asset.status == ASSET_STATUS_OBSOLETE:
                continue
            if asset.asset_type == ASSET_TYPE_CONVERTED_PDF and asset.status == ASSET_STATUS_READY:
                converted_pdf_asset = asset
            if asset.asset_type == ASSET_TYPE_MINERU_RESULT and asset.status == ASSET_STATUS_READY:
                mineru_result_asset = asset
            if asset.asset_type == ASSET_TYPE_PAGE_PREVIEW and asset.page_id is not None:
                page_preview_by_page_id[asset.page_id] = asset
            if asset.asset_type == ASSET_TYPE_BLOCK_IMAGE and asset.block_id is not None:
                block_image_by_block_id[asset.block_id] = asset
            if asset.asset_type in {ASSET_TYPE_PAGE_PREVIEW, ASSET_TYPE_BLOCK_IMAGE} and asset.status == ASSET_STATUS_READY:
                serialized_asset = self._serialize_asset(asset)
                if serialized_asset is not None:
                    markdown_image_assets.append(serialized_asset)

        preview_pages: list[dict[str, object]] = []
        for page in pages:
            page_blocks = blocks_by_page_id.get(page.id, [])
            preview_pages.append(
                {
                    "id": page.id,
                    "page_no": page.page_no,
                    "page_title": page.page_title,
                    "drawing_no": page.drawing_no,
                    "page_text": page.page_text,
                    "clean_content": page.clean_content,
                    "filtered_content": page.filtered_content,
                    "cleaning_metadata_json": page.cleaning_metadata_json,
                    "corrected_text": page.corrected_text,
                    "correction_status": page.correction_status,
                    "page_summary": page.page_summary,
                    "page_preview_asset": self._serialize_asset(page_preview_by_page_id.get(page.id)),
                    "blocks": [
                        {
                            "id": block.id,
                            "block_index": block.block_index,
                            "block_type": block.block_type,
                            "text": block.text,
                            "clean_text": block.clean_text,
                            "filter_status": block.filter_status,
                            "filter_reason": block.filter_reason,
                            "bbox_json": block.bbox_json,
                            "metadata_json": block.metadata_json,
                            "image_asset": self._serialize_asset(block_image_by_block_id.get(block.id)),
                        }
                        for block in page_blocks
                    ],
                }
            )

        markdown_content, markdown_source = self._build_preview_markdown(mineru_result_asset, preview_pages)
        return {
            "document": {
                "id": document.id,
                "file_name": file_name_for_preview,
                "file_type": file_type_for_preview,
                "version_no": active_version_no,
                "knowledge_type": document.knowledge_type,
                "project_id": document.project_id,
                "index_status": index_status_for_preview,
            },
            "converted_pdf_asset": self._serialize_asset(converted_pdf_asset),
            "markdown_content": markdown_content,
            "markdown_source": markdown_source,
            "markdown_image_assets": markdown_image_assets,
            "page_count": len(preview_pages),
            "pages": preview_pages,
        }

    def get_document_asset(self, asset_id: int, user: User) -> DocumentAsset:
        """
        查询单个文档派生资产，并复用文档权限校验。

        参数:
            asset_id: 资产ID
            user: 当前用户

        返回:
            资产 ORM 对象
        """

        asset = DocumentAssetService(self.db).get_asset(asset_id)
        if asset is None:
            raise AppException("派生资产不存在", status_code=404, code=404)
        self.get_document(asset.document_id, user)
        return asset

    def correct_page(
        self,
        document_id: int,
        page_no: int,
        corrected_text: str,
        user: User,
        drawing_no: str | None = None,
        page_title: str | None = None,
    ) -> DocumentPage:
        """
        人工修正文档页级内容。

        参数:
            document_id: 文档 ID
            page_no: 页码
            corrected_text: 修正后的页文本
            user: 当前用户
            drawing_no: 可选图纸号
            page_title: 可选页标题

        返回:
            更新后的页记录
        """

        return PageIndexService(self.db).correct_page(
            document_id,
            page_no,
            corrected_text,
            user,
            drawing_no,
            page_title,
        )

    def quality_check(self, document_id: int, user: User, passed: bool, comment: str | None = None) -> dict:
        """
        执行页级解析质量确认。

        参数:
            document_id: 文档 ID
            user: 当前用户
            passed: 是否通过
            comment: 备注

        返回:
            质量检查结果
        """

        return PageIndexService(self.db).quality_check(document_id, user, passed, comment)

    def create_index_build_task(self, document_id: int, user: User, version_no: int | None = None) -> IndexTask:
        """
        创建异步“解析并构建索引”任务。

        参数:
            document_id: 文档 ID
            user: 当前用户

        返回:
            已入队的索引任务记录
        """

        document = self.get_document(document_id, user)
        version = self._resolve_index_build_version(document, version_no)
        self._ensure_version_review_approved(version, "解析并构建索引")
        self._ensure_no_active_index_build(document, version)
        task = IndexTaskService(self.db).create_build_task(document.id, version.version_no, user, version.id)
        self._mark_index_build_started(document, version, user.id)
        self.db.commit()
        self.db.refresh(task)
        return task

    def create_index_publish_task(self, document_id: int, user: User) -> IndexTask:
        """
        创建异步索引发布任务。

        参数:
            document_id: 文档 ID
            user: 当前用户

        返回:
            已入队的发布任务记录
        """

        document = self.get_document(document_id, user)
        version = self.repository.get_current_version(document.id) or self.repository.get_version(document.id, document.version_no)
        return IndexTaskService(self.db).create_publish_task(document.id, document.version_no, user, version.id if version else None)

    def list_index_tasks(self, document_id: int, user: User) -> list[IndexTask]:
        """
        查询文档索引任务列表。

        参数:
            document_id: 文档 ID
            user: 当前用户

        返回:
            索引任务列表
        """

        document = self.get_document(document_id, user)
        return IndexTaskService(self.db).list_document_tasks(document.id)

    def archive_document(self, document_id: int, operator: User, comment: str | None = None) -> Document:
        """
        归档文档。

        参数:
            document_id: 文档 ID
            operator: 当前操作人
            comment: 归档说明

        返回:
            更新后的文档对象
        """

        document = self.get_document(document_id, operator)
        document.review_status = REVIEW_STATUS_ARCHIVED
        document.review_comment = comment
        SystemService(self.db).record_operation(
            operator,
            ACTION_ARCHIVE_DOCUMENT,
            TARGET_TYPE_DOCUMENT,
            document.id,
            comment or "归档文档",
        )
        self.db.commit()
        self._enrich_category_fields(document)
        logger.info("文档归档完成: document_id=%s", document.id)
        return document

    def _delete_document_retrieval_artifacts(
        self,
        document: Document,
        vector_ids: list[str],
        citation_message_ids: list[int],
        document_asset_count: int,
    ) -> dict[str, int]:
        """
        删除文档关联的检索、解析、审计与审核数据。

        参数:
            document: 文档对象。
            vector_ids: 文档关联的 Milvus 向量ID列表。
            citation_message_ids: 引用了该文档的助手消息ID列表。
            document_asset_count: 删除前派生资产记录数量。

        返回:
            删除结果摘要。
        """

        page_index_repository = PageIndexService(self.db).repository

        deleted_trace_count = self.retrieval_trace_repository.clear_by_message_ids(citation_message_ids)
        deleted_citation_count = self.chat_repository.clear_citations_by_document(document.id)
        deleted_graph_count = self.graph_repository.clear_all_document_graph(document.id)
        deleted_asset_count = DocumentAssetService(self.db).delete_document_asset_records(document.id)
        deleted_page_count = page_index_repository.clear_all_document_pages(document.id)
        deleted_chunk_count = self.repository.clear_chunks(document.id)
        # 任务和审核记录都可能持有 version_id 外键，必须先于版本记录清理。
        deleted_task_count = self.index_task_repository.clear_by_document(document.id)
        review_cleanup_summary = self.review_repository.clear_document_records(document.id)
        deleted_version_count = self.repository.clear_versions(document.id)

        return {
            "vector_count": len(vector_ids),
            "retrieval_traces": deleted_trace_count,
            "chat_citations": deleted_citation_count,
            "graph_entities": deleted_graph_count,
            "document_pages": deleted_page_count,
            "document_chunks": deleted_chunk_count,
            "document_versions": deleted_version_count,
            "index_tasks": deleted_task_count,
            "review_tasks": review_cleanup_summary["review_tasks"],
            "review_logs": review_cleanup_summary["review_logs"],
            "document_assets": deleted_asset_count or document_asset_count,
            "deleted_asset_files": 0,
            "deleted_asset_objects": 0,
        }

    def _schedule_document_external_cleanup(
        self,
        document_id: int,
        vector_ids: list[str],
        source_storage_paths: list[str],
        asset_storage_paths: list[str],
        text_mirror_paths: list[str],
        asset_object_keys: list[str],
    ) -> None:
        """
        异步清理文档外部资源，避免删除接口等待 Milvus、MinIO 或磁盘 I/O。

        数据库记录已在当前事务中删除，检索链路会立即失效；这里的外部清理只做尽力回收。
        """

        if not (vector_ids or source_storage_paths or asset_storage_paths or text_mirror_paths or asset_object_keys):
            return

        thread = Thread(
            target=self._cleanup_document_external_artifacts,
            kwargs={
                "document_id": document_id,
                "vector_ids": list(vector_ids),
                "source_storage_paths": list(source_storage_paths),
                "asset_storage_paths": list(asset_storage_paths),
                "text_mirror_paths": list(text_mirror_paths),
                "asset_object_keys": list(asset_object_keys),
            },
            name=f"document-delete-cleanup-{document_id}",
            daemon=True,
        )
        thread.start()
        logger.info(
            "文档外部资源后台清理已启动: document_id=%s vectors=%s source_files=%s asset_files=%s mirrors=%s asset_objects=%s",
            document_id,
            len(vector_ids),
            len(source_storage_paths),
            len(asset_storage_paths),
            len(text_mirror_paths),
            len(asset_object_keys),
        )

    @staticmethod
    def _cleanup_document_external_artifacts(
        document_id: int,
        vector_ids: list[str],
        source_storage_paths: list[str],
        asset_storage_paths: list[str],
        text_mirror_paths: list[str],
        asset_object_keys: list[str],
    ) -> None:
        """后台尽力清理文档外部资源。"""

        settings = get_settings()
        started_at = now_utc()
        deleted_vectors = 0
        deleted_files = 0
        deleted_objects = 0
        failed_items = 0

        if vector_ids and settings.milvus_enabled:
            try:
                MilvusIndexer().delete_vectors(document_id, vector_ids)
                deleted_vectors = len(vector_ids)
            except Exception:  # noqa: BLE001
                failed_items += 1
                logger.warning("文档删除后 Milvus 向量后台清理失败: document_id=%s vectors=%s", document_id, len(vector_ids), exc_info=True)
        elif vector_ids:
            logger.warning("Milvus 未启用，跳过文档向量后台清理: document_id=%s vectors=%s", document_id, len(vector_ids))

        upload_service = UploadService()
        for storage_path in source_storage_paths:
            try:
                upload_service.remove(storage_path)
                deleted_files += 1
            except Exception:  # noqa: BLE001
                failed_items += 1
                logger.warning("文档原始文件后台删除失败: document_id=%s path=%s", document_id, storage_path, exc_info=True)

        for storage_path in asset_storage_paths:
            try:
                path = settings.resolve_local_path(storage_path)
                if path.is_file():
                    path.unlink()
                    deleted_files += 1
            except Exception:  # noqa: BLE001
                failed_items += 1
                logger.warning("文档派生资产后台删除失败: document_id=%s path=%s", document_id, storage_path, exc_info=True)

        for mirror_path in text_mirror_paths:
            try:
                path = Path(mirror_path)
                if path.is_file():
                    path.unlink()
                    deleted_files += 1
            except Exception:  # noqa: BLE001
                failed_items += 1
                logger.warning("PageIndex 文本镜像后台删除失败: document_id=%s path=%s", document_id, mirror_path, exc_info=True)

        client = get_minio_client()
        if client is None and asset_object_keys:
            logger.warning("MinIO 未启用，跳过文档派生对象后台清理: document_id=%s objects=%s", document_id, len(asset_object_keys))
        elif client is not None:
            for object_key in asset_object_keys:
                try:
                    client.remove_object(settings.minio_bucket, object_key)
                    deleted_objects += 1
                except Exception:  # noqa: BLE001
                    failed_items += 1
                    logger.warning("文档派生资产 MinIO 后台删除失败: document_id=%s object_key=%s", document_id, object_key, exc_info=True)

        try:
            base_dir = settings.libreoffice_work_path.resolve()
            document_dir = (base_dir / str(document_id)).resolve()
            if document_dir.exists() and document_dir.is_dir() and base_dir in document_dir.parents:
                shutil.rmtree(document_dir)
                deleted_files += 1
        except Exception:  # noqa: BLE001
            failed_items += 1
            logger.warning("文档派生资产目录后台清理失败: document_id=%s", document_id, exc_info=True)

        elapsed_ms = int((now_utc() - started_at).total_seconds() * 1000)
        logger.info(
            "文档外部资源后台清理完成: document_id=%s deleted_vectors=%s deleted_files=%s deleted_objects=%s failed_items=%s elapsed_ms=%s",
            document_id,
            deleted_vectors,
            deleted_files,
            deleted_objects,
            failed_items,
            elapsed_ms,
        )

    def _cleanup_document_storage_files(self, source_storage_paths: list[str], text_mirror_paths: list[str]) -> None:
        """
        在数据库提交成功后，尽力清理文档原文件与文本镜像文件。

        参数:
            source_storage_paths: 文档原始文件及版本文件路径列表。
            text_mirror_paths: PageIndex 文本镜像路径列表。
        """

        upload_service = UploadService()
        for storage_path in source_storage_paths:
            try:
                upload_service.remove(storage_path)
            except Exception:  # noqa: BLE001
                logger.warning("文档原始文件删除失败: path=%s", storage_path, exc_info=True)

        for mirror_path in text_mirror_paths:
            try:
                path = Path(mirror_path)
                if path.is_file():
                    path.unlink()
            except Exception:  # noqa: BLE001
                logger.warning("PageIndex 文本镜像删除失败: path=%s", mirror_path, exc_info=True)

    def _build_preview_markdown(
        self,
        mineru_result_asset: DocumentAsset | None,
        preview_pages: list[dict[str, object]],
    ) -> tuple[str | None, str | None]:
        """
        构建文档原始内容的整篇 Markdown 预览。

        参数:
            mineru_result_asset: MinerU 原始结果资产
            preview_pages: 已组装的页级预览数据

        返回:
            Markdown 内容与来源标识；没有可展示内容时返回 (None, None)
        """

        markdown_content = self._read_mineru_markdown(mineru_result_asset)
        if markdown_content:
            return markdown_content, PREVIEW_MARKDOWN_SOURCE_MINERU

        # 兼容早期没有保存 md_content 的解析结果，保持前端仍能按整篇文档展示。
        page_texts: list[str] = []
        for page in preview_pages:
            text = page.get("corrected_text") or page.get("page_text")
            if isinstance(text, str) and text.strip():
                page_texts.append(text.strip())
        fallback_content = "\n\n".join(page_texts).strip()
        if fallback_content:
            return fallback_content, PREVIEW_MARKDOWN_SOURCE_PAGE_TEXT
        return None, None

    def _read_mineru_markdown(self, mineru_result_asset: DocumentAsset | None) -> str | None:
        """
        从 MinerU 原始结果资产中读取完整 Markdown。

        参数:
            mineru_result_asset: document_assets 中的 mineru_result 资产

        返回:
            MinerU 输出的完整 Markdown；读取失败或不存在时返回 None
        """

        if mineru_result_asset is None or not mineru_result_asset.storage_path:
            return None

        path = self.settings.resolve_local_path(mineru_result_asset.storage_path)
        if not path.is_file():
            logger.warning(
                "MinerU Markdown 资产文件不存在: asset_id=%s path=%s",
                mineru_result_asset.id,
                path,
            )
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.exception(
                "MinerU Markdown 资产读取失败: asset_id=%s path=%s",
                mineru_result_asset.id,
                path,
            )
            return None

        markdown_content = self._extract_markdown_from_payload(payload)
        if not markdown_content:
            logger.warning(
                "MinerU Markdown 字段为空: asset_id=%s path=%s",
                mineru_result_asset.id,
                path,
            )
        return markdown_content

    def _extract_markdown_from_payload(self, payload: object) -> str | None:
        """
        在 MinerU 结果结构中递归查找 Markdown 字段。

        参数:
            payload: MinerU 原始 JSON 片段

        返回:
            第一个非空 Markdown 字符串
        """

        if isinstance(payload, dict):
            for key in MARKDOWN_FIELD_CANDIDATES:
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

            # MinerU API 常见结构为 results -> 文件名 -> md_content。
            for key in ("results", "result", "data"):
                nested = payload.get(key)
                markdown_content = self._extract_markdown_from_payload(nested)
                if markdown_content:
                    return markdown_content

            for value in payload.values():
                markdown_content = self._extract_markdown_from_payload(value)
                if markdown_content:
                    return markdown_content

        if isinstance(payload, list):
            for item in payload:
                markdown_content = self._extract_markdown_from_payload(item)
                if markdown_content:
                    return markdown_content

        return None

    def _serialize_asset(self, asset: DocumentAsset | None) -> dict[str, object] | None:
        """
        将资产对象序列化为前端可直接使用的结构。

        参数:
            asset: 资产 ORM 对象

        返回:
            字典结构；为空时返回 None
        """

        if asset is None:
            return None
        return {
            "id": asset.id,
            "asset_type": asset.asset_type,
            "file_name": asset.file_name,
            "mime_type": asset.mime_type,
            "storage_backend": asset.storage_backend,
            "file_size": asset.file_size,
            "status": asset.status,
            "metadata_json": asset.metadata_json,
            "created_at": asset.created_at,
            "updated_at": asset.updated_at,
        }

    def _ensure_document_is_approved(self, document: Document) -> None:
        """
        校验文档是否允许进入解析或索引链路。

        参数:
            document: 文档对象
        """

        if document.review_status != REVIEW_STATUS_APPROVED:
            raise AppException("只有审核通过的文档才能执行该操作")
        if document.review_status == REVIEW_STATUS_ARCHIVED:
            raise AppException("已归档文档不允许执行该操作")

    def _mark_build_failed(self, document: Document, exc: Exception) -> None:
        """
        将文档构建状态统一标记为失败。

        参数:
            document: 文档对象
            exc: 原始异常
        """

        document.index_status = INDEX_STATUS_FAILED
        document.build_finished_at = now_utc()
        document.build_error = str(exc)[:2000]

    def _resolve_file_size(self, storage_path: str) -> int:
        """
        获取文件大小；文件缺失时返回 0。

        参数:
            storage_path: 文件路径

        返回:
            文件字节数
        """

        path = self.settings.resolve_local_path(storage_path)
        if not path.exists() or not path.is_file():
            return 0
        return int(path.stat().st_size)
