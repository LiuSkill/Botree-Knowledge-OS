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
import time
from threading import Thread
from types import SimpleNamespace

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.data_scope import enabled_role_data_scopes
from app.core.config import get_settings
from app.core.exceptions import AppException, is_database_lock_error
from app.core.security_levels import (
    DEFAULT_SECURITY_LEVEL,
    allowed_security_levels,
    ensure_security_level_access,
    normalize_security_level,
    user_max_security_level,
)
from app.core.minio import get_minio_client
from app.knowledge.chunking.chunk_builder import ChunkBuilder
from app.knowledge.indexing.milvus_indexer import MilvusIndexer
from app.knowledge.indexing.index_service import IndexService
from app.knowledge.ingestion.upload_service import UploadService
from app.knowledge.parsing.parsed_content_cleaner import ParsedContentCleaner
from app.knowledge.parsing.parsed_document import ParsedDocumentResult
from app.knowledge.parsing.parser_service import ParserService
from app.models.document_asset import DocumentAsset
from app.models.document import Document, DocumentChunk, DocumentVersion
from app.models.project import Project
from app.models.index_task import IndexTask
from app.models.knowledge_category import KnowledgeCategory
from app.models.page_index import DocumentPage, DocumentPageBlock, PageIndex
from app.services.document_asset_service import DocumentAssetService
from app.services.libreoffice_conversion_service import LibreOfficeConversionService
from app.models.user import User
from app.repositories.chat_repository import ChatRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.repositories.index_task_repository import IndexTaskRepository
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.retrieval_trace_repository import RetrievalTraceRepository
from app.repositories.review_repository import ReviewRepository
from app.repositories.user_repository import UserRepository
from app.schemas.document import DocumentMetadataUpdate
from app.services.index_pipeline_service import IndexPipelineService
from app.services.index_task_service import IndexTaskService
from app.services.knowledge_category_service import KnowledgeCategoryService
from app.services.page_index_service import PageIndexService
from app.services.project_access_service import ProjectAccessService
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
PROJECT_DOCUMENT_STATUS_PENDING = "待审核"
PROJECT_DOCUMENT_STATUS_PUBLISHED = "已发布"

