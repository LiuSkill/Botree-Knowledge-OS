"""Knowledge base schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., description="知识库名称")
    code: str = Field(..., description="知识库编码")
    type: str = Field(..., description="知识库类型")
    project_id: int | None = Field(default=None, description="项目ID")
    description: str | None = Field(default=None, description="知识库描述")
    enabled: bool = Field(default=True, description="是否启用")


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, description="知识库名称")
    description: str | None = Field(default=None, description="知识库描述")
    enabled: bool | None = Field(default=None, description="是否启用")


class KnowledgeBaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    type: str
    project_id: int | None = None
    description: str | None = None
    enabled: bool
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime
