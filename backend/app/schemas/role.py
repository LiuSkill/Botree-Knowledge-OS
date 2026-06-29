"""
Role Schemas.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.data_scope import DEFAULT_DATA_SCOPE, normalize_data_scope
from app.core.security_levels import DEFAULT_SECURITY_LEVEL, normalize_security_level


class PermissionOut(BaseModel):
    """Permission response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    module: str
    action: str
    code: str
    description: str | None = None


class RoleCreate(BaseModel):
    """Create role request."""

    name: str = Field(..., description="角色名称")
    code: str = Field(..., description="角色编码")
    description: str | None = Field(default=None, description="角色说明")
    security_level: str = Field(default=DEFAULT_SECURITY_LEVEL, description="角色最高密级")
    data_scope: str = Field(default=DEFAULT_DATA_SCOPE, description="项目数据范围：all/department/own/public_only")
    permission_ids: list[int] = Field(default_factory=list, description="权限ID列表")

    @field_validator("security_level")
    @classmethod
    def _normalize_security_level(cls, value: str) -> str:
        return normalize_security_level(value, default=DEFAULT_SECURITY_LEVEL)

    @field_validator("data_scope")
    @classmethod
    def _normalize_data_scope(cls, value: str) -> str:
        return normalize_data_scope(value, default=DEFAULT_DATA_SCOPE)


class RoleUpdate(BaseModel):
    """Update role request."""

    name: str | None = Field(default=None, description="角色名称")
    description: str | None = Field(default=None, description="角色说明")
    enabled: bool | None = Field(default=None, description="是否启用")
    security_level: str | None = Field(default=None, description="角色最高密级")
    data_scope: str | None = Field(default=None, description="项目数据范围：all/department/own/public_only")
    permission_ids: list[int] | None = Field(default=None, description="权限ID列表")

    @field_validator("security_level")
    @classmethod
    def _normalize_security_level(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_security_level(value, default=DEFAULT_SECURITY_LEVEL)

    @field_validator("data_scope")
    @classmethod
    def _normalize_data_scope(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_data_scope(value, default=DEFAULT_DATA_SCOPE)


class RoleOut(BaseModel):
    """Role response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    description: str | None = None
    enabled: bool
    security_level: str
    data_scope: str
    created_at: datetime
    updated_at: datetime
    permissions: list[PermissionOut] = Field(default_factory=list, description="权限列表")
