"""
Project Schemas

负责：
1. 项目 CRUD 请求和响应模型
2. 项目成员管理模型
3. 支持项目中心和项目详情页
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    """创建项目请求。"""

    name: str = Field(..., description="项目名称")
    code: str = Field(..., description="项目编码")
    description: str | None = Field(default=None, description="项目描述")
    client: str | None = Field(default=None, description="客户名称")
    manager: str | None = Field(default=None, description="项目经理")
    status: str = Field(default="active", description="项目状态：active/completed/pending/archived")
    progress: int = Field(default=0, ge=0, le=100, description="项目进度")


class ProjectUpdate(BaseModel):
    """更新项目请求。"""

    name: str | None = Field(default=None, description="项目名称")
    description: str | None = Field(default=None, description="项目描述")
    client: str | None = Field(default=None, description="客户名称")
    manager: str | None = Field(default=None, description="项目经理")
    status: str | None = Field(default=None, description="项目状态")
    progress: int | None = Field(default=None, ge=0, le=100, description="项目进度")


class ProjectOut(BaseModel):
    """项目响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    description: str | None = None
    client: str | None = None
    manager: str | None = None
    status: str
    progress: int
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime
    knowledge_base_id: int | None = Field(default=None, description="项目知识库ID")
    document_count: int = Field(default=0, description="项目文档数")
    knowledge_count: int = Field(default=0, description="项目知识片段数")


class ProjectMemberCreate(BaseModel):
    """新增项目成员请求。"""

    user_id: int = Field(..., description="用户ID")
    role: str = Field(default="member", description="项目角色")
    permission_scope: str = Field(default="project_read", description="权限范围")
    external_user: bool = Field(default=False, description="是否外部用户")


class ProjectMemberOut(BaseModel):
    """项目成员响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    user_id: int
    role: str
    permission_scope: str
    external_user: bool
    status: str
    created_at: datetime
    updated_at: datetime
