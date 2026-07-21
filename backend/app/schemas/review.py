"""
Review Schemas

负责：
1. 审核任务响应模型
2. 审核通过和驳回请求模型
3. 审核日志响应模型
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReviewDecisionRequest(BaseModel):
    """审核处理请求。"""

    comment: str | None = Field(default=None, description="审核意见")


class ReviewBatchDecisionRequest(BaseModel):
    """批量审核处理请求。"""

    task_ids: list[int] = Field(..., min_length=1, max_length=50, description="审核任务ID列表")
    comment: str | None = Field(default=None, max_length=500, description="统一审核意见")


class ReviewBatchResultItem(BaseModel):
    """单条批量审核结果。"""

    task_id: int
    success: bool
    message: str


class ReviewBatchResultOut(BaseModel):
    """批量审核汇总结果。"""

    total: int
    success_count: int
    failed_count: int
    results: list[ReviewBatchResultItem]


class ReviewTaskOut(BaseModel):
    """审核任务响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    project_id: int | None = None
    document_file_name: str | None = None
    document_category_name: str | None = None
    document_category_path: str | None = None
    display_version_no: int | None = None
    uploader_id: int | None = None
    uploader_name: str | None = None
    uploader_username: str | None = None
    version_id: int | None = None
    version_no: int | None = None
    reviewer_id: int | None = None
    review_status: str
    review_comment: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ReviewLogOut(BaseModel):
    """审核日志响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version_id: int | None = None
    version_no: int | None = None
    action: str
    operator_id: int | None = None
    comment: str | None = None
    created_at: datetime
    updated_at: datetime
