"""
Retrieval Schemas

负责：
1. 知识检索请求和响应模型
2. 明确检索范围、权限过滤和证据片段结构
3. 支持 AI 问答复用检索结果
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.chat import CitationOut


class RetrievalSearchRequest(BaseModel):
    """知识检索请求。"""

    query: str = Field(..., description="检索关键词或问题")
    chat_type: str | None = Field(default=None, description="问答类型：project_chat/base_chat")
    mode: str = Field(default="auto", description="检索模式：auto/base_only/project_only/hybrid")
    project_id: int | None = Field(default=None, description="项目ID")
    limit: int = Field(default=5, ge=1, le=20, description="返回数量")


class RetrievalSearchResponse(BaseModel):
    """知识检索响应。"""

    query: str
    mode: str
    query_scope: str
    used_retrievers: list[str]
    citations: list[CitationOut]


class RetrievalDebugRequest(RetrievalSearchRequest):
    """
    检索调试请求

    说明：
    - 复用普通检索参数
    - debug 接口会额外返回各路召回、重排和 trace 摘要
    """

    include_trace: bool = Field(default=True, description="是否返回检索调试轨迹")
    execution_mode: Literal["planner", "all"] = Field(default="planner", description="执行模式：planner/all")
