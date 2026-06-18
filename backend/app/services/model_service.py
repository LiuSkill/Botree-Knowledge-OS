"""
Model Service

负责：
1. 模型配置 CRUD
2. 默认模型设置
3. 调用真实模型接口执行连通性测试
"""

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.models.model_config import ModelConfig
from app.models.user import User
from app.repositories.model_repository import ModelConfigRepository
from app.schemas.model_config import ModelConfigCreate, ModelConfigUpdate
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService
from app.services.system_service import SystemService


class ModelService:
    """
    模型服务

    职责：
    - 管理 LLM/Embedding/Reranker 配置
    - 维护默认模型唯一性
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = ModelConfigRepository(db)

    def list_configs(self) -> list[ModelConfig]:
        """查询模型配置列表。"""

        return self.repository.list()

    def create_config(self, payload: ModelConfigCreate, operator: User) -> ModelConfig:
        """创建模型配置。"""

        if payload.is_default:
            self.repository.clear_default(payload.model_type)
        config = ModelConfig(**payload.model_dump())
        self.repository.add(config)
        SystemService(self.db).record_operation(operator, "新增模型配置", "model_config", config.id, config.model_name)
        self.db.commit()
        return config

    def update_config(self, config_id: int, payload: ModelConfigUpdate, operator: User) -> ModelConfig:
        """更新模型配置。"""

        config = self.repository.get(config_id)
        if not config:
            raise AppException("模型配置不存在", status_code=404, code=404)
        data = payload.model_dump(exclude_unset=True)
        if data.get("is_default"):
            self.repository.clear_default(data.get("model_type") or config.model_type)
        for key, value in data.items():
            setattr(config, key, value)
        SystemService(self.db).record_operation(operator, "编辑模型配置", "model_config", config.id, config.model_name)
        self.db.commit()
        return config

    def delete_config(self, config_id: int, operator: User) -> None:
        """删除模型配置。"""

        config = self.repository.get(config_id)
        if not config:
            raise AppException("模型配置不存在", status_code=404, code=404)
        self.repository.delete(config)
        SystemService(self.db).record_operation(operator, "删除模型配置", "model_config", config_id, "删除模型配置")
        self.db.commit()

    def test_config(self, config_id: int) -> dict:
        """测试模型配置。"""

        config = self.repository.get(config_id)
        if not config:
            raise AppException("模型配置不存在", status_code=404, code=404)
        if config.model_type in {
            "llm",
            "vision_llm",
            "reranker",
            "intent",
            "planner",
            "evidence_judge_fast",
            "evidence_judge",
            "answer_llm",
            "analysis_llm",
            "graph_extractor",
        }:
            return LLMService(self.db).test_chat_completion(config)
        if config.model_type == "embedding":
            return EmbeddingService(self.db).test_embedding(config)
        raise AppException("当前仅支持测试 LLM、Embedding、Reranker、意图识别、证据判断和图谱抽取模型配置")

    def set_default(self, config_id: int, operator: User) -> ModelConfig:
        """设为默认模型。"""

        config = self.repository.get(config_id)
        if not config:
            raise AppException("模型配置不存在", status_code=404, code=404)
        self.repository.clear_default(config.model_type)
        config.is_default = True
        SystemService(self.db).record_operation(operator, "设置默认模型", "model_config", config.id, config.model_name)
        self.db.commit()
        return config
