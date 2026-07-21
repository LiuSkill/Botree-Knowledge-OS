"""
Document Schemas
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.security_levels import DEFAULT_SECURITY_LEVEL


class DocumentOut(BaseModel):
    """Document response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    knowledge_base_id: int
    knowledge_type: str
    project_id: int | None = None
    project_name: str | None = None
    directory_id: int | None = None
    document_name: str | None = None
    document_type: str | None = None
    discipline: str | None = None
    version: str | None = None
    status: str = "待审核"
    upload_user_id: int | None = None
    uploader_name: str | None = None
    uploader_username: str | None = None
    file_name: str
    file_type: str
    file_size: int
    storage_path: str
    file_path: str | None = None
    category_id: int | None = None
    category_name: str | None = None
    category_path: str | None = None
    document_status: str = "pending_review"
    parse_status: str = "unparsed"
    parse_started_at: datetime | None = None
    parse_finished_at: datetime | None = None
    parse_error: str | None = None
    parse_log: str | None = None
    review_status: str
    index_status: str
    version_no: int
    current_version: bool
    is_current_version: bool = True
    drawing_no: str | None = None
    drawing_name: str | None = None
    security_level: str = DEFAULT_SECURITY_LEVEL
    created_by: int | None = None
    submitted_by: int | None = None
    reviewed_by: int | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None
    build_started_at: datetime | None = None
    build_finished_at: datetime | None = None
    build_error: str | None = None
    built_by: int | None = None
    preview_url: str | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None
    remark: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentChunkOut(BaseModel):
    """Document chunk response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    knowledge_base_id: int
    document_id: int
    project_id: int | None = None
    knowledge_type: str
    version_no: int = 1
    chunk_status: str = "active"
    chunk_index: int
    content: str
    page_number: int | None = None
    section_title: str | None = None
    metadata_json: str | None = None
    vector_id: str | None = None
    security_level: str = DEFAULT_SECURITY_LEVEL
    created_at: datetime
    updated_at: datetime


class DocumentPageOut(BaseModel):
    """Document page response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    knowledge_base_id: int
    project_id: int | None = None
    document_id: int
    version_no: int
    page_no: int
    drawing_no: str | None = None
    page_title: str | None = None
    page_text: str
    clean_content: str | None = None
    filtered_content: str | None = None
    cleaning_metadata_json: str | None = None
    page_summary: str | None = None
    layout_json: str | None = None
    mineru_json_object_key: str | None = None
    page_image_object_key: str | None = None
    source_hash: str | None = None
    correction_status: str
    corrected_text: str | None = None
    corrected_by: int | None = None
    security_level: str = DEFAULT_SECURITY_LEVEL
    created_at: datetime
    updated_at: datetime


class DocumentAssetOut(BaseModel):
    """Document asset response."""

    id: int
    asset_type: str
    file_name: str
    mime_type: str | None = None
    storage_backend: str
    file_size: int
    status: str
    metadata_json: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentPreviewDocumentOut(BaseModel):
    """Document summary in preview."""

    id: int
    file_name: str
    file_type: str
    version_no: int
    knowledge_type: str
    project_id: int | None = None
    index_status: str
    security_level: str = DEFAULT_SECURITY_LEVEL


class DocumentPreviewBlockOut(BaseModel):
    """Block entry in preview."""

    id: int
    block_index: int
    block_type: str
    text: str | None = None
    clean_text: str | None = None
    filter_status: str = "kept"
    filter_reason: str | None = None
    bbox_json: str | None = None
    metadata_json: str | None = None
    image_asset: DocumentAssetOut | None = None


class DocumentPreviewPageOut(BaseModel):
    """Page entry in preview."""

    id: int
    page_no: int
    page_title: str | None = None
    drawing_no: str | None = None
    page_text: str
    clean_content: str | None = None
    filtered_content: str | None = None
    cleaning_metadata_json: str | None = None
    corrected_text: str | None = None
    correction_status: str
    security_level: str = DEFAULT_SECURITY_LEVEL
    page_summary: str | None = None
    page_preview_asset: DocumentAssetOut | None = None
    blocks: list[DocumentPreviewBlockOut]


