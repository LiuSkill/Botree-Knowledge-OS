"""
User Schemas.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.core.data_scope import DEFAULT_DATA_SCOPE
from app.core.security_levels import DEFAULT_SECURITY_LEVEL, user_max_security_level
from app.utils.user_avatar import avatar_url_for_user


class RoleBrief(BaseModel):
    """Role brief info."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="角色ID")
    name: str = Field(..., description="角色名称")
    code: str = Field(..., description="角色编码")
    enabled: bool = Field(..., description="角色是否启用")
    security_level: str = Field(default=DEFAULT_SECURITY_LEVEL, description="角色最高密级")
    data_scope: str = Field(default=DEFAULT_DATA_SCOPE, description="角色项目数据范围")


class UserCreate(BaseModel):
    """Create user request."""

    username: str = Field(..., description="用户名")
    password: str = Field(default="Botree@123456", description="初始密码")
    real_name: str = Field(..., description="真实姓名")
    email: str | None = Field(default=None, description="邮箱")
    phone: str | None = Field(default=None, description="手机号")
    department: str | None = Field(default=None, description="部门")
    department_id: int | None = Field(default=None, description="部门ID")
    role_ids: list[int] = Field(default_factory=list, description="角色ID列表")


class UserUpdate(BaseModel):
    """Update user request."""

    real_name: str | None = Field(default=None, description="真实姓名")
    email: str | None = Field(default=None, description="邮箱")
    phone: str | None = Field(default=None, description="手机号")
    department: str | None = Field(default=None, description="部门")
    department_id: int | None = Field(default=None, description="部门ID")
    status: str | None = Field(default=None, description="状态")
    role_ids: list[int] | None = Field(default=None, description="角色ID列表")


class UserOut(BaseModel):
    """User response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    real_name: str
    email: str | None = None
    phone: str | None = None
    department: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    status: str
    avatar_object_key: str | None = Field(default=None, exclude=True)
    avatar_updated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    roles: list[RoleBrief] = Field(default_factory=list, description="角色列表")

    @computed_field
    @property
    def avatar_url(self) -> str | None:
        """Avatar URL."""

        return avatar_url_for_user(self)  # type: ignore[arg-type]

    @computed_field
    @property
    def max_security_level(self) -> str:
        """Derived max security level."""

        return user_max_security_level(self)
