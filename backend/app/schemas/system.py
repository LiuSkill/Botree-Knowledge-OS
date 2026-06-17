"""
System Schemas

负责：
1. 工作台统计响应模型
2. 操作日志响应模型
3. 问答审计响应模型
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DashboardStats(BaseModel):
    """工作台统计响应。"""

    project_count: int
    knowledge_base_count: int
    document_count: int
    knowledge_entry_count: int = Field(default=0, description="知识条目数量")
    ai_answer_count: int = Field(default=0, description="AI 回答次数")
    pending_review_count: int
    last_login_at: datetime | None = Field(default=None, description="上次登录时间")
    recent_documents: list[dict] = Field(default_factory=list, description="最近资料")
    recent_projects: list[dict] = Field(default_factory=list, description="最近项目")
    todo_reviews: list[dict] = Field(default_factory=list, description="待办审核")
    recent_ai_questions: list[dict] = Field(default_factory=list, description="最近 AI 提问")
    knowledge_category_stats: list[dict] = Field(default_factory=list, description="知识分类统计")


class OperationLogOut(BaseModel):
    """操作日志响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    username: str | None = None
    action: str
    target_type: str
    target_id: str | None = None
    detail: str | None = None
    ip_address: str | None = None
    result: str
    created_at: datetime
    updated_at: datetime


class QAAuditOut(BaseModel):
    """问答审计响应。"""

    id: int
    session_id: int
    answer: str
    query_scope: str | None = None
    agent_trace_json: str | None = None
    citation_count: int
    created_at: datetime
