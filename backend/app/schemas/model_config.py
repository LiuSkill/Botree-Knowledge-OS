"""
Model Config Schemas

负责：
1. 模型配置请求和响应模型
2. 支持模型测试和默认模型设置
3. 支持真实 LLM/Embedding 接口调用配置
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ModelConfigCreate(BaseModel):
    """创建模型配置请求。"""

    provider: str = Field(..., description="模型供应商")
    model_name: str = Field(..., description="模型名称")
    api_base: str | None = Field(default=None, description="API Base")
    api_key: str | None = Field(default=None, description="API Key")
    model_type: str = Field(
        default="llm",
        description="模型类型：llm/embedding/reranker/intent/planner/evidence_judge_fast/evidence_judge/answer_llm/vision_llm/analysis_llm/graph_extractor",
    )
    is_default: bool = Field(default=False, description="是否默认模型")
    enabled: bool = Field(default=True, description="是否启用")


class ModelConfigUpdate(BaseModel):
    """更新模型配置请求。"""

    provider: str | None = Field(default=None, description="模型供应商")
    model_name: str | None = Field(default=None, description="模型名称")
    api_base: str | None = Field(default=None, description="API Base")
    api_key: str | None = Field(default=None, description="API Key")
    model_type: str | None = Field(default=None, description="模型类型")
    is_default: bool | None = Field(default=None, description="是否默认模型")
    enabled: bool | None = Field(default=None, description="是否启用")


class ModelConfigOut(BaseModel):
    """模型配置响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    model_name: str
    api_base: str | None = None
    api_key: str | None = None
    model_type: str
    is_default: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime
