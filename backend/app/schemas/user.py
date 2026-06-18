"""
User Schemas

负责：
1. 用户管理请求和响应模型
2. 支持角色信息嵌套展示
3. 保证用户接口具备 Swagger 说明
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.utils.user_avatar import avatar_url_for_user


class RoleBrief(BaseModel):
    """角色简要信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="角色ID")
    name: str = Field(..., description="角色名称")
    code: str = Field(..., description="角色编码")
    enabled: bool = Field(..., description="角色是否启用")


class UserCreate(BaseModel):
    """新增用户请求。"""

    username: str = Field(..., description="用户名")
    password: str = Field(default="Botree@123456", description="初始密码")
    real_name: str = Field(..., description="真实姓名")
    email: str | None = Field(default=None, description="邮箱")
    phone: str | None = Field(default=None, description="手机号")
    department: str | None = Field(default=None, description="部门")
    role_ids: list[int] = Field(default_factory=list, description="角色ID列表")


class UserUpdate(BaseModel):
    """更新用户请求。"""

    real_name: str | None = Field(default=None, description="真实姓名")
    email: str | None = Field(default=None, description="邮箱")
    phone: str | None = Field(default=None, description="手机号")
    department: str | None = Field(default=None, description="部门")
    status: str | None = Field(default=None, description="状态：enabled/disabled")
    role_ids: list[int] | None = Field(default=None, description="角色ID列表")


class UserOut(BaseModel):
    """用户响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    real_name: str
    email: str | None = None
    phone: str | None = None
    department: str | None = None
    status: str
    avatar_object_key: str | None = Field(default=None, exclude=True)
    avatar_updated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    roles: list[RoleBrief] = Field(default_factory=list, description="角色列表")

    @computed_field
    @property
    def avatar_url(self) -> str | None:
        """头像访问地址。"""

        return avatar_url_for_user(self)  # type: ignore[arg-type]