class DocumentSecurityLevelUpdate(BaseModel):
    """Document security level update request."""

    security_level: str = Field(..., description="public/internal/confidential")


class DocumentMetadataUpdate(BaseModel):
    """Project document metadata update request."""

    document_name: str | None = None
    directory_id: int | None = None
    document_type: str | None = None
    discipline: str | None = None
    version: str | None = None
    status: str | None = None
    security_level: str | None = None
    preview_url: str | None = None
    remark: str | None = None


class DocumentPreviewOut(BaseModel):
    """Document preview response."""

    document: DocumentPreviewDocumentOut
    converted_pdf_asset: DocumentAssetOut | None = None
    markdown_content: str | None = None
    markdown_source: str | None = None
    markdown_image_assets: list[DocumentAssetOut] = Field(default_factory=list)
    page_count: int
    pages: list[DocumentPreviewPageOut]


class DocumentDeleteOut(BaseModel):
    """Document delete response."""

    deleted: bool
    vector_count: int
    retrieval_traces: int
    chat_citations: int
    graph_entities: int
    document_pages: int
    document_chunks: int
    document_versions: int
    index_tasks: int
    review_tasks: int
    review_logs: int
    document_assets: int
    deleted_asset_files: int
    deleted_asset_objects: int
    external_cleanup_queued: bool = False
    pending_vector_count: int = 0
    pending_file_count: int = 0
    pending_asset_object_count: int = 0


class PageCorrectionRequest(BaseModel):
    """Page correction request."""

    corrected_text: str = Field(..., description="人工修正后的页文本")
    drawing_no: str | None = Field(default=None, description="修正后的图纸编号")
    page_title: str | None = Field(default=None, description="修正后的页标题")


class QualityCheckRequest(BaseModel):
    """Quality check request."""

    passed: bool = Field(default=True, description="是否通过")
    comment: str | None = Field(default=None, description="质检备注")


class IndexTaskOut(BaseModel):
    """Index task response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version_id: int | None = None
    version_no: int
    task_type: str
    status: str
    progress: int
    error_message: str | None = None
    result_json: str | None = None
    rq_job_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


class BatchIndexBuildRequest(BaseModel):
    """批量创建索引构建任务请求。"""

    document_ids: list[int] = Field(..., min_length=1, max_length=50, description="文档ID列表")


class BatchIndexBuildResultItem(BaseModel):
    """单条索引构建任务创建结果。"""

    document_id: int
    success: bool
    message: str
    task: IndexTaskOut | None = None


class BatchIndexBuildResultOut(BaseModel):
    """批量索引构建汇总结果。"""

    total: int
    success_count: int
    failed_count: int
    results: list[BatchIndexBuildResultItem]


class DocumentVersionOut(BaseModel):
    """Document version response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    project_id: int | None = None
    version_no: int
    version: str | None = None
    category_id: int | None = None
    file_name: str
    file_type: str = ""
    file_size: int = 0
    storage_path: str
    file_path: str | None = None
    change_summary: str | None = None
    version_status: str = "draft"
    status: str = "待审核"
    parse_status: str = "unparsed"
    parse_started_at: datetime | None = None
    parse_finished_at: datetime | None = None
    parse_error: str | None = None
    parse_log: str | None = None
    review_status: str
    index_status: str
    is_current: bool
    is_current_version: bool = True
    security_level: str = DEFAULT_SECURITY_LEVEL
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None
    build_started_at: datetime | None = None
    build_finished_at: datetime | None = None
    build_error: str | None = None
    created_by: int | None = None
    upload_user_id: int | None = None
    version_note: str | None = None
    created_at: datetime
    updated_at: datetime


class ReviewSubmitRequest(BaseModel):
    """Review submit request."""

    comment: str | None = Field(default=None, description="提交说明")


class ArchiveRequest(BaseModel):
    """Archive request."""

    comment: str | None = Field(default=None, description="归档说明")
