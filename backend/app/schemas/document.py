"""
Document Schemas

负责：
1. 文档列表、详情和 Chunk 响应模型
2. 文档版本、解析和索引操作模型
3. 支持知识中心与项目详情页
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentOut(BaseModel):
    """文档响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    knowledge_base_id: int
    knowledge_type: str
    project_id: int | None = None
    file_name: str
    file_type: str
    file_size: int
    storage_path: str
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
    drawing_no: str | None = None
    drawing_name: str | None = None
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
    created_at: datetime
    updated_at: datetime


class DocumentChunkOut(BaseModel):
    """文档 Chunk 响应。"""

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
    created_at: datetime
    updated_at: datetime


class DocumentPageOut(BaseModel):
    """文档页级响应。"""

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
    created_at: datetime
    updated_at: datetime


class DocumentAssetOut(BaseModel):
    """文档派生资产响应。"""

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
    """原始内容预览中的文档摘要。"""

    id: int
    file_name: str
    file_type: str
    version_no: int
    knowledge_type: str
    project_id: int | None = None
    index_status: str


class DocumentPreviewBlockOut(BaseModel):
    """原始内容预览中的块级结构。"""

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
    """原始内容预览中的页级结构。"""

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
    page_summary: str | None = None
    page_preview_asset: DocumentAssetOut | None = None
    blocks: list[DocumentPreviewBlockOut]


class DocumentPreviewOut(BaseModel):
    """原始内容预览响应。"""

    document: DocumentPreviewDocumentOut
    converted_pdf_asset: DocumentAssetOut | None = None
    markdown_content: str | None = None
    markdown_source: str | None = None
    markdown_image_assets: list[DocumentAssetOut] = Field(default_factory=list)
    page_count: int
    pages: list[DocumentPreviewPageOut]


class DocumentDeleteOut(BaseModel):
    """
    文档删除结果响应。

    说明：
        统一返回文档删除时已清理的检索、预览、审核和任务数据统计，
        便于前端展示二次确认后的清理结果。
    """

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
    """页级人工修正请求。"""

    corrected_text: str = Field(..., description="人工修正后的页文本")
    drawing_no: str | None = Field(default=None, description="修正后的图纸编号")
    page_title: str | None = Field(default=None, description="修正后的页标题")


class QualityCheckRequest(BaseModel):
    """解析质量确认请求。"""

    passed: bool = Field(default=True, description="是否通过质量检查")
    comment: str | None = Field(default=None, description="质量检查备注")


class IndexTaskOut(BaseModel):
    """离线索引任务响应。"""

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


class DocumentVersionOut(BaseModel):
    """文档版本响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version_no: int
    category_id: int | None = None
    file_name: str
    file_type: str = ""
    file_size: int = 0
    storage_path: str
    change_summary: str | None = None
    version_status: str = "draft"
    parse_status: str = "unparsed"
    parse_started_at: datetime | None = None
    parse_finished_at: datetime | None = None
    parse_error: str | None = None
    parse_log: str | None = None
    review_status: str
    index_status: str
    is_current: bool
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None
    build_started_at: datetime | None = None
    build_finished_at: datetime | None = None
    build_error: str | None = None
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


class ReviewSubmitRequest(BaseModel):
    """提交审核请求。"""

    comment: str | None = Field(default=None, description="提交说明")


class ArchiveRequest(BaseModel):
    """归档请求。"""

    comment: str | None = Field(default=None, description="归档说明")
