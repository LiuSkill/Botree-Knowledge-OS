"""
Local Reranker Runtime

负责加载本地 CrossEncoder reranker，并在进程内复用模型实例。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import RLock
from typing import Any

import torch

logger = logging.getLogger(__name__)

LocalRerankerCacheKey = tuple[str, str, int]
_LOCAL_RERANKER_CACHE: dict[LocalRerankerCacheKey, "LocalCrossEncoderReranker"] = {}
_LOCAL_RERANKER_CACHE_LOCK = RLock()


class LocalCrossEncoderReranker:
    """
    本地 CrossEncoder Reranker 推理器。

    业务规则：
        reranker 输入是 query 与候选正文的成对文本，输出一个相关性分数；
        同一进程内相同模型、设备和 batch_size 只加载一次，避免每轮问答重复加载大模型。
    """

    def __init__(self, model_name: str, device: str, batch_size: int) -> None:
        self.model_path = self._resolve_model_path(model_name)
        self.batch_size = max(1, int(batch_size))
        self.requested_device = self._normalize_device(device)
        self.device = self._resolve_device(self.requested_device)
        self.model: Any | None = None

        started_at = time.perf_counter()
        logger.info(
            "本地Reranker模型加载开始: loaded=%s path=%s requested_device=%s resolved_device=%s batch_size=%s",
            False,
            self.model_path,
            self.requested_device,
            self.device,
            self.batch_size,
        )
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(str(self.model_path), device=self.device, trust_remote_code=True)
        logger.info(
            "本地Reranker模型加载完成: loaded=%s path=%s backend=%s requested_device=%s resolved_device=%s elapsed_ms=%s",
            self.is_loaded,
            self.model_path,
            self.backend_name,
            self.requested_device,
            self.device,
            int((time.perf_counter() - started_at) * 1000),
        )

    @property
    def is_loaded(self) -> bool:
        return self.model is not None

    @property
    def backend_name(self) -> str:
        return "sentence-transformers-cross-encoder"

    def predict(self, query: str, documents: list[str]) -> list[float]:
        """对候选文档执行成对重排打分。"""

        if not documents:
            return []
        if self.model is None:
            raise RuntimeError("Local reranker model is not loaded")

        started_at = time.perf_counter()
        pairs = [(query, document) for document in documents]
        scores = self.model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        result = [float(score) for score in scores.tolist()]
        logger.info(
            "本地Reranker调用完成: loaded=%s path=%s backend=%s requested_device=%s resolved_device=%s count=%s batch_size=%s elapsed_ms=%s",
            self.is_loaded,
            self.model_path,
            self.backend_name,
            self.requested_device,
            self.device,
            len(documents),
            self.batch_size,
            int((time.perf_counter() - started_at) * 1000),
        )
        return result

    def _resolve_model_path(self, model_name: str) -> Path:
        model_path = Path(model_name)
        if model_path.exists():
            return model_path
        raise FileNotFoundError(f"Reranker model path does not exist: {model_name}")

    def _normalize_device(self, requested_device: str) -> str:
        return (requested_device or "cpu").lower().strip()

    def _resolve_device(self, requested_device: str) -> str:
        normalized_device = self._normalize_device(requested_device)
        if normalized_device == "cuda":
            if torch.cuda.is_available() and self._cuda_smoke_test():
                return "cuda"
            logger.warning("配置请求CUDA但当前环境不可用，本地Reranker自动回退CPU")
        return "cpu"

    def _cuda_smoke_test(self) -> bool:
        try:
            device = torch.device("cuda")
            tensor = torch.tensor([1], device=device)
            _ = tensor + 1
            torch.cuda.synchronize()
            return True
        except Exception:
            logger.exception("Reranker CUDA基础可用性测试失败")
            return False


def get_local_reranker(model_name: str, device: str, batch_size: int) -> LocalCrossEncoderReranker:
    """获取本地 reranker 单例。"""

    cache_key = _build_cache_key(model_name, device, batch_size)
    with _LOCAL_RERANKER_CACHE_LOCK:
        cached_reranker = _LOCAL_RERANKER_CACHE.get(cache_key)
        if cached_reranker is not None:
            logger.info(
                "本地Reranker模型缓存命中: loaded=%s path=%s requested_device=%s resolved_device=%s batch_size=%s",
                cached_reranker.is_loaded,
                cached_reranker.model_path,
                device,
                cached_reranker.device,
                cached_reranker.batch_size,
            )
            return cached_reranker

        started_at = time.perf_counter()
        local_reranker = LocalCrossEncoderReranker(model_name=model_name, device=device, batch_size=batch_size)
        _LOCAL_RERANKER_CACHE[cache_key] = local_reranker
        logger.info(
            "本地Reranker模型已写入单例缓存: loaded=%s path=%s requested_device=%s resolved_device=%s batch_size=%s elapsed_ms=%s",
            local_reranker.is_loaded,
            local_reranker.model_path,
            local_reranker.requested_device,
            local_reranker.device,
            local_reranker.batch_size,
            int((time.perf_counter() - started_at) * 1000),
        )
        return local_reranker


def is_local_reranker_loaded(model_name: str, device: str, batch_size: int) -> bool:
    """查询当前进程是否已经加载指定本地 reranker。"""

    cache_key = _build_cache_key(model_name, device, batch_size)
    with _LOCAL_RERANKER_CACHE_LOCK:
        cached_reranker = _LOCAL_RERANKER_CACHE.get(cache_key)
        return bool(cached_reranker and cached_reranker.is_loaded)


def _build_cache_key(model_name: str, device: str, batch_size: int) -> LocalRerankerCacheKey:
    return (model_name, (device or "cpu").lower().strip(), max(1, int(batch_size)))
