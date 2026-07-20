"""敏感内容管理接口结构。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SensitiveTypePayload(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    default_mask_text: str = Field(min_length=1, max_length=255)
    enabled: bool = True


class SensitiveTypeOut(SensitiveTypePayload):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class SensitiveRulePayload(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    sensitive_type_code: str
    match_type: Literal["regex", "keyword", "keyword_window"]
    pattern: str = Field(min_length=1)
    context_keywords: list[str] = Field(default_factory=list)
    window_size: int = Field(default=30, ge=0, le=500)
    mask_text: str | None = None
    priority: int = 100
    enabled: bool = True


class SensitiveRuleOut(SensitiveRulePayload):
    id: int
    version: int
    created_at: datetime
    updated_at: datetime


class RuleTestRequest(BaseModel):
    content: str
    role_id: int | None = None
    rule_id: int | None = None
    rule_enabled: bool = True


class RoleSensitivePermissionSave(BaseModel):
    permissions: dict[str, bool]
