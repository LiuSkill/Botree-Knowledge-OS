"""
Model Config Repository

负责：
1. 模型配置数据库访问
2. 支持默认模型设置
3. 为后续真实模型调用提供配置来源
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.model_config import ModelConfig


class ModelConfigRepository:
    """
    模型配置仓储

    职责：
    - 管理模型配置 CRUD
    - 查询默认模型
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(
        self,
        keyword: str | None = None,
        model_type: str | None = None,
        enabled: bool | None = None,
        is_default: bool | None = None,
    ) -> list[ModelConfig]:
        """查询模型配置列表。"""

        stmt = select(ModelConfig).order_by(ModelConfig.id.desc())
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                (ModelConfig.provider.like(like))
                | (ModelConfig.model_name.like(like))
                | (ModelConfig.api_base.like(like))
            )
        if model_type:
            stmt = stmt.where(ModelConfig.model_type == model_type)
        if enabled is not None:
            stmt = stmt.where(ModelConfig.enabled.is_(enabled))
        if is_default is not None:
            stmt = stmt.where(ModelConfig.is_default.is_(is_default))
        return list(self.db.scalars(stmt).all())

    def get(self, config_id: int) -> ModelConfig | None:
        """按 ID 查询模型配置。"""

        return self.db.get(ModelConfig, config_id)

    def get_default(self, model_type: str) -> ModelConfig | None:
        """
        查询指定类型的默认启用模型。

        参数:
            model_type: 模型类型，支持 llm/embedding/reranker。

        返回:
            默认且启用的模型配置，不存在时返回 None。
        """

        return self.db.scalar(
            select(ModelConfig).where(
                ModelConfig.model_type == model_type,
                ModelConfig.is_default.is_(True),
                ModelConfig.enabled.is_(True),
            )
        )

    def add(self, config: ModelConfig) -> ModelConfig:
        """新增模型配置。"""

        self.db.add(config)
        self.db.flush()
        return config

    def clear_default(self, model_type: str) -> None:
        """清除同类型默认模型。"""

        for item in self.db.scalars(select(ModelConfig).where(ModelConfig.model_type == model_type)).all():
            item.is_default = False
        self.db.flush()

    def delete(self, config: ModelConfig) -> None:
        """删除模型配置。"""

        self.db.delete(config)
        self.db.flush()
