"""
Role Schemas
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.security_levels import DEFAULT_SECURITY_LEVEL, SECURITY_LEVEL_CHOICES, normalize_security_level


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
    permission_ids: list[int] = Field(default_factory=list, description="权限ID列表")

    @classmethod
    def _normalize_security_level(cls, value: str) -> str:
        return normalize_security_level(value, default=DEFAULT_SECURITY_LEVEL)


class RoleUpdate(BaseModel):
    """Update role request."""

    name: str | None = Field(default=None, description="角色名称")
    description: str | None = Field(default=None, description="角色说明")
    enabled: bool | None = Field(default=None, description="是否启用")
    security_level: str | None = Field(default=None, description="角色最高密级")
    permission_ids: list[int] | None = Field(default=None, description="权限ID列表")

    @classmethod
    def _normalize_security_level(cls, value: str) -> str:
        return normalize_security_level(value, default=DEFAULT_SECURITY_LEVEL)


class RoleOut(BaseModel):
    """Role response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    description: str | None = None
    enabled: bool
    security_level: str
    created_at: datetime
    updated_at: datetime
    permissions: list[PermissionOut] = Field(default_factory=list, description="权限列表")

