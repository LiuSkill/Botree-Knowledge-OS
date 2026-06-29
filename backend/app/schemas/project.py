"""Project schemas."""

from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.core.security_levels import DEFAULT_SECURITY_LEVEL

PROJECT_STATUS_OPTIONS = ("待启动", "进行中", "已完成", "已暂停")


class ProjectCreate(BaseModel):
    """Create project request.

    兼容历史字段 name/code/client/manager/status，同时支持本次项目基本信息字段别名。
    """

    name: str = Field(..., validation_alias=AliasChoices("name", "project_name"), description="项目名称")
    code: str = Field(..., validation_alias=AliasChoices("code", "project_code"), description="项目编号")
    project_short_name: str | None = Field(default=None, description="项目简称")
    description: str | None = Field(default=None, description="项目简介")
    client: str | None = Field(default=None, validation_alias=AliasChoices("client", "customer_name"), description="客户名称")
    manager: str | None = Field(default=None, validation_alias=AliasChoices("manager", "owner_name"), description="项目负责人")
    owner_id: int | None = Field(default=None, description="项目负责人ID")
    status: str = Field(default="进行中", validation_alias=AliasChoices("status", "project_status"), description="项目状态")
    progress: int = Field(default=0, ge=0, le=100, description="项目进度")
    security_level: str = Field(default=DEFAULT_SECURITY_LEVEL, description="项目密级")

    project_english_name: str | None = Field(default=None, description="英文名称")
    project_type: str | None = Field(default=None, description="项目类型")
    project_stage: str | None = Field(default=None, description="项目阶段")
    raw_material_type: str | None = Field(default=None, description="原料类型")
    capacity: str | None = Field(default=None, description="处理能力")
    process_route: str | None = Field(default=None, description="工艺路线")
    main_products: str | None = Field(default=None, description="主要产品")
    scope_description: str | None = Field(default=None, description="项目范围")
    deliverables: str | None = Field(default=None, description="交付成果")
    department_id: int | None = Field(default=None, description="所属部门ID")


class ProjectUpdate(BaseModel):
    """Update project request."""

    name: str | None = Field(default=None, validation_alias=AliasChoices("name", "project_name"), description="项目名称")
    code: str | None = Field(default=None, validation_alias=AliasChoices("code", "project_code"), description="项目编号")
    project_short_name: str | None = Field(default=None, description="项目简称")
    description: str | None = Field(default=None, description="项目简介")
    client: str | None = Field(default=None, validation_alias=AliasChoices("client", "customer_name"), description="客户名称")
    manager: str | None = Field(default=None, validation_alias=AliasChoices("manager", "owner_name"), description="项目负责人")
    owner_id: int | None = Field(default=None, description="项目负责人ID")
    status: str | None = Field(default=None, validation_alias=AliasChoices("status", "project_status"), description="项目状态")
    progress: int | None = Field(default=None, ge=0, le=100, description="项目进度")
    security_level: str | None = Field(default=None, description="项目密级")

    project_english_name: str | None = Field(default=None, description="英文名称")
    project_type: str | None = Field(default=None, description="项目类型")
    project_stage: str | None = Field(default=None, description="项目阶段")
    raw_material_type: str | None = Field(default=None, description="原料类型")
    capacity: str | None = Field(default=None, description="处理能力")
    process_route: str | None = Field(default=None, description="工艺路线")
    main_products: str | None = Field(default=None, description="主要产品")
    scope_description: str | None = Field(default=None, description="项目范围")
    deliverables: str | None = Field(default=None, description="交付成果")
    department_id: int | None = Field(default=None, description="所属部门ID")


class ProjectOut(BaseModel):
    """Project response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    project_name: str
    project_code: str
    project_short_name: str | None = None
    project_english_name: str | None = None
    description: str | None = None
    client: str | None = None
    customer_name: str | None = None
    manager: str | None = None
    owner_id: int | None = None
    owner_name: str | None = None
    status: str
    project_status: str
    progress: int
    security_level: str
    project_type: str | None = None
    project_stage: str | None = None
    raw_material_type: str | None = None
    capacity: str | None = None
    process_route: str | None = None
    main_products: str | None = None
    scope_description: str | None = None
    deliverables: str | None = None
    department_id: int | None = None
    created_by: int | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    knowledge_base_id: int | None = Field(default=None, description="项目知识库ID")
    document_count: int = Field(default=0, description="项目文档数量")
    knowledge_count: int = Field(default=0, description="项目知识片段数量")
    parsed_document_count: int = 0
    indexed_document_count: int = 0
    pending_review_document_count: int = 0


class ProjectMemberCreate(BaseModel):
    """Create project member request."""

    user_id: int = Field(..., description="用户ID")
    role: str = Field(default="member", description="项目角色")
    permission_scope: str = Field(default="project_read", description="权限范围")
    external_user: bool = Field(default=False, description="是否外部用户")


class ProjectMemberOut(BaseModel):
    """Project member response."""

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
