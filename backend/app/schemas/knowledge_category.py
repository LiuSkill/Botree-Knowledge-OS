"""
Knowledge Category Schemas

负责：
1. 定义知识分类创建、编辑和响应模型
2. 为 Swagger 提供分类范围、层级和启停字段说明
3. 支持前端渲染企业/项目隔离的无限层级分类树
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class KnowledgeCategoryCreate(BaseModel):
    """
    创建知识分类请求

    职责：
    - 接收分类基础信息
    - 明确企业分类和项目分类的范围归属
    """

    scope_type: str = Field(..., description="分类范围：base/project")
    project_id: int | None = Field(default=None, description="项目ID，项目分类必填，企业分类为空")
    parent_id: int | None = Field(default=None, description="父分类ID")
    name: str = Field(..., min_length=1, max_length=100, description="分类名称")
    code: str = Field(..., min_length=1, max_length=100, description="分类编码，同一范围内唯一")
    description: str | None = Field(default=None, description="分类说明")
    sort_order: int = Field(default=0, description="排序值")
    enabled: bool = Field(default=True, description="是否启用")


class KnowledgeCategoryUpdate(BaseModel):
    """
    更新知识分类请求

    职责：
    - 支持编辑名称、编码、父级、排序和启停状态
    - 范围字段不允许通过编辑接口改变
    """

    parent_id: int | None = Field(default=None, description="父分类ID，空值表示根分类")
    name: str | None = Field(default=None, min_length=1, max_length=100, description="分类名称")
    code: str | None = Field(default=None, min_length=1, max_length=100, description="分类编码")
    description: str | None = Field(default=None, description="分类说明")
    sort_order: int | None = Field(default=None, description="排序值")
    enabled: bool | None = Field(default=None, description="是否启用")


class KnowledgeCategoryOut(BaseModel):
    """
    知识分类响应

    职责：
    - 返回分类树节点
    - 携带直接文档数和包含子级的汇总文档数
    """

    id: int
    scope_type: str
    project_id: int | None = None
    parent_id: int | None = None
    name: str
    code: str
    description: str | None = None
    sort_order: int
    enabled: bool
    document_count: int = Field(default=0, description="直接挂载到该分类的文档数")
    total_document_count: int = Field(default=0, description="包含所有子分类的文档数")
    children: list["KnowledgeCategoryOut"] = Field(default_factory=list, description="子分类")
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime
