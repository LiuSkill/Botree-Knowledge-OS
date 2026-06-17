"""
Role Schemas

负责：
1. 角色管理请求和响应模型
2. 权限矩阵响应模型
3. 支持系统管理页面
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PermissionOut(BaseModel):
    """权限响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    module: str
    action: str
    code: str
    description: str | None = None


class RoleCreate(BaseModel):
    """新增角色请求。"""

    name: str = Field(..., description="角色名称")
    code: str = Field(..., description="角色编码")
    description: str | None = Field(default=None, description="角色描述")
    permission_ids: list[int] = Field(default_factory=list, description="权限ID列表")


class RoleUpdate(BaseModel):
    """更新角色请求。"""

    name: str | None = Field(default=None, description="角色名称")
    description: str | None = Field(default=None, description="角色描述")
    enabled: bool | None = Field(default=None, description="是否启用")
    permission_ids: list[int] | None = Field(default=None, description="权限ID列表")


class RoleOut(BaseModel):
    """角色响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    description: str | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime
    permissions: list[PermissionOut] = Field(default_factory=list, description="权限列表")
