"""
Model Configuration Models

负责：
1. LLM、Embedding、Reranker 配置建模
2. 为后续真实模型调用预留扩展点
3. 支撑系统管理中的模型配置页面
"""

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ModelConfig(TimestampMixin, Base):
    """
    模型配置表

    职责：
    - 保存模型供应商和模型名称
    - 标记默认模型和启用状态
    - 支撑真实 LLM、Embedding 和 Reranker 调用
    """

    __tablename__ = "model_configs"
    __table_args__ = {"comment": "模型配置表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    provider: Mapped[str] = mapped_column(String(100), nullable=False, comment="模型供应商")
    model_name: Mapped[str] = mapped_column(String(150), nullable=False, comment="模型名称")
    api_base: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="API Base地址")
    api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="API Key，从.env或安全配置读取后写入")
    model_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="模型类型：llm/embedding/reranker/intent/planner/evidence_judge_fast/evidence_judge/answer_llm/vision_llm/analysis_llm",
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否默认模型")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
