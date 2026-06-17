"""
Documents API

负责：
1. 文档列表、详情、删除、下载和版本管理
2. 文档审核、解析、索引和原始内容预览
3. 文档页级结果与派生资产访问
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import AppException
from app.core.minio import get_minio_client
from app.core.response import success
from app.models.user import User
from app.schemas.document import (
    ArchiveRequest,
    DocumentChunkOut,
    DocumentDeleteOut,
    DocumentOut,
    DocumentPageOut,
    DocumentPreviewOut,
    DocumentVersionOut,
    IndexTaskOut,
    PageCorrectionRequest,
    QualityCheckRequest,
    ReviewSubmitRequest,
)
from app.services.document_service import DocumentService
from app.services.review_service import ReviewService

router = APIRouter(prefix="/documents", tags=["文档管理"])


def _stream_minio_object(object_key: str) -> Iterator[bytes]:
    """以流式方式返回 MinIO 对象内容。"""

    settings = get_settings()
    client = get_minio_client()
    if client is None:
        raise AppException("对象存储未启用，无法读取派生资产", status_code=404, code=404)
    response = client.get_object(settings.minio_bucket, object_key)
    try:
        for chunk in response.stream(32 * 1024):
            yield chunk
    finally:
        response.close()
        response.release_conn()


@router.get("", summary="文档列表")
def list_documents(
    project_id: int | None = None,
    review_status: str | None = None,
    category_id: int | None = None,
    index_status: str | None = None,
    knowledge_type: str | None = None,
    keyword: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """查询文档列表。"""

    documents = DocumentService(db).list_documents(
        current_user,
        project_id=project_id,
        review_status=review_status,
        category_id=category_id,
        index_status=index_status,
        knowledge_type=knowledge_type,
        keyword=keyword,
    )
    return success([DocumentOut.model_validate(item).model_dump(mode="json") for item in documents])


@router.get("/assets/{asset_id}", summary="查看文档派生资产")
def get_document_asset(asset_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """按权限受控返回派生资产文件。"""

    asset = DocumentService(db).get_document_asset(asset_id, current_user)
    settings = get_settings()
    if asset.storage_path:
        asset_path = settings.resolve_local_path(asset.storage_path)
    else:
        asset_path = None
    if asset_path and asset_path.is_file():
        return FileResponse(
            path=asset_path,
            filename=asset.file_name,
            media_type=asset.mime_type or "application/octet-stream",
            content_disposition_type="inline",
        )

    if asset.object_key:
        return StreamingResponse(
            _stream_minio_object(asset.object_key),
            media_type=asset.mime_type or "application/octet-stream",
            headers={"Content-Disposition": f'inline; filename="{asset.file_name}"'},
        )

    raise AppException("派生资产文件不存在", status_code=404, code=404)


@router.get("/{document_id}", summary="文档详情")
def get_document(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """查询文档详情。"""

    document = DocumentService(db).get_document(document_id, current_user)
    return success(DocumentOut.model_validate(document).model_dump(mode="json"))


@router.delete("/{document_id}", summary="删除文档")
def delete_document(
    document_id: int,
    current_user: User = Depends(require_permission("knowledge:delete")),
    db: Session = Depends(get_db),
) -> dict:
    """删除文档及其检索相关数据。"""

    result = DocumentService(db).delete_document(document_id, current_user)
    return success(DocumentDeleteOut.model_validate(result).model_dump(mode="json"))


@router.get("/{document_id}/download-url", summary="下载地址")
def download_url(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """获取文档下载信息。"""

    return success(DocumentService(db).download_url(document_id, current_user))


@router.get("/{document_id}/chunks", summary="文档切块")
def list_chunks(
    document_id: int,
    version_no: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """查询文档 Chunk。"""

    chunks = DocumentService(db).list_chunks(document_id, current_user, version_no)
    return success([DocumentChunkOut.model_validate(item).model_dump(mode="json") for item in chunks])


@router.get("/{document_id}/pages", summary="文档页级解析结果")
def list_pages(
    document_id: int,
    version_no: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """查询文档页级解析结果。"""

    pages = DocumentService(db).list_pages(document_id, current_user, version_no)
    return success([DocumentPageOut.model_validate(item).model_dump(mode="json") for item in pages])


@router.get("/{document_id}/preview", summary="文档原始内容预览")
def preview_document(
    document_id: int,
    version_no: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """返回当前版本的页、块和图片预览结构。"""

    preview = DocumentService(db).preview_document(document_id, current_user, version_no)
    return success(DocumentPreviewOut.model_validate(preview).model_dump(mode="json"))


@router.put("/{document_id}/pages/{page_no}/correction", summary="人工修正文档页")
def correct_page(
    document_id: int,
    page_no: int,
    payload: PageCorrectionRequest,
    current_user: User = Depends(require_permission("review:review")),
    db: Session = Depends(get_db),
) -> dict:
    """人工修正文档页级文本、图纸号和页标题。"""

    page = DocumentService(db).correct_page(
        document_id,
        page_no,
        payload.corrected_text,
        current_user,
        payload.drawing_no,
        payload.page_title,
    )
    return success(DocumentPageOut.model_validate(page).model_dump(mode="json"))


@router.post("/{document_id}/quality-check", summary="解析质量检查")
def quality_check(
    document_id: int,
    payload: QualityCheckRequest | None = None,
    current_user: User = Depends(require_permission("review:review")),
    db: Session = Depends(get_db),
) -> dict:
    """确认页级解析质量，通过后才允许进入索引构建。"""

    request = payload or QualityCheckRequest()
    return success(DocumentService(db).quality_check(document_id, current_user, request.passed, request.comment))


@router.post("/{document_id}/submit-review", summary="提交审核")
def submit_review(
    document_id: int,
    version_no: int | None = None,
    payload: ReviewSubmitRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """提交文档审核。"""

    task = ReviewService(db).submit_review(document_id, current_user, payload.comment if payload else None, version_no)
    return success(
        {
            "review_task_id": task.id,
            "review_status": task.review_status,
            "version_id": task.version_id,
            "version_no": task.version_no,
        }
    )


@router.post("/{document_id}/parse", summary="解析文档")
def parse_document(
    document_id: int,
    version_no: int | None = None,
    current_user: User = Depends(require_permission("review:review")),
    db: Session = Depends(get_db),
) -> dict:
    """解析文档并生成 Chunk。"""

    if version_no is not None:
        return success(DocumentService(db).parse_document_version(document_id, version_no, current_user))
    return success(DocumentService(db).parse_document(document_id, current_user))


@router.post("/{document_id}/index", summary="构建索引")
def index_document(document_id: int, current_user: User = Depends(require_permission("review:review")), db: Session = Depends(get_db)) -> dict:
    """构建文档索引。"""

    return success(DocumentService(db).index_document(document_id, current_user))


@router.post("/{document_id}/build-index", summary="解析并构建索引")
def build_document_index(
    document_id: int,
    version_no: int | None = None,
    current_user: User = Depends(require_permission("review:review")),
    db: Session = Depends(get_db),
) -> dict:
    """同步执行文档解析和索引构建。"""

    return success(DocumentService(db).build_document_index(document_id, current_user, version_no))


@router.get("/{document_id}/indexes", summary="索引状态")
def document_indexes(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """查询文档索引状态。"""

    document = DocumentService(db).get_document(document_id, current_user)
    return success(
        {
            "document_id": document.id,
            "index_status": document.index_status,
            "chunk_count": len(DocumentService(db).list_chunks(document_id, current_user, document.version_no)),
            "build_started_at": document.build_started_at,
            "build_finished_at": document.build_finished_at,
            "build_error": document.build_error,
            "built_by": document.built_by,
        }
    )


@router.post("/{document_id}/indexes/build", summary="创建离线索引构建任务")
def create_index_build_task(
    document_id: int,
    version_no: int | None = None,
    current_user: User = Depends(require_permission("review:review")),
    db: Session = Depends(get_db),
) -> dict:
    """创建 RQ 异步索引构建任务。"""

    task = DocumentService(db).create_index_build_task(document_id, current_user, version_no)
    return success(IndexTaskOut.model_validate(task).model_dump(mode="json"))


@router.post("/{document_id}/indexes/publish", summary="创建索引发布任务")
def create_index_publish_task(
    document_id: int,
    current_user: User = Depends(require_permission("review:review")),
    db: Session = Depends(get_db),
) -> dict:
    """发布当前文档版本的 staging 索引。"""

    task = DocumentService(db).create_index_publish_task(document_id, current_user)
    return success(IndexTaskOut.model_validate(task).model_dump(mode="json"))


@router.get("/{document_id}/index-tasks", summary="文档索引任务")
def list_index_tasks(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """查询文档离线索引任务列表。"""

    tasks = DocumentService(db).list_index_tasks(document_id, current_user)
    return success([IndexTaskOut.model_validate(item).model_dump(mode="json") for item in tasks])


@router.post("/{document_id}/versions", summary="上传新版本")
async def create_version(
    document_id: int,
    file: UploadFile = File(...),
    change_summary: str | None = Form(default=None),
    category_id: int | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """上传文档新版本。"""

    version = await DocumentService(db).create_version(document_id, file, current_user, change_summary, category_id)
    return success(DocumentVersionOut.model_validate(version).model_dump(mode="json"))


@router.get("/{document_id}/versions", summary="版本列表")
def list_versions(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """查询文档版本列表。"""

    versions = DocumentService(db).list_versions(document_id, current_user)
    return success([DocumentVersionOut.model_validate(item).model_dump(mode="json") for item in versions])


@router.get("/{document_id}/versions/{version_no}/download", summary="下载指定版本文件")
def download_version_file(
    document_id: int,
    version_no: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """下载同一文档版本链中的指定版本原始文件。"""

    version = DocumentService(db).get_version_file(document_id, version_no, current_user)
    version_path = get_settings().resolve_local_path(version.storage_path)
    return FileResponse(
        path=version_path,
        filename=version.file_name,
        content_disposition_type="inline",
    )


@router.post("/{document_id}/rollback", summary="版本回滚")
def rollback_document(
    document_id: int,
    version_no: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """回滚文档版本。"""

    document = DocumentService(db).rollback_document(document_id, current_user, version_no)
    return success(DocumentOut.model_validate(document).model_dump(mode="json"))


@router.post("/{document_id}/archive", summary="归档文档")
def archive_document(
    document_id: int,
    payload: ArchiveRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """归档文档。"""

    document = DocumentService(db).archive_document(document_id, current_user, payload.comment if payload else None)
    return success(DocumentOut.model_validate(document).model_dump(mode="json"))
