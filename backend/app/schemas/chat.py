"""
Chat Schemas

负责：
1. AI 问答请求和响应模型
2. 会话、消息、引用来源模型
3. 保存 Agent 执行过程结构
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatSessionCreate(BaseModel):
    """创建会话请求。"""

    title: str = Field(default="新的知识问答", description="会话标题")
    chat_type: str = Field(default="base_chat", description="问答类型：project_chat/base_chat")
    mode: str = Field(default="auto", description="问答模式：auto/base_only/project_only/hybrid")
    project_id: int | None = Field(default=None, description="项目ID")


class ChatSessionUpdate(BaseModel):
    """更新会话展示属性请求。"""

    title: str | None = Field(default=None, min_length=1, max_length=255, description="会话标题")
    is_pinned: bool | None = Field(default=None, description="是否置顶")
    is_favorite: bool | None = Field(default=None, description="是否收藏")


class ChatSessionOut(BaseModel):
    """会话响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    chat_type: str = "base_chat"
    mode: str
    project_id: int | None = None
    is_pinned: bool = False
    is_favorite: bool = False
    conversation_state: str | None = None
    pending_chat_type: str | None = None
    pending_answer_policy: str | None = None
    pending_evidence_status: str | None = None
    pending_created_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ChatMessageOut(BaseModel):
    """消息响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    user_id: int | None = None
    role: str
    content: str
    query_scope: str | None = None
    agent_trace_json: str | None = None
    progress_json: str | None = None
    feedback_status: Literal["like", "dislike"] | None = None
    citations: list["CitationOut"] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ChatCompletionRequest(BaseModel):
    """问答请求。"""

    chat_type: str = Field(default="base_chat", description="问答类型：project_chat/base_chat")
    mode: str = Field(default="auto", description="问答模式")
    project_id: int | None = Field(default=None, description="项目ID")
    session_id: int | None = Field(default=None, description="会话ID")
    message: str = Field(..., description="用户问题")
    agent_enabled: bool = Field(default=True, description="是否启用 Agent 执行过程")


class ChatMessageFeedbackUpdate(BaseModel):
    """问答反馈更新请求。"""

    feedback_status: Literal["like", "dislike"] | None = Field(default=None, description="回答反馈状态")


class CitationAssetOut(BaseModel):
    """引用图片资产响应。"""

    asset_id: int
    asset_type: str
    url: str
    mime_type: str | None = None
    file_name: str
    file_size: int
    page_number: int | None = None
    block_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CitationOut(BaseModel):
    """引用来源响应。"""

    source_type: str
    knowledge_base_id: int
    project_id: int | None = None
    document_id: int
    chunk_id: int
    drawing_no: str | None = None
    file_name: str
    page_number: int | None = None
    content: str
    assets: list[CitationAssetOut] = Field(default_factory=list)


class AgentTraceStep(BaseModel):
    """Agent 执行步骤。"""

    step: str
    result: str | None = None
    sequence: int | None = None
    display_text: str | None = None
    implementation: str | None = None
    status: str | None = None
    elapsed_ms: int | None = None
    intent: str | None = None
    sub_query_index: int | None = None
    sub_query_total: int | None = None
    input_summary: dict[str, Any] = Field(default_factory=dict, description="节点输入摘要")
    output_summary: dict[str, Any] = Field(default_factory=dict, description="节点输出摘要")
    details: dict[str, Any] = Field(default_factory=dict, description="节点结构化详情")


class ChatProgressEvent(BaseModel):
    """普通用户可见的问答处理进度。"""

    visible: bool = True
    stage: Literal["understanding", "planning", "retrieving", "filtering", "answering"]
    title: str
    status: Literal["pending", "running", "success", "failed"]
    sequence: int | None = None


class ChatCompletionResponse(BaseModel):
    """问答响应。"""

    answer: str
    session_id: int
    chat_type: str
    mode: str
    query_scope: str
    used_retrievers: list[str]
    agent_trace: list[AgentTraceStep]
    trace_steps: list[AgentTraceStep] = Field(default_factory=list, description="前端展示用执行步骤")
    progress_events: list[ChatProgressEvent] = Field(default_factory=list, description="普通用户可见处理进度")
    citations: list[CitationOut]
    feedback_status: Literal["like", "dislike"] | None = None
    raw: dict[str, Any] = Field(default_factory=dict, description="扩展调试信息")
