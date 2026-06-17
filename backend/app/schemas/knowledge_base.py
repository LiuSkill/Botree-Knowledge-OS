"""
Knowledge Base Schemas

负责：
1. 知识库 CRUD 请求和响应模型
2. 授权展示模型
3. 支持知识中心与授权中心
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeBaseCreate(BaseModel):
    """创建知识库请求。"""

    name: str = Field(..., description="知识库名称")
    code: str = Field(..., description="知识库编码")
    type: str = Field(default="base", description="知识库类型：base/project")
    project_id: int | None = Field(default=None, description="项目ID")
    description: str | None = Field(default=None, description="知识库描述")
    visibility: str = Field(default="internal", description="可见性：internal/authorized/private")
    enabled: bool = Field(default=True, description="是否启用")


class KnowledgeBaseUpdate(BaseModel):
    """更新知识库请求。"""

    name: str | None = Field(default=None, description="知识库名称")
    description: str | None = Field(default=None, description="知识库描述")
    visibility: str | None = Field(default=None, description="可见性")
    enabled: bool | None = Field(default=None, description="是否启用")


class KnowledgeBaseOut(BaseModel):
    """知识库响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    type: str
    project_id: int | None = None
    description: str | None = None
    visibility: str
    enabled: bool
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime
    document_count: int = Field(default=0, description="文档数量")
    chunk_count: int = Field(default=0, description="知识片段数量")
