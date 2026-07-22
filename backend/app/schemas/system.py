"""
System Schemas

负责：
1. 工作台统计响应模型
2. 操作日志响应模型
3. 问答审计响应模型
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.chat import CitationOut


class DashboardStats(BaseModel):
    """工作台统计响应。"""

    project_count: int
    knowledge_base_count: int
    document_count: int
    knowledge_entry_count: int = Field(default=0, description="知识条目数量")
    ai_answer_count: int = Field(default=0, description="AI 回答次数")
    pending_review_count: int
    last_login_at: datetime | None = Field(default=None, description="上次登录时间")
    recent_projects: list[dict] = Field(default_factory=list, description="最近项目")
    todo_reviews: list[dict] = Field(default_factory=list, description="待办审核")
    qa_trend: dict = Field(default_factory=dict, description="近 7 天 AI 问答趋势")
    document_type_distribution: list[dict] = Field(default_factory=list, description="文档类型分布")
    knowledge_asset_distribution: dict = Field(default_factory=dict, description="知识资产分布")


class OperationLogOut(BaseModel):
    """操作日志响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    username: str | None = None
    action: str
    target_type: str
    target_id: str | None = None
    project_id: int | None = None
    detail: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    result: str
    created_at: datetime
    updated_at: datetime


class QAAuditOut(BaseModel):
    """问答明细审计响应。"""

    id: int
    message_id: int
    session_id: int
    session_title: str
    user_id: int
    username: str
    real_name: str
    avatar_url: str | None = None
    avatar_updated_at: datetime | None = None
    chat_type: str
    mode: str
    project_id: int | None = None
    project_name: str | None = None
    project_code: str | None = None
    question: str | None = None
    answer: str
    query_scope: str | None = None
    agent_trace_json: str | None = None
    citation_count: int
    citations: list[CitationOut] = Field(default_factory=list)
    retrievers: list[str] = Field(default_factory=list)
    intent: str | None = None
    elapsed_ms: int | None = None
    feedback_status: Literal["like", "dislike"] | None = None
    answered_at: datetime
    created_at: datetime


class QAAuditSessionOut(BaseModel):
    """问答会话审计响应。"""

    id: int
    session_id: int
    title: str
    user_id: int
    username: str
    real_name: str
    avatar_url: str | None = None
    avatar_updated_at: datetime | None = None
    chat_type: str
    mode: str
    project_id: int | None = None
    project_name: str | None = None
    project_code: str | None = None
    question_count: int
    answer_count: int
    citation_count: int
    latest_question: str | None = None
    latest_answer: str | None = None
    latest_qa_at: datetime
    created_at: datetime


class PageResult(BaseModel):
    """统一分页响应。"""

    items: list[dict]
    total: int
    page: int
    page_size: int
