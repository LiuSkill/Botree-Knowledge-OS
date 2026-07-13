"""
Synchronize default model configs to the independent model service.

该脚本由部署流程显式调用。只有 MODEL_SERVICE_ENABLED=true 时才会改写默认
Embedding/Reranker 配置，避免普通本地部署被意外切换。
"""

from __future__ import annotations

import logging
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal, init_database
from app.models.model_config import ModelConfig

logger = logging.getLogger(__name__)


def sync_model_service_configs(db: Session) -> dict[str, ModelConfig] | None:
    """把默认 Embedding/Reranker 配置切换到 model_service。"""

    settings = get_settings()
    if not settings.model_service_enabled:
        logger.info("MODEL_SERVICE_ENABLED=false，跳过模型服务配置同步")
        return None

    embedding_model = str(settings.embedding_model or settings.model_service_embedding_model or "").strip()
    reranker_model = str(settings.reranker_model or settings.model_service_reranker_model or "").strip()
    embedding_api_base = str(settings.embedding_api_base or settings.model_service_api_base or "").strip()
    reranker_api_base = str(settings.reranker_api_base or settings.model_service_api_base or "").strip()
    embedding_api_key = str(settings.embedding_api_key or settings.model_service_api_key or "").strip() or None
    reranker_api_key = str(settings.reranker_api_key or settings.model_service_api_key or "").strip() or None

    if not embedding_model:
        raise RuntimeError("启用模型服务时必须配置 EMBEDDING_MODEL 或 MODEL_SERVICE_EMBEDDING_MODEL")
    if not reranker_model:
        raise RuntimeError("启用模型服务时必须配置 RERANKER_MODEL 或 MODEL_SERVICE_RERANKER_MODEL")
    if not embedding_api_base:
        raise RuntimeError("启用模型服务时必须配置 EMBEDDING_API_BASE 或 MODEL_SERVICE_API_BASE")
    if not reranker_api_base:
        raise RuntimeError("启用模型服务时必须配置 RERANKER_API_BASE 或 MODEL_SERVICE_API_BASE")

    embedding_config = _upsert_default_config(
        db,
        model_type="embedding",
        provider="model_service",
        model_name=embedding_model,
        api_base=embedding_api_base,
        api_key=embedding_api_key,
    )
    reranker_config = _upsert_default_config(
        db,
        model_type="reranker",
        provider="model_service",
        model_name=reranker_model,
        api_base=reranker_api_base,
        api_key=reranker_api_key,
    )
    db.commit()
    logger.info(
        "模型服务配置同步完成: embedding_model=%s reranker_model=%s api_base=%s",
        embedding_model,
        reranker_model,
        settings.model_service_api_base,
    )
    return {"embedding": embedding_config, "reranker": reranker_config}


def _upsert_default_config(
    db: Session,
    *,
    model_type: str,
    provider: str,
    model_name: str,
    api_base: str,
    api_key: str | None,
) -> ModelConfig:
    defaults = list(
        db.scalars(
            select(ModelConfig).where(
                ModelConfig.model_type == model_type,
                ModelConfig.is_default.is_(True),
            )
        ).all()
    )
    config = defaults[0] if defaults else None
    for duplicate in defaults[1:]:
        duplicate.is_default = False

    if config is None:
        config = ModelConfig(
            provider=provider,
            model_name=model_name,
            api_base=api_base,
            api_key=api_key,
            model_type=model_type,
            is_default=True,
            enabled=True,
        )
        db.add(config)
    else:
        config.provider = provider
        config.model_name = model_name
        config.api_base = api_base
        config.api_key = api_key
        config.is_default = True
        config.enabled = True
    db.flush()
    return config


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    init_database()
    with SessionLocal() as db:
        sync_model_service_configs(db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
