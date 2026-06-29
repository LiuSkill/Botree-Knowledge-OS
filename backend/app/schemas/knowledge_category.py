"""Knowledge category schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.security_levels import DEFAULT_SECURITY_LEVEL


class KnowledgeCategoryCreate(BaseModel):
    """Create knowledge category/project directory request."""

    scope_type: str = Field(..., description="分类范围：base/project")
    project_id: int | None = Field(default=None, description="项目ID，项目目录必填，企业分类为空")
    parent_id: int | None = Field(default=None, description="父分类ID")
    name: str = Field(..., min_length=1, max_length=100, description="分类名称")
    code: str = Field(..., min_length=1, max_length=100, description="分类编码，同一范围内唯一")
    description: str | None = Field(default=None, description="分类说明")
    sort_order: int = Field(default=0, description="排序值")
    enabled: bool = Field(default=True, description="是否启用")
    default_security_level: str = Field(default=DEFAULT_SECURITY_LEVEL, description="目录默认密级")


class KnowledgeCategoryUpdate(BaseModel):
    """Update knowledge category/project directory request."""

    parent_id: int | None = Field(default=None, description="父分类ID，空值表示根分类")
    name: str | None = Field(default=None, min_length=1, max_length=100, description="分类名称")
    code: str | None = Field(default=None, min_length=1, max_length=100, description="分类编码")
    description: str | None = Field(default=None, description="分类说明")
    sort_order: int | None = Field(default=None, description="排序值")
    enabled: bool | None = Field(default=None, description="是否启用")
    default_security_level: str | None = Field(default=None, description="目录默认密级")


class KnowledgeCategoryOut(BaseModel):
    """Knowledge category/project directory response."""

    id: int
    scope_type: str
    project_id: int | None = None
    parent_id: int | None = None
    name: str
    code: str
    description: str | None = None
    sort_order: int
    enabled: bool
    default_security_level: str = DEFAULT_SECURITY_LEVEL
    is_deleted: bool = False
    deleted_at: datetime | None = None
    document_count: int = Field(default=0, description="直接挂载到该分类的文档数")
    total_document_count: int = Field(default=0, description="包含所有子分类的文档数")
    children: list["KnowledgeCategoryOut"] = Field(default_factory=list, description="子分类")
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime
