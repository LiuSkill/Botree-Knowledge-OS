"""
Embedding Service

负责：
1. 读取默认 Embedding 模型配置
2. 调用真实 OpenAI-compatible Embeddings 接口
3. 为 Milvus 索引和向量检索提供向量
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.models.model_config import ModelConfig
from app.repositories.model_repository import ModelConfigRepository
from app.services.llm_service import DISABLED_MODEL_PROVIDERS

logger = logging.getLogger(__name__)

MIN_EMBEDDING_BATCH_SIZE = 1
DASHSCOPE_EMBEDDING_BATCH_LIMIT = 10
DIMENSION_AWARE_MODEL_KEYWORDS = ("text-embedding-v3", "text-embedding-v4", "text-embedding-3")
LOCAL_EMBEDDING_PROVIDERS = {"local", "local_qwen", "qwen_local"}
MODEL_SERVICE_EMBEDDING_PROVIDERS = {"model_service"}
EMBEDDING_CACHE_MAX_SIZE = 256
_EMBEDDING_CACHE: dict[tuple[str, str, str], list[float]] = {}


@dataclass(frozen=True)
class RuntimeEmbeddingConfig:
    """
    运行时 Embedding 配置

    职责：
    - 合并数据库配置和 .env 配置
    - 屏蔽上层对 API Base、Key、模型名称的判断细节
    """

    provider: str
    model_name: str
    api_base: str | None
    api_key: str | None


class EmbeddingService:
    """
    向量化服务

    职责：
    - 调用真实 Embedding 服务
    - 校验返回向量数量和维度
    - 禁止使用 local/mock/fallback 等假向量实现
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.model_repository = ModelConfigRepository(db)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        批量生成文本向量。

        参数:
            texts: 需要向量化的文本列表。

        返回:
            与输入顺序一致的向量列表。
        """

        if not texts:
            return []

        runtime_config = self._runtime_config()
        cached_vectors = self._get_cached_vectors(texts, runtime_config)
        if cached_vectors is not None:
            logger.info(
                "Embedding缓存命中: provider=%s model=%s count=%s",
                runtime_config.provider,
                runtime_config.model_name,
                len(texts),
            )
            return cached_vectors
        started_at = time.perf_counter()
        try:
            if self._is_local_embedding(runtime_config):
                batch_size = self.settings.embedding_batch_size
                vectors = self._embed_with_local_model(texts, runtime_config)
            else:
                batch_size = self._effective_batch_size(runtime_config)
                vectors = []
                for start_index in range(0, len(texts), batch_size):
                    # 按真实服务限制分批，避免大文档一次性请求导致 Embedding 接口拒绝。
                    batch_texts = texts[start_index : start_index + batch_size]
                    vectors.extend(self._request_embeddings(batch_texts, runtime_config))
            if len(vectors) != len(texts):
                raise ValueError(f"Embedding返回数量不匹配: expected={len(texts)} actual={len(vectors)}")
            logger.info(
                "Embedding调用成功: provider=%s model=%s count=%s batch_size=%s elapsed_ms=%s",
                runtime_config.provider,
                runtime_config.model_name,
                len(texts),
                batch_size,
                int((time.perf_counter() - started_at) * 1000),
            )
            self._put_cached_vectors(texts, runtime_config, vectors)
            return vectors
        except AppException:
            raise
        except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
            logger.exception("Embedding调用失败: provider=%s model=%s", runtime_config.provider, runtime_config.model_name)
            raise AppException(f"Embedding真实接口调用失败：{exc}", status_code=502, code=502) from exc

    def test_embedding(self, config: ModelConfig) -> dict:
        """
        测试指定 Embedding 配置。

        参数:
            config: 模型配置记录。

        返回:
            连通性和向量维度信息。
        """

        runtime_config = self._runtime_config(config)
        vectors = self._embed_with_config(["连接测试"], runtime_config)
        dimension = len(vectors[0]) if vectors else 0
        return {"status": "success", "provider": runtime_config.provider, "model": runtime_config.model_name, "dimension": dimension}

    def is_configured(self) -> bool:
        """
        判断是否具备真实 Embedding 配置。

        返回:
            True 表示可尝试真实向量化，False 表示未配置。
        """

        try:
            self._runtime_config()
            return True
        except AppException:
            return False

    def warmup_local_embedding(self) -> None:
        """
        预热本地 Embedding 模型。

        说明:
            FastAPI 启动时执行一次轻量向量化，让 Qwen3-Embedding-0.6B 提前加载到进程缓存。
            远程 Embedding 配置不需要本地预热，直接跳过。
        """

        runtime_config = self._runtime_config()
        if not self._is_local_embedding(runtime_config):
            return

        from app.services.embedding_local import is_local_embedding_loaded

        loaded_before = is_local_embedding_loaded(
            runtime_config.model_name,
            self.settings.embedding_device,
            self.settings.embedding_batch_size,
            self.settings.embedding_dim,
        )
        logger.info(
            "本地Embedding预热开始: loaded=%s provider=%s model=%s device=%s dimension=%s",
            loaded_before,
            runtime_config.provider,
            runtime_config.model_name,
            self.settings.embedding_device,
            self.settings.embedding_dim,
        )
        started_at = time.perf_counter()
        vectors = self._embed_with_local_model(["embedding warmup"], runtime_config)
        actual_dimension = len(vectors[0]) if vectors else 0
        logger.info(
            "本地Embedding预热完成: loaded=%s provider=%s model=%s device=%s dimension=%s elapsed_ms=%s",
            True,
            runtime_config.provider,
            runtime_config.model_name,
            self.settings.embedding_device,
            actual_dimension,
            int((time.perf_counter() - started_at) * 1000),
        )

    def _embed_with_config(self, texts: list[str], runtime_config: RuntimeEmbeddingConfig) -> list[list[float]]:
        """使用指定配置执行向量化，供模型测试复用。"""

        try:
            if self._is_local_embedding(runtime_config):
                return self._embed_with_local_model(texts, runtime_config)
            return self._request_embeddings(texts, runtime_config)
        except AppException:
            raise
        except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
            logger.exception("Embedding配置测试失败: provider=%s model=%s", runtime_config.provider, runtime_config.model_name)
            raise AppException(f"Embedding配置测试失败：{exc}", status_code=502, code=502) from exc

    def _embed_with_local_model(self, texts: list[str], runtime_config: RuntimeEmbeddingConfig) -> list[list[float]]:
        """
        使用本地真实 Embedding 模型生成向量。

        参数:
            texts: 待向量化文本列表。
            runtime_config: 已解析的本地 Embedding 配置。

        返回:
            与输入顺序一致的向量列表。
        """

        try:
            from app.services.embedding_local import get_local_embedding

            local_embedding = get_local_embedding(
                runtime_config.model_name,
                self.settings.embedding_device,
                self.settings.embedding_batch_size,
                self.settings.embedding_dim,
            )
            return local_embedding.embed_texts(texts)
        except ImportError as exc:
            logger.exception("本地Embedding依赖缺失: model=%s", runtime_config.model_name)
            raise AppException(
                "本地Embedding依赖缺失，请安装 sentence-transformers、transformers、torch 后重试",
                status_code=500,
                code=500,
            ) from exc
        except Exception as exc:
            logger.exception("本地Embedding调用失败: model=%s", runtime_config.model_name)
            raise AppException(f"本地Embedding调用失败：{exc}", status_code=502, code=502) from exc

    def _request_embeddings(self, texts: list[str], runtime_config: RuntimeEmbeddingConfig) -> list[list[float]]:
        """
        调用 OpenAI-compatible Embeddings 接口。

        参数:
            texts: 单批次待向量化文本。
            runtime_config: 已解析的真实 Embedding 运行配置。

        返回:
            与输入文本顺序一致的浮点向量列表。
        """

        if not runtime_config.api_base:
            raise ValueError("Embedding API Base为空，无法调用远程Embedding服务")
        url = f"{runtime_config.api_base.rstrip('/')}/embeddings"
        headers = {"Content-Type": "application/json"}
        if runtime_config.api_key:
            headers["Authorization"] = f"Bearer {runtime_config.api_key}"
        payload = self._build_embedding_payload(texts, runtime_config)

        response = requests.post(url, headers=headers, json=payload, timeout=self.settings.embedding_timeout_seconds)
        response.raise_for_status()
        data = response.json()
        vectors = [item["embedding"] for item in sorted(data["data"], key=lambda item: item.get("index", 0))]
        if len(vectors) != len(texts):
            raise ValueError(f"Embedding返回数量不匹配: expected={len(texts)} actual={len(vectors)}")
        return [[float(value) for value in vector] for vector in vectors]

    def _build_embedding_payload(self, texts: list[str], runtime_config: RuntimeEmbeddingConfig) -> dict[str, object]:
        """
        构造 Embedding 请求体。

        说明:
            DashScope text-embedding-v3/v4 与 OpenAI text-embedding-3 支持 dimensions 参数，
            显式传入 EMBEDDING_DIM 可保证返回维度与 Milvus 集合配置一致。
        """

        payload: dict[str, object] = {"model": runtime_config.model_name, "input": texts}
        if self._should_send_dimensions(runtime_config):
            payload["dimensions"] = self.settings.embedding_dim
        return payload

    def _effective_batch_size(self, runtime_config: RuntimeEmbeddingConfig) -> int:
        """
        获取真实 Embedding 请求批量大小。

        参数:
            runtime_config: 已解析的真实 Embedding 运行配置。

        返回:
            可直接用于切分 texts 的批量大小。
        """

        configured_batch_size = self.settings.embedding_batch_size
        if configured_batch_size < MIN_EMBEDDING_BATCH_SIZE:
            logger.warning(
                "EMBEDDING_BATCH_SIZE无效，使用最小批量: configured=%s fallback=%s",
                configured_batch_size,
                MIN_EMBEDDING_BATCH_SIZE,
            )
            return MIN_EMBEDDING_BATCH_SIZE
        if self._is_dashscope_embedding(runtime_config) and configured_batch_size > DASHSCOPE_EMBEDDING_BATCH_LIMIT:
            logger.warning(
                "DashScope Embedding批量超过服务限制，自动截断: configured=%s limit=%s",
                configured_batch_size,
                DASHSCOPE_EMBEDDING_BATCH_LIMIT,
            )
            return DASHSCOPE_EMBEDDING_BATCH_LIMIT
        return configured_batch_size

    def _is_dashscope_embedding(self, runtime_config: RuntimeEmbeddingConfig) -> bool:
        """
        判断当前配置是否为 DashScope Embedding 服务。

        参数:
            runtime_config: 已解析的真实 Embedding 运行配置。

        返回:
            True 表示需要遵守 DashScope 单请求文本数量限制。
        """

        provider = runtime_config.provider.lower()
        api_base = (runtime_config.api_base or "").lower()
        return "dashscope" in api_base or "qwen" in provider or "dashscope" in provider

    def _is_local_embedding(self, runtime_config: RuntimeEmbeddingConfig) -> bool:
        """
        判断当前配置是否为本地真实 Embedding 模型。

        参数:
            runtime_config: 已解析的 Embedding 运行配置。

        返回:
            True 表示通过本地模型路径进行推理。
        """

        return runtime_config.provider.lower() in LOCAL_EMBEDDING_PROVIDERS

    def _should_send_dimensions(self, runtime_config: RuntimeEmbeddingConfig) -> bool:
        """
        判断当前模型是否支持 dimensions 参数。

        参数:
            runtime_config: 已解析的 Embedding 运行配置。

        返回:
            True 表示请求体应包含 dimensions。
        """

        if runtime_config.provider.lower() in MODEL_SERVICE_EMBEDDING_PROVIDERS:
            return self.settings.embedding_dim > 0
        normalized_model = runtime_config.model_name.lower()
        return self.settings.embedding_dim > 0 and any(keyword in normalized_model for keyword in DIMENSION_AWARE_MODEL_KEYWORDS)

    def _runtime_config(self, config: ModelConfig | None = None) -> RuntimeEmbeddingConfig:
        """
        解析运行时 Embedding 配置。

        参数:
            config: 指定模型配置；为空时读取默认配置。

        返回:
            可直接用于真实接口调用的配置。
        """

        model_config = config or self.model_repository.get_default("embedding")
        provider = (model_config.provider if model_config else self.settings.embedding_provider).strip()
        provider_key = provider.lower()
        if provider_key in DISABLED_MODEL_PROVIDERS:
            raise AppException("已禁用mock/fallback Embedding，请配置真实 Embedding 服务", status_code=500, code=500)

        fallback_model = self.settings.embedding_model or self.settings.model_service_embedding_model or ""
        model_name = (model_config.model_name if model_config else fallback_model).strip()
        if not model_name:
            raise AppException("未配置 EMBEDDING_MODEL 或默认 Embedding 模型", status_code=500, code=500)
        if provider_key in LOCAL_EMBEDDING_PROVIDERS:
            model_path = Path(model_name)
            if not model_path.exists():
                raise AppException(f"本地 Embedding 模型路径不存在：{model_name}", status_code=500, code=500)
            return RuntimeEmbeddingConfig(provider=provider, model_name=model_name, api_base=None, api_key=None)

        api_base = (
            (model_config.api_base if model_config else None)
            or self.settings.embedding_api_base
            or (self.settings.model_service_api_base if provider_key in MODEL_SERVICE_EMBEDDING_PROVIDERS else None)
            or self.settings.llm_base_url
            or self.settings.openai_compatible_base_url
        )
        api_key = (
            (model_config.api_key if model_config else None)
            or self.settings.embedding_api_key
            or (self.settings.model_service_api_key if provider_key in MODEL_SERVICE_EMBEDDING_PROVIDERS else None)
            or self.settings.llm_api_key
            or self.settings.openai_api_key
        )
        if not api_base:
            raise AppException("未配置 Embedding API Base", status_code=500, code=500)
        return RuntimeEmbeddingConfig(provider=provider, model_name=model_name, api_base=api_base, api_key=api_key)

    def _get_cached_vectors(self, texts: list[str], runtime_config: RuntimeEmbeddingConfig) -> list[list[float]] | None:
        """
        获取查询向量缓存。

        参数:
            texts: 待向量化文本。
            runtime_config: 当前 Embedding 配置。

        返回:
            全部命中时返回向量列表，否则返回 None。
        """

        vectors: list[list[float]] = []
        for text in texts:
            key = self._cache_key(text, runtime_config)
            cached = _EMBEDDING_CACHE.get(key)
            if cached is None:
                return None
            vectors.append(cached)
        return vectors

    def _put_cached_vectors(self, texts: list[str], runtime_config: RuntimeEmbeddingConfig, vectors: list[list[float]]) -> None:
        """
        写入查询向量缓存。

        参数:
            texts: 已向量化文本。
            runtime_config: 当前 Embedding 配置。
            vectors: 生成的向量。
        """

        for text, vector in zip(texts, vectors, strict=False):
            if len(_EMBEDDING_CACHE) >= EMBEDDING_CACHE_MAX_SIZE:
                _EMBEDDING_CACHE.pop(next(iter(_EMBEDDING_CACHE)))
            _EMBEDDING_CACHE[self._cache_key(text, runtime_config)] = vector

    def _cache_key(self, text: str, runtime_config: RuntimeEmbeddingConfig) -> tuple[str, str, str]:
        """生成 Embedding 缓存键。"""

        return (runtime_config.provider, runtime_config.model_name, text.strip())
