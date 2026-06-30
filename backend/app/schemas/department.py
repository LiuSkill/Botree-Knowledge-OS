"""Department Schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DepartmentStatus = Literal["enabled", "disabled"]


class DepartmentBase(BaseModel):
    """部门新增和编辑的公共字段。"""

    name: str = Field(..., min_length=1, max_length=100, description="部门名称")
    code: str = Field(..., min_length=1, max_length=100, description="部门编码")
    parent_id: int | None = Field(default=None, description="上级部门ID")
    leader_user_id: int | None = Field(default=None, description="负责人用户ID")
    sort_order: int = Field(default=0, ge=0, le=999999, description="排序")
    status: DepartmentStatus = Field(default="enabled", description="状态")
    description: str | None = Field(default=None, max_length=1000, description="备注")

    @field_validator("name", "code")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("description")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class DepartmentCreate(DepartmentBase):
    """Create department request."""


class DepartmentUpdate(BaseModel):
    """Update department request."""

    name: str | None = Field(default=None, min_length=1, max_length=100, description="部门名称")
    code: str | None = Field(default=None, min_length=1, max_length=100, description="部门编码")
    parent_id: int | None = Field(default=None, description="上级部门ID")
    leader_user_id: int | None = Field(default=None, description="负责人用户ID")
    sort_order: int | None = Field(default=None, ge=0, le=999999, description="排序")
    status: DepartmentStatus | None = Field(default=None, description="状态")
    description: str | None = Field(default=None, max_length=1000, description="备注")

    @field_validator("name", "code")
    @classmethod
    def _strip_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("description")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class DepartmentStatusUpdate(BaseModel):
    """Update department status request."""

    status: DepartmentStatus = Field(..., description="目标状态")


class DepartmentOut(BaseModel):
    """Department response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    parent_id: int | None = None
    parent_name: str | None = None
    leader_user_id: int | None = None
    leader_name: str | None = None
    sort_order: int
    status: DepartmentStatus
    description: str | None = None
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime
    children: list["DepartmentOut"] = Field(default_factory=list)


class DepartmentUserOption(BaseModel):
    """部门负责人选择项。"""

    id: int
    username: str
    real_name: str
    status: str