PARSE_DB_WRITE_MAX_ATTEMPTS = 3
PARSE_DB_WRITE_RETRY_BASE_DELAY_SECONDS = 0.2

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
DEFAULT_DOCUMENT_TYPE = "其他"
DEFAULT_DISCIPLINE = "其他"

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
ACTION_IMPORT_PROJECT_DOCUMENT = "导入项目资料"
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
        self.access_service = ProjectAccessService(db)

    def _user_allowed_levels(self, user: User) -> list[str]:
        """根据用户启用角色推导可访问密级集合，用户自身不保存密级。"""

        return allowed_security_levels(user_max_security_level(user))

    def _ensure_document_security_access(self, document: Document, user: User) -> None:
        """文档内容访问必须叠加三层密级强制门禁。"""

        ensure_security_level_access(user, document.security_level)

    def _ensure_project_document_access(
        self,
        document: Document,
        user: User,
        *permission_codes: str,
    ) -> None:
        """项目资料叠加 RBAC、数据范围、项目密级和文档密级；基础知识仅校验文档密级。"""

        if document.project_id is not None:
            self.access_service.ensure_document_access(
                document,
                user,
                permission_codes=tuple(permission_codes or ("project:view",)),
            )
            return
        self._ensure_document_security_access(document, user)

    def _default_document_security_level(self, knowledge_base_project_id: int | None) -> str:
        """项目资料默认继承项目密级，基础知识默认 internal。"""

        if knowledge_base_project_id is None:
            return DEFAULT_SECURITY_LEVEL
        project = ProjectService(self.db).project_repository.get(knowledge_base_project_id)
        return normalize_security_level(getattr(project, "security_level", None), default=DEFAULT_SECURITY_LEVEL)

    def _resolve_document_security_level(
        self,
        *,
        operator: User,
        knowledge_base_project_id: int | None,
        requested_level: str | None,
    ) -> str:
        security_level = normalize_security_level(
            requested_level,
            default=self._default_document_security_level(knowledge_base_project_id),
        )
        ensure_security_level_access(operator, security_level, message="无权创建或修改超出自身最高密级的文档")
        return security_level

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
                self.access_service.ensure_project_access(
                    knowledge_base.project_id,
                    user,
                    permission_codes=("project:view",),
                )

        if project_id is not None:
            self.access_service.ensure_project_access(project_id, user, permission_codes=("project:view",))

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
            if project_id is not None:
                try:
                    ensure_security_level_access(user, document.security_level, message="无权访问该文档密级")
                except AppException:
                    continue
                result.append(document)
                continue

            if not self.access_service.can_access_document(document, user, permission_codes=("project:view",)):
                continue
            if document.project_id is not None:
                try:
                    self.access_service.ensure_project_access(
                        document.project_id,
                        user,
                        permission_codes=("project:view",),
                    )
                except AppException:
                    logger.info(
                        "文档列表过滤无权项目资料: document_id=%s project_id=%s user_id=%s",
                        document.id,
                        document.project_id,
                        getattr(user, "id", None),
                    )
                    continue
            result.append(document)
        self._enrich_category_fields_bulk(result)
        self._enrich_uploader_fields(result)
        return result

    def list_approved_documents_page(
        self,
        user: User,
        *,
        page: int,
        page_size: int,
        project_id: int | None = None,
        category_id: int | None = None,
        index_status: str | None = None,
        knowledge_type: str | None = None,
        keyword: str | None = None,
    ) -> dict[str, object]:
        """分页查询审核通过资料，并在数据库层过滤用户可访问的项目资料。"""

        if project_id is not None:
            self.access_service.ensure_project_access(project_id, user, permission_codes=("project:view",))

        category_ids = self.category_service.descendant_ids(category_id) if category_id is not None else None
        include_base_documents = project_id is None and knowledge_type != "project"
        include_project_documents = knowledge_type != "base" and self.access_service.has_permission(user, "project:view", "project")
        accessible_project_ids: list[int] | None = None
        if project_id is not None:
            include_base_documents = False
            include_project_documents = True
            accessible_project_ids = [project_id]
        elif include_project_documents:
            accessible_project_ids = self._accessible_project_ids(user)

        result = self.repository.list_approved_page(
            page=page,
            page_size=page_size,
            security_levels=self._user_allowed_levels(user),
            include_base_documents=include_base_documents,
            include_project_documents=include_project_documents,
            accessible_project_ids=accessible_project_ids,
            project_id=project_id,
            category_ids=category_ids,
            index_status=index_status,
            knowledge_type=knowledge_type,
            keyword=keyword,
        )
        documents = list(result["items"])
        self._enrich_category_fields_bulk(documents)
        self._enrich_uploader_fields(documents)
        return {**result, "items": documents}

    def _accessible_project_ids(self, user: User) -> list[int]:
        """复用项目列表的数据范围规则，生成跨项目资料查询的项目 ID 白名单。"""

        user_department = getattr(user, "department_id", None) or getattr(user, "department", None)
        return ProjectRepository(self.db).list_accessible_ids(
            user_id=user.id,
            user_department=str(user_department) if user_department else None,
            is_admin=self.access_service.is_admin(user),
            data_scopes=enabled_role_data_scopes(user),
            project_security_levels=self._user_allowed_levels(user),
        )

    def list_project_documents_page(
        self,
        user: User,
        *,
        project_id: int,
        page: int,
        page_size: int,
        category_id: int | None = None,
        keyword: str | None = None,
        status: str | None = None,
        security_level: str | None = None,
        parse_status: str | None = None,
        index_status: str | None = None,
        document_type: str | None = None,
        discipline: str | None = None,
        upload_user_id: int | None = None,
    ) -> dict[str, object]:
        """项目资料管理页分页查询，数量统计由数据库聚合返回，前端只负责展示。"""

        self.access_service.ensure_project_access(project_id, user, permission_codes=("project:view",))
        category_ids = self.category_service.descendant_ids(category_id) if category_id is not None else None
        result = self.repository.list_project_page(
            project_id=project_id,
            security_levels=self._user_allowed_levels(user),
            page=page,
            page_size=page_size,
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
        documents = list(result["items"])
        self._enrich_category_fields_bulk(documents)
        self._enrich_uploader_fields(documents)
        return {**result, "items": documents}

    def _enrich_uploader_fields(self, documents: list[Document]) -> None:
        """批量补充上传人展示字段，避免列表接口逐条查询用户。"""

        uploader_ids = {
            uploader_id
            for document in documents
            if (uploader_id := document.upload_user_id or document.created_by) is not None
        }
        user_by_id = {user.id: user for user in UserRepository(self.db).list_by_ids(uploader_ids)}
        for document in documents:
            uploader_id = document.upload_user_id or document.created_by
            uploader = user_by_id.get(uploader_id) if uploader_id is not None else None
            setattr(document, "uploader_name", uploader.real_name if uploader else None)
            setattr(document, "uploader_username", uploader.username if uploader else None)

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
        self._ensure_project_document_access(document, user, "project:view")
        self._enrich_category_fields(document)
        self._enrich_uploader_fields([document])
        return document

    async def upload_document(
        self,
        knowledge_base_id: int,
        upload_file: UploadFile,
        operator: User,
        category_id: int,
        security_level: str | None = None,
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
            self.access_service.ensure_project_access(
                knowledge_base.project_id,
                operator,
                permission_codes=("project:upload",),
            )
        category = self.category_service.validate_for_document(
            category_id,
            knowledge_base.type,
            knowledge_base.project_id,
            operator,
        )
        resolved_security_level = self._resolve_document_security_level(
            operator=operator,
            knowledge_base_project_id=knowledge_base.project_id,
            requested_level=security_level or category.default_security_level,
        )
        file_info = await UploadService().save(upload_file)
        version_label = "v1"
        document_type = self._infer_document_type(category, file_info["file_name"])
        discipline = self._infer_discipline(category)

        document = Document(
            knowledge_base_id=knowledge_base.id,
            knowledge_type=knowledge_base.type,
            project_id=knowledge_base.project_id,
            directory_id=category.id,
            document_name=file_info["file_name"],
            document_type=document_type,
            discipline=discipline,
            version=version_label,
            status=PROJECT_DOCUMENT_STATUS_PENDING,
            upload_user_id=operator.id,
            category_id=category.id,
            file_name=file_info["file_name"],
            file_type=file_info["file_type"],
            file_size=file_info["file_size"],
            storage_path=file_info["storage_path"],
            file_path=file_info["storage_path"],
            document_status=DOCUMENT_STATUS_PENDING_REVIEW,
            parse_status=PARSE_STATUS_UNPARSED,
            review_status=REVIEW_STATUS_DRAFT,
            index_status=INDEX_STATUS_NOT_INDEXED,
            version_no=1,
            current_version=False,
            is_current_version=True,
            security_level=resolved_security_level,
            created_by=operator.id,
        )
        self.repository.add(document)
        version = self.repository.add_version(
            DocumentVersion(
                document_id=document.id,
                project_id=document.project_id,
                version_no=1,
                version=version_label,
                category_id=document.category_id,
                file_name=document.file_name,
                file_type=document.file_type,
                file_size=document.file_size,
                storage_path=document.storage_path,
                file_path=document.file_path,
                change_summary="初始上传",
                version_note="初始上传",
                version_status=VERSION_STATUS_DRAFT,
                status=PROJECT_DOCUMENT_STATUS_PENDING,
                parse_status=PARSE_STATUS_UNPARSED,
                review_status=REVIEW_STATUS_DRAFT,
                index_status=document.index_status,
                is_current=False,
                is_current_version=True,
                security_level=document.security_level,
                created_by=operator.id,
                upload_user_id=operator.id,
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

    def create_imported_project_document(
        self,
        knowledge_base_id: int,
        source_path: str | Path,
        operator: User,
        category_id: int,
        security_level: str | None = None,
        remark: str | None = None,
    ) -> Document:
        """
        从本地目录导入项目资料，仅建档和保存原始文件，不触发解析或索引任务。

        该方法复用上传链路的知识库、目录、密级和元数据规则，但刻意不创建
        MinerU 解析任务，适合大批量历史项目资料先入库后分批治理。
        """

        knowledge_base = self.kb_repository.get(knowledge_base_id)
        if not knowledge_base:
            raise AppException("知识库不存在", status_code=404, code=404)
        if knowledge_base.type != "project" or knowledge_base.project_id is None:
            raise AppException("目录导入仅支持项目知识库")
        self.access_service.ensure_project_access(
            knowledge_base.project_id,
            operator,
            permission_codes=("project:upload",),
        )
        category = self.category_service.validate_for_document(
            category_id,
            knowledge_base.type,
            knowledge_base.project_id,
            operator,
        )
        resolved_security_level = self._resolve_document_security_level(
            operator=operator,
            knowledge_base_project_id=knowledge_base.project_id,
            requested_level=security_level or category.default_security_level,
        )
        file_info = UploadService().save_local_file(source_path)
        version_label = "v1"
        document_type = self._infer_document_type(category, file_info["file_name"])
        discipline = self._infer_discipline(category)

        document = Document(
            knowledge_base_id=knowledge_base.id,
            knowledge_type=knowledge_base.type,
            project_id=knowledge_base.project_id,
            directory_id=category.id,
            document_name=file_info["file_name"],
            document_type=document_type,
            discipline=discipline,
            version=version_label,
            status=PROJECT_DOCUMENT_STATUS_PENDING,
            upload_user_id=operator.id,
            category_id=category.id,
            file_name=file_info["file_name"],
            file_type=file_info["file_type"],
            file_size=file_info["file_size"],
            storage_path=file_info["storage_path"],
            file_path=file_info["storage_path"],
            document_status=DOCUMENT_STATUS_PENDING_REVIEW,
            parse_status=PARSE_STATUS_UNPARSED,
            review_status=REVIEW_STATUS_DRAFT,
            index_status=INDEX_STATUS_NOT_INDEXED,
            version_no=1,
            current_version=False,
            is_current_version=True,
            security_level=resolved_security_level,
            remark=remark,
            created_by=operator.id,
        )
        self.repository.add(document)
        version = self.repository.add_version(
            DocumentVersion(
                document_id=document.id,
                project_id=document.project_id,
                version_no=1,
                version=version_label,
                category_id=document.category_id,
                file_name=document.file_name,
                file_type=document.file_type,
                file_size=document.file_size,
                storage_path=document.storage_path,
                file_path=document.file_path,
                change_summary="目录导入",
                version_note="目录导入",
                version_status=VERSION_STATUS_DRAFT,
                status=PROJECT_DOCUMENT_STATUS_PENDING,
                parse_status=PARSE_STATUS_UNPARSED,
                review_status=REVIEW_STATUS_DRAFT,
                index_status=document.index_status,
                is_current=False,
                is_current_version=True,
                security_level=document.security_level,
                created_by=operator.id,
                upload_user_id=operator.id,
            )
        )
        SystemService(self.db).record_operation(
            operator,
            ACTION_IMPORT_PROJECT_DOCUMENT,
            TARGET_TYPE_DOCUMENT,
            document.id,
            f"导入项目资料 {document.file_name}",
            project_id=document.project_id,
        )
        self.db.commit()
        self._enrich_category_fields(document)
        logger.info(
            "项目资料导入成功: document_id=%s version_id=%s project_id=%s file_name=%s operation=%s status=%s timestamp=%s",
            document.id,
            version.id,
            document.project_id,
            document.file_name,
            "directory_import",
            "success",
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
        self._ensure_project_document_access(document, operator, "project:document:version-create")
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
        version_label = f"v{next_version_no}"
        activate_new_version = document.project_id is not None
        if activate_new_version:
            for existing_version in self.repository.list_versions(document.id):
                existing_version.is_current = False
                existing_version.is_current_version = False
                if existing_version.version_status == VERSION_STATUS_CURRENT:
                    existing_version.version_status = VERSION_STATUS_HISTORICAL

        version = self.repository.add_version(
            DocumentVersion(
                document_id=document.id,
                project_id=document.project_id,
                version_no=next_version_no,
                version=version_label,
                category_id=category.id,
                file_name=file_info["file_name"],
                file_type=file_info["file_type"],
                file_size=file_info["file_size"],
                storage_path=file_info["storage_path"],
                file_path=file_info["storage_path"],
                change_summary=change_summary,
                version_note=change_summary,
                version_status=VERSION_STATUS_DRAFT,
                status=PROJECT_DOCUMENT_STATUS_PENDING,
                parse_status=PARSE_STATUS_UNPARSED,
                review_status=REVIEW_STATUS_DRAFT,
                index_status=INDEX_STATUS_NOT_INDEXED,
                is_current=activate_new_version,
                is_current_version=activate_new_version,
                security_level=document.security_level,
                created_by=operator.id,
                upload_user_id=operator.id,
            )
        )
        if activate_new_version:
            document.version_no = next_version_no
            document.version = version_label
            document.document_name = file_info["file_name"]
            document.file_name = file_info["file_name"]
            document.file_type = file_info["file_type"]
            document.file_size = file_info["file_size"]
            document.storage_path = file_info["storage_path"]
            document.file_path = file_info["storage_path"]
            document.directory_id = category.id
            document.category_id = category.id
            document.status = PROJECT_DOCUMENT_STATUS_PENDING
            document.document_status = DOCUMENT_STATUS_PENDING_REVIEW
            document.review_status = REVIEW_STATUS_DRAFT
            document.parse_status = PARSE_STATUS_UNPARSED
            document.index_status = INDEX_STATUS_NOT_INDEXED
            document.current_version = True
            document.is_current_version = True
            document.parse_started_at = None
            document.parse_finished_at = None
            document.parse_error = None
            document.parse_log = None
            document.build_started_at = None
            document.build_finished_at = None
            document.build_error = None
            document.built_by = None
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

    def update_document_metadata(self, document_id: int, payload: DocumentMetadataUpdate, operator: User) -> Document:
        document = self.get_document(document_id, operator)
        self._ensure_project_document_access(document, operator, "project:document:edit")
        fields_set = payload.model_fields_set
        changed_fields: list[str] = []

        if "directory_id" in fields_set:
            if payload.directory_id is None:
                raise AppException("项目资料目录不能为空")
            category = self.category_service.validate_for_document(
                payload.directory_id,
                document.knowledge_type,
                document.project_id,
                operator,
            )
            if document.category_id != category.id or document.directory_id != category.id:
                document.category_id = category.id
                document.directory_id = category.id
                current_version = self.repository.get_current_version(document.id)
                if current_version:
                    current_version.category_id = category.id
                changed_fields.append("directory_id")

        for field in ("document_name", "document_type", "discipline", "version", "preview_url", "remark"):
            if field in fields_set:
                value = getattr(payload, field)
                if getattr(document, field) != value:
                    setattr(document, field, value)
                    changed_fields.append(field)

        if "security_level" in fields_set and payload.security_level is not None:
            self._ensure_project_document_access(document, operator, "project:document:security-update")
            if self._apply_document_security_level(document, payload.security_level, operator):
                changed_fields.append("security_level")

        if "status" in fields_set and payload.status is not None:
            if self._apply_project_document_status(document, payload.status, operator):
                changed_fields.append("status")

        if changed_fields:
            SystemService(self.db).record_operation(
                operator,
                "编辑文件元数据",
                TARGET_TYPE_DOCUMENT,
                document.id,
                json.dumps({"changed_fields": changed_fields}, ensure_ascii=False),
                project_id=document.project_id,
            )
            self.db.commit()
        self._enrich_category_fields(document)
        return document

    def delete_document(self, document_id: int, operator: User) -> dict[str, int | bool]:
        """
        删除文档。

        参数:
            document_id: 文档 ID
            operator: 当前操作人
        """

        document = self.get_document(document_id, operator)
        self._ensure_project_document_access(document, operator, "project:document:delete")
        if document.project_id is None:
            return self._delete_base_document(document, operator)
        all_chunks = self.repository.list_chunks(document.id, include_obsolete=True)
        vector_ids = [chunk.vector_id for chunk in all_chunks if chunk.vector_id]
        page_indexes = PageIndexService(self.db).repository.list_document_indexes(document.id)
        invalidated_chunk_count = self.repository.deactivate_chunks(document.id)
        obsolete_page_index_count = 0
        for page_index in page_indexes:
            if page_index.status in {"staging", "published"}:
                page_index.status = "obsolete"
                obsolete_page_index_count += 1
        deleted_at = now_utc()
        document.is_deleted = True
        document.deleted_at = deleted_at
        if document.index_status == INDEX_STATUS_INDEXED:
            document.index_status = INDEX_STATUS_INVALID
        for version in self.repository.list_versions(document.id):
            if version.index_status == INDEX_STATUS_INDEXED:
                version.index_status = INDEX_STATUS_INVALID
        SystemService(self.db).record_operation(
            operator,
            ACTION_DELETE_DOCUMENT,
            TARGET_TYPE_DOCUMENT,
            document_id,
            json.dumps(
                {
                    "soft_delete": True,
                    "deleted_at": deleted_at.isoformat(),
                    "vector_count": len(vector_ids),
                    "invalidated_chunks": invalidated_chunk_count,
                    "obsolete_page_indexes": obsolete_page_index_count,
                },
                ensure_ascii=False,
            ),
        )
        self.db.commit()
        logger.info(
            "文档软删除完成: document_id=%s vector_count=%s invalidated_chunks=%s obsolete_page_indexes=%s",
            document_id,
            len(vector_ids),
            invalidated_chunk_count,
            obsolete_page_index_count,
        )
        return {
            "deleted": True,
            "vector_count": len(vector_ids),
            "retrieval_traces": 0,
            "chat_citations": 0,
            "graph_entities": 0,
            "document_pages": 0,
            "document_chunks": invalidated_chunk_count,
            "document_versions": 0,
            "index_tasks": 0,
            "review_tasks": 0,
            "review_logs": 0,
            "document_assets": 0,
            "deleted_asset_files": 0,
            "deleted_asset_objects": 0,
            "external_cleanup_queued": False,
            "pending_vector_count": len(vector_ids),
            "pending_file_count": 0,
            "pending_asset_object_count": 0,
        }

    def _delete_base_document(self, document: Document, operator: User) -> dict[str, int | bool]:
        """Delete a base knowledge document with the legacy physical cleanup flow."""

        all_chunks = self.repository.list_chunks(document.id, include_obsolete=True)
        vector_ids = [chunk.vector_id for chunk in all_chunks if chunk.vector_id]
        citation_message_ids = self.chat_repository.list_citation_message_ids_by_document(document.id)
        versions = self.repository.list_versions(document.id)
        assets = DocumentAssetService(self.db).list_document_assets(document.id)
        page_indexes = PageIndexService(self.db).repository.list_document_indexes(document.id)
        source_storage_paths = [document.storage_path]
        source_storage_paths.extend(version.storage_path for version in versions if version.storage_path)
        source_storage_paths = [path for path in source_storage_paths if path]
        asset_storage_paths = [asset.storage_path for asset in assets if asset.storage_path]
        asset_object_keys = [asset.object_key for asset in assets if asset.object_key]
        text_mirror_paths = [page_index.text_mirror_path for page_index in page_indexes if page_index.text_mirror_path]
        cleanup_summary = self._delete_document_retrieval_artifacts(
            document,
            vector_ids,
            citation_message_ids,
            len(assets),
        )
        document_id = document.id
        self.repository.delete(document)
        SystemService(self.db).record_operation(
            operator,
            ACTION_DELETE_DOCUMENT,
            TARGET_TYPE_DOCUMENT,
            document_id,
            json.dumps({"soft_delete": False, **cleanup_summary}, ensure_ascii=False),
        )
        self.db.commit()
        external_cleanup_queued = bool(
            vector_ids or source_storage_paths or asset_storage_paths or text_mirror_paths or asset_object_keys
        )
        if external_cleanup_queued:
            self._schedule_document_external_cleanup(
                document_id,
                vector_ids,
                source_storage_paths,
                asset_storage_paths,
                text_mirror_paths,
                asset_object_keys,
            )
        return {
            "deleted": True,
            **cleanup_summary,
            "external_cleanup_queued": external_cleanup_queued,
            "pending_vector_count": len(vector_ids),
            "pending_file_count": len(source_storage_paths) + len(text_mirror_paths),
            "pending_asset_object_count": len(asset_object_keys),
        }

    def purge_document(self, document_id: int, operator: User) -> dict[str, int | bool]:
        """物理删除文档及其全部数据库关联和外部存储资源。"""

        document = self.get_document(document_id, operator)
        self._ensure_project_document_access(document, operator, "project:document:delete")
        return self._delete_base_document(document, operator)

    def publish_document(self, document_id: int, operator: User) -> Document:
        """发布项目资料，同时写入旧审核字段以兼容现有解析和索引链路。"""

        document = self.get_document(document_id, operator)
        self._ensure_project_document_access(document, operator, "project:submit-review")
        current_version = self.repository.get_current_version(document.id) or self.repository.get_version(document.id, document.version_no)
        reviewed_at = now_utc()
        document.status = PROJECT_DOCUMENT_STATUS_PUBLISHED
        document.review_status = REVIEW_STATUS_APPROVED
        document.document_status = DOCUMENT_STATUS_REVIEWED
        document.reviewed_by = operator.id
        document.reviewed_at = reviewed_at
        document.current_version = True
        document.is_current_version = True
        if current_version:
            current_version.is_current = True
            current_version.status = PROJECT_DOCUMENT_STATUS_PUBLISHED
            current_version.review_status = REVIEW_STATUS_APPROVED
            current_version.version_status = VERSION_STATUS_APPROVED
            current_version.reviewed_by = operator.id
            current_version.reviewed_at = reviewed_at
            current_version.is_current_version = document.is_current_version
        SystemService(self.db).record_operation(
            operator,
            "发布文件",
            TARGET_TYPE_DOCUMENT,
            document.id,
            json.dumps({"status": document.status, "version_no": document.version_no}, ensure_ascii=False),
        )
        self.db.commit()
        self._enrich_category_fields(document)
        logger.info("文档发布完成: document_id=%s project_id=%s operator_id=%s", document.id, document.project_id, operator.id)
        return document

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
        self._ensure_project_document_access(document, user, "project:document:download")
        SystemService(self.db).record_operation(
            user,
            "下载文件",
            TARGET_TYPE_DOCUMENT,
            document.id,
            json.dumps({"version_no": document.version_no, "file_name": document.file_name}, ensure_ascii=False),
            project_id=document.project_id,
            auto_commit=True,
        )
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
            preview_source = self._get_document_pdf_preview(document_id, user, version_no)
            document = self.repository.get(document_id)
            SystemService(self.db).record_operation(
                user,
                "预览文件",
                TARGET_TYPE_DOCUMENT,
                document_id,
                json.dumps(
                    {
                        "version_no": version_no,
                        "source_kind": preview_source.source_kind,
                        "file_name": preview_source.file_name,
                    },
                    ensure_ascii=False,
                ),
                project_id=document.project_id if document else None,
                auto_commit=True,
            )
            return preview_source
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
        self._ensure_project_document_access(document, user, "project:document:preview")
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

        document = self.get_document(document_id, user)
        self._ensure_project_document_access(document, user, "project:view")
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
                version.is_current_version = True
                version.version_status = VERSION_STATUS_CURRENT
                version.status = PROJECT_DOCUMENT_STATUS_PUBLISHED
                version.index_status = INDEX_STATUS_INDEXED
            else:
                version.is_current = False
                version.is_current_version = False
                if was_current or version.version_status == VERSION_STATUS_CURRENT or version.index_status == INDEX_STATUS_INDEXED:
                    version.version_status = VERSION_STATUS_HISTORICAL
                if version.index_status == INDEX_STATUS_INDEXED:
                    version.index_status = INDEX_STATUS_INVALID

        document.version_no = target_version.version_no
        document.version = target_version.version or f"v{target_version.version_no}"
        document.document_name = target_version.file_name
        document.file_name = target_version.file_name
        document.file_type = target_version.file_type or file_type(target_version.file_name)
        document.file_size = target_version.file_size
        document.storage_path = target_version.storage_path
        document.file_path = target_version.file_path or target_version.storage_path
        document.directory_id = target_version.category_id
        document.category_id = target_version.category_id
        document.security_level = target_version.security_level
        document.document_status = DOCUMENT_STATUS_ACTIVE
        document.status = PROJECT_DOCUMENT_STATUS_PUBLISHED
        document.parse_status = target_version.parse_status
        document.parse_started_at = target_version.parse_started_at
        document.parse_finished_at = target_version.parse_finished_at
        document.parse_error = target_version.parse_error
        document.parse_log = target_version.parse_log
        document.review_status = REVIEW_STATUS_APPROVED
        document.index_status = INDEX_STATUS_INDEXED
        document.current_version = True
        document.is_current_version = True
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
        self._ensure_project_document_access(document, operator, "project:document:retry-index")
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
        self._ensure_project_document_access(document, operator, "project:document:retry-index")
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
        self._ensure_project_document_access(document, operator, "project:document:retry-parse")
        return self.parse_document_version(document.id, document.version_no, operator)

    def parse_document_version(self, document_id: int, version_no: int, operator: User) -> dict:
        """
        异步解析指定文件版本。

        解析阶段只写入目标版本的 MinerU 结果、页级内容和 Chunk，不触发索引构建，
        也不改变当前生效版本，保证新版本审核前不影响线上检索。
        """

        document = self.get_document(document_id, operator)
        self._ensure_project_document_access(document, operator, "project:document:retry-parse")
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
            parsed_result, mineru_artifact_summary = self._parse_document_source(context)  # type: ignore[arg-type]
            for attempt in range(1, PARSE_DB_WRITE_MAX_ATTEMPTS + 1):
                try:
                    chunks = self._persist_parsed_result_as_chunks(context, parsed_result, mineru_artifact_summary)  # type: ignore[arg-type]
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
                    return {
                        "document_id": document.id,
                        "version_id": version.id,
                        "version_no": version.version_no,
                        "chunk_count": len(chunks),
                    }
                except OperationalError as exc:
                    if not is_database_lock_error(exc) or attempt >= PARSE_DB_WRITE_MAX_ATTEMPTS:
                        raise
                    self.db.rollback()
                    logger.warning(
                        "MinerU 解析结果写库遇到数据库锁冲突，准备重试: document_id=%s version_no=%s attempt=%s max_attempts=%s error=%s",
                        document_id,
                        version_no,
                        attempt,
                        PARSE_DB_WRITE_MAX_ATTEMPTS,
                        exc,
                    )
                    time.sleep(PARSE_DB_WRITE_RETRY_BASE_DELAY_SECONDS * attempt)
                    document = self.get_document(document_id, operator)
                    version = self.repository.get_version(document.id, version_no)
                    if version is None:
                        raise AppException("目标版本不存在", status_code=404, code=404)
                    context = self._build_version_context(document, version, operator.id)
        except Exception as exc:
            self.db.rollback()
            document = self.get_document(document_id, operator)
            version = self.repository.get_version(document.id, version_no)
            if version is None:
                raise
            finished_at = now_utc()
            if is_database_lock_error(exc):
                error_message = "数据库正在处理同一文档解析结果，请稍后重试"
            else:
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
            SystemService(self.db).record_operation(
                operator,
                "解析失败重试",
                TARGET_TYPE_DOCUMENT,
                document.id,
                json.dumps(
                    {
                        "version_id": version.id,
                        "version_no": version.version_no,
                        "error_message": error_message,
                    },
                    ensure_ascii=False,
                ),
                result=RESULT_FAILED,
                project_id=document.project_id,
            )
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

        document = self.get_document(document_id, user)
        self._ensure_project_document_access(document, user, "project:document:version-view")
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

        document = self.get_document(document_id, user)
        self._ensure_project_document_access(document, user, "project:document:download")
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
        SystemService(self.db).record_operation(
            user,
            "下载文件",
            TARGET_TYPE_DOCUMENT,
            document.id,
            json.dumps({"version_no": version.version_no, "file_name": version.file_name}, ensure_ascii=False),
            project_id=document.project_id,
            auto_commit=True,
        )
        return version

    def rollback_document(
        self,
        document_id: int,
        operator: User,
        version_no: int | None = None,
        permission_code: str = "project:document:version-create",
    ) -> Document:
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
        self._ensure_project_document_access(document, operator, permission_code)
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
            is_target = version.id == target.id
            version.is_current = is_target
            version.is_current_version = is_target
        document.version_no = target.version_no
        document.version = target.version or f"v{target.version_no}"
        document.document_name = target.file_name
        document.file_name = target.file_name
        document.file_type = file_type(target.file_name)
        document.storage_path = target.storage_path
        document.file_path = target.file_path or target.storage_path
        document.file_size = self._resolve_file_size(target.storage_path)
        document.directory_id = target.category_id
        document.category_id = target.category_id
        document.security_level = target.security_level
        document.status = target.status or PROJECT_DOCUMENT_STATUS_PENDING
        document.review_status = target.review_status
        document.document_status = DOCUMENT_STATUS_REVIEWED if document.status == PROJECT_DOCUMENT_STATUS_PUBLISHED else DOCUMENT_STATUS_PENDING_REVIEW
        document.parse_status = target.parse_status
        document.index_status = INDEX_STATUS_NOT_INDEXED
        document.current_version = True
        document.is_current_version = True
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

    def set_current_version(self, document_id: int, version_id: int, operator: User) -> Document:
        """按版本记录 ID 标记当前版本，供项目资料版本管理 API 使用。"""

        document = self.get_document(document_id, operator)
        self._ensure_project_document_access(document, operator, "project:document:version-set-current")
        target = self.repository.get_version_by_id(version_id)
        if target is None or target.document_id != document.id:
            raise AppException("目标版本不存在", status_code=404, code=404)
        return self.rollback_document(
            document_id,
            operator,
            target.version_no,
            permission_code="project:document:version-set-current",
        )

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
            security_level=version.security_level or document.security_level,
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

        parsed_result, mineru_artifact_summary = self._parse_document_source(document)
        return self._persist_parsed_result_as_chunks(document, parsed_result, mineru_artifact_summary)

    def _parse_document_source(self, document: Document | SimpleNamespace) -> tuple[ParsedDocumentResult, dict[str, int]]:
        """
        调用解析器并清洗页级结果，不写数据库。

        说明：
            数据库写回阶段可能因并发解析出现 MySQL 1205/1213，需要可重试；
            外部解析服务耗时较长，只应执行一次。
        """

        resolved_storage_path = self.settings.resolve_local_path(document.storage_path)
        if not resolved_storage_path.exists():
            raise AppException("源文件不存在，无法解析")

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
        mineru_artifact_summary = DocumentAssetService(self.db).materialize_mineru_output(document, parsed_result)
        return parsed_result, mineru_artifact_summary

    def _persist_parsed_result_as_chunks(
        self,
        document: Document | SimpleNamespace,
        parsed_result: ParsedDocumentResult,
        mineru_artifact_summary: dict[str, int],
    ) -> list[DocumentChunk]:
        """
        将已解析结果写入页模型、资产和待替换 Chunk。

        该方法必须保持幂等：调用方在数据库死锁/锁等待后会 rollback 并重试整个写库阶段。
        """

        asset_service = DocumentAssetService(self.db)
        asset_service.prepare_version_parse_refresh(document.id, document.version_no)
        if parsed_result.parse_source.converted_pdf_path:
            asset_service.get_or_create_converted_pdf(
                document=document,
                pdf_path=parsed_result.parse_source.converted_pdf_path,
                created_by=document.built_by or document.created_by,
            )

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
                security_level=document.security_level,
                metadata_json=json.dumps(
                    {
                        "file_name": document.file_name,
                        "version_no": document.version_no,
                        "project_id": document.project_id,
                        "knowledge_base_id": document.knowledge_base_id,
                        "category_id": document.category_id,
                        "security_level": document.security_level,
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
        self._enrich_project_fields(document)

    def _enrich_category_fields_bulk(self, documents: list[Document]) -> None:
        """
        批量补充分类展示字段，避免资料列表在大项目下逐条查询目录。
        """

        category_ids = {
            category_id
            for document in documents
            if (category_id := document.category_id or document.directory_id) is not None
        }
        if not category_ids:
            for document in documents:
                setattr(document, "category_name", None)
                setattr(document, "category_path", None)
            self._enrich_project_fields_bulk(documents)
            return

        category_by_id: dict[int, KnowledgeCategory] = {}
        pending_ids = set(category_ids)
        while pending_ids:
            rows = list(self.db.scalars(select(KnowledgeCategory).where(KnowledgeCategory.id.in_(pending_ids))).all())
            pending_ids = set()
            for category in rows:
                if category.id in category_by_id:
                    continue
                category_by_id[category.id] = category
                if category.parent_id is not None and category.parent_id not in category_by_id:
                    pending_ids.add(category.parent_id)

        path_cache: dict[int, str | None] = {}

        def category_path(category_id: int | None) -> str | None:
            if category_id is None:
                return None
            if category_id in path_cache:
                return path_cache[category_id]
            names: list[str] = []
            current = category_by_id.get(category_id)
            visited: set[int] = set()
            while current and current.id not in visited:
                visited.add(current.id)
                names.append(current.name)
                current = category_by_id.get(current.parent_id) if current.parent_id is not None else None
            path_cache[category_id] = " / ".join(reversed(names)) if names else None
            return path_cache[category_id]

        for document in documents:
            category_id = document.category_id or document.directory_id
            category = category_by_id.get(category_id) if category_id is not None else None
            setattr(document, "category_name", category.name if category else None)
            setattr(document, "category_path", category_path(category_id))
        self._enrich_project_fields_bulk(documents)

    def _enrich_project_fields(self, document: Document) -> None:
        """补充项目名称，便于详情页直接展示知识范围。"""

        project_name = None
        if document.project_id is not None:
            project = ProjectRepository(self.db).get(document.project_id)
            project_name = project.name if project else None
        setattr(document, "project_name", project_name)

    def _enrich_project_fields_bulk(self, documents: list[Document]) -> None:
        """批量补充项目名称，避免列表和详情重复查项目。"""

        project_ids = {document.project_id for document in documents if document.project_id is not None}
        if not project_ids:
            for document in documents:
                setattr(document, "project_name", None)
            return
        project_map = {
            project.id: project
            for project in self.db.scalars(
                select(Project).where(Project.id.in_(project_ids), Project.is_deleted.is_(False))
            ).all()
        }
        for document in documents:
            project = project_map.get(document.project_id) if document.project_id is not None else None
            setattr(document, "project_name", project.name if project else None)

    def _infer_document_type(self, category: object, file_name: str) -> str:
        """根据目录和文件名保守推断文档类型，匹配不到时统一归为“其他”。"""

        category_text = f"{getattr(category, 'code', '')} {getattr(category, 'name', '')} {file_name}"
        type_rules = (
            ("合同", "合同文件"),
            ("程序", "程序文件"),
            ("组织", "组织通讯录"),
            ("通讯录", "组织通讯录"),
            ("WBS", "WBS文件"),
            ("进度", "进度计划"),
            ("月报", "月报"),
            ("会议", "会议纪要"),
            ("设计输入", "设计输入"),
            ("设计基础", "设计基础"),
            ("设计成品", "设计成品"),
            ("厂商", "厂商资料"),
            ("图纸", "图纸"),
            ("设备", "设备资料"),
            ("采购", "采购文件"),
        )
        for keyword, document_type in type_rules:
            if keyword in category_text:
                return document_type
        return DEFAULT_DOCUMENT_TYPE

    def _infer_discipline(self, category: object) -> str:
        """根据目录编码和名称推断专业字段，避免上传时元数据完全为空。"""

        code = str(getattr(category, "code", "") or "")
        name = str(getattr(category, "name", "") or "")
        text = f"{code} {name}"
        discipline_rules = (
            ("工艺", "工艺"),
            ("管道", "管道"),
            ("设备", "设备"),
            ("仪表", "仪表"),
            ("电气", "电气"),
            ("结构", "结构"),
            ("造价", "造价"),
            ("拆解", "拆解"),
            ("采购", "采购"),
            ("项目", "项目管理"),
        )
        for keyword, discipline in discipline_rules:
            if keyword in text:
                return discipline
        if code.startswith("A"):
            return "项目管理"
        if code.startswith("P"):
            return "采购"
        return DEFAULT_DISCIPLINE

    def list_pages(self, document_id: int, user: User, version_no: int | None = None) -> list[DocumentPage]:
        """
        查询文档页级解析结果。

        参数:
            document_id: 文档 ID
            user: 当前用户

        返回:
            页级解析结果列表
        """

        document = self.get_document(document_id, user)
        self._ensure_project_document_access(document, user, "project:view")
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
        self._ensure_project_document_access(document, user, "project:document:preview")
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
                    "security_level": page.security_level,
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
        SystemService(self.db).record_operation(
            user,
            "预览文件",
            TARGET_TYPE_DOCUMENT,
            document.id,
            json.dumps(
                {
                    "version_no": active_version_no,
                    "page_count": len(preview_pages),
                    "source": markdown_source,
                },
                ensure_ascii=False,
            ),
            project_id=document.project_id,
            auto_commit=True,
        )
        return {
            "document": {
                "id": document.id,
                "file_name": file_name_for_preview,
                "file_type": file_type_for_preview,
                "version_no": active_version_no,
                "knowledge_type": document.knowledge_type,
                "project_id": document.project_id,
                "index_status": index_status_for_preview,
                "security_level": (version.security_level if version else document.security_level),
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
        document = self.get_document(asset.document_id, user)
        self._ensure_project_document_access(document, user, "project:document:preview")
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

        document = self.get_document(document_id, user)
        self._ensure_project_document_access(document, user, "project:document:edit")
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

        document = self.get_document(document_id, user)
        self._ensure_project_document_access(document, user, "project:document:retry-index")
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
        self._ensure_project_document_access(document, user, "project:document:retry-index")
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
        self._ensure_project_document_access(document, user, "project:document:retry-index")
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

    def update_document_security_level(self, document_id: int, security_level: str, operator: User) -> Document:
        """修改文档密级，并让依赖旧向量 metadata 的索引失效后重建。"""

        document = self.get_document(document_id, operator)
        self._ensure_project_document_access(document, operator, "project:document:security-update")
        target_level = normalize_security_level(security_level, default=document.security_level)
        ensure_security_level_access(operator, target_level, message="无权修改为超出自身最高密级的文档")
        if document.security_level == target_level:
            return document

        old_level = document.security_level
        document.security_level = target_level
        if document.index_status == INDEX_STATUS_INDEXED:
            document.index_status = INDEX_STATUS_INVALID
        for version in self.repository.list_versions(document.id):
            version.security_level = target_level
            if version.index_status == INDEX_STATUS_INDEXED:
                version.index_status = INDEX_STATUS_INVALID
        for chunk in self.repository.list_chunks(document.id, include_obsolete=True):
            chunk.security_level = target_level
        pages = list(self.db.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id)).all())
        for page in pages:
            page.security_level = target_level
        page_indexes = list(self.db.scalars(select(PageIndex).where(PageIndex.document_id == document.id)).all())
        for page_index in page_indexes:
            page_index.security_level = target_level
            if page_index.status in {"staging", "published"}:
                page_index.status = "obsolete"

        SystemService(self.db).record_operation(
            operator,
            "修改文档密级",
            TARGET_TYPE_DOCUMENT,
            document.id,
            f"{old_level}->{target_level}",
        )
        self.db.commit()
        self._enrich_category_fields(document)
        logger.info(
            "文档密级已更新并标记索引失效: document_id=%s old_level=%s new_level=%s pages=%s page_indexes=%s",
            document.id,
            old_level,
            target_level,
            len(pages),
            len(page_indexes),
        )
        return document

    def _apply_project_document_status(self, document: Document, status: str, operator: User) -> bool:
        if status not in {PROJECT_DOCUMENT_STATUS_PENDING, PROJECT_DOCUMENT_STATUS_PUBLISHED}:
            raise AppException("文件状态仅支持待审核和已发布")
        old_status = document.status
        if status == PROJECT_DOCUMENT_STATUS_PUBLISHED:
            self._ensure_project_document_access(document, operator, "project:submit-review")
            self._apply_published_status(document, operator)
        else:
            document.status = PROJECT_DOCUMENT_STATUS_PENDING
            document.document_status = DOCUMENT_STATUS_PENDING_REVIEW
            document.review_status = REVIEW_STATUS_DRAFT
            current_version = self.repository.get_current_version(document.id)
            if current_version:
                current_version.status = PROJECT_DOCUMENT_STATUS_PENDING
                current_version.review_status = REVIEW_STATUS_DRAFT
                current_version.version_status = VERSION_STATUS_DRAFT
        return old_status != document.status

    def _apply_published_status(self, document: Document, operator: User) -> None:
        current_version = self.repository.get_current_version(document.id) or self.repository.get_version(document.id, document.version_no)
        reviewed_at = now_utc()
        document.status = PROJECT_DOCUMENT_STATUS_PUBLISHED
        document.review_status = REVIEW_STATUS_APPROVED
        document.document_status = DOCUMENT_STATUS_REVIEWED
        document.reviewed_by = operator.id
        document.reviewed_at = reviewed_at
        document.current_version = True
        document.is_current_version = True
        if current_version:
            current_version.is_current = True
            current_version.status = PROJECT_DOCUMENT_STATUS_PUBLISHED
            current_version.review_status = REVIEW_STATUS_APPROVED
            current_version.version_status = VERSION_STATUS_APPROVED
            current_version.reviewed_by = operator.id
            current_version.reviewed_at = reviewed_at
            current_version.is_current_version = document.is_current_version

    def _apply_document_security_level(self, document: Document, security_level: str, operator: User) -> bool:
        target_level = normalize_security_level(security_level, default=document.security_level)
        ensure_security_level_access(operator, target_level, message="无权修改为超过自身最高密级的文档")
        if document.security_level == target_level:
            return False

        document.security_level = target_level
        if document.index_status == INDEX_STATUS_INDEXED:
            document.index_status = INDEX_STATUS_INVALID
        for version in self.repository.list_versions(document.id):
            version.security_level = target_level
            if version.index_status == INDEX_STATUS_INDEXED:
                version.index_status = INDEX_STATUS_INVALID
        for chunk in self.repository.list_chunks(document.id, include_obsolete=True):
            chunk.security_level = target_level
        pages = list(self.db.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id)).all())
        for page in pages:
            page.security_level = target_level
        page_indexes = list(self.db.scalars(select(PageIndex).where(PageIndex.document_id == document.id)).all())
        for page_index in page_indexes:
            page_index.security_level = target_level
            if page_index.status in {"staging", "published"}:
                page_index.status = "obsolete"
        return True

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
