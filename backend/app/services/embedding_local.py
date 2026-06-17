"""
Local Qwen Embedding Service

负责：
1. 从本地模型目录加载 Qwen3-Embedding-0.6B。
2. 使用 sentence-transformers 优先推理，失败时回退到 transformers。
3. 输出固定维度的归一化向量，供 Milvus 索引和检索复用。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import RLock
from typing import Any

import torch
import torch.nn.functional as F
from sentence_transformers import SentenceTransformer
from transformers import AutoModel, AutoTokenizer

logger = logging.getLogger(__name__)

LocalEmbeddingCacheKey = tuple[str, str, int, int]
_LOCAL_EMBEDDING_CACHE: dict[LocalEmbeddingCacheKey, "LocalQwenEmbedding"] = {}
_LOCAL_EMBEDDING_CACHE_LOCK = RLock()


class LocalQwenEmbedding:
    """
    本地 Qwen Embedding 推理器

    职责：
    - 校验本地模型目录是否存在
    - 加载 Qwen3-Embedding-0.6B 并生成向量
    - 在 CUDA 不可用或显存不足时自动降级到 CPU
    """

    def __init__(self, model_name: str, device: str, batch_size: int, dimension: int) -> None:
        """
        初始化本地 Embedding 推理器。

        参数:
            model_name: 本地模型绝对路径或可解析路径。
            device: 期望推理设备，支持 cuda/cpu。
            batch_size: 推理批量大小。
            dimension: 输出向量维度。
        """

        self.model_path = self._resolve_model_path(model_name)
        self.batch_size = max(1, batch_size)
        self.dimension = dimension
        self.device = self._resolve_device(device)
        self.sentence_model: SentenceTransformer | None = None
        self.tokenizer: Any = None
        self.auto_model: Any = None

        load_started_at = time.perf_counter()
        logger.info(
            "加载本地Embedding模型: loaded=%s path=%s device=%s batch_size=%s dimension=%s",
            False,
            self.model_path,
            self.device,
            self.batch_size,
            self.dimension,
        )
        try:
            self.sentence_model = SentenceTransformer(str(self.model_path), device=self.device, trust_remote_code=True)
        except Exception:
            logger.exception("sentence-transformers加载失败，回退到transformers: path=%s", self.model_path)
            self._load_transformers_model_with_fallback()
        logger.info(
            "本地Embedding模型加载完成: loaded=%s path=%s backend=%s device=%s dimension=%s elapsed_ms=%s",
            self.is_loaded,
            self.model_path,
            self.backend_name,
            self.device,
            self.dimension,
            int((time.perf_counter() - load_started_at) * 1000),
        )

    @property
    def is_loaded(self) -> bool:
        """
        判断模型权重是否已经加载到当前进程。

        返回:
            True 表示后续请求会复用内存中的模型实例。
        """

        return self.sentence_model is not None or self.auto_model is not None

    @property
    def backend_name(self) -> str:
        """
        获取当前推理后端名称。

        返回:
            sentence-transformers 或 transformers。
        """

        if self.sentence_model is not None:
            return "sentence-transformers"
        return "transformers"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        批量生成文本向量。

        参数:
            texts: 待向量化文本列表。

        返回:
            与输入顺序一致的向量列表。
        """

        if not texts:
            return []

        started_at = time.perf_counter()
        try:
            if self.sentence_model is not None:
                vectors = self._embed_with_sentence_transformer(texts)
            else:
                vectors = self._embed_with_transformers(texts)
        except RuntimeError as exc:
            if not self._is_cuda_oom(exc):
                raise
            logger.exception("本地Embedding显存不足，尝试降低批量并切换CPU: device=%s batch_size=%s", self.device, self.batch_size)
            self.batch_size = max(1, self.batch_size // 2)
            if self.device == "cuda":
                self._fallback_to_cpu()
            if self.sentence_model is not None:
                vectors = self._embed_with_sentence_transformer(texts)
            else:
                vectors = self._embed_with_transformers(texts)
        vector_dimension = len(vectors[0]) if vectors else self.dimension
        logger.info(
            "本地Embedding调用完成: loaded=%s path=%s backend=%s device=%s count=%s batch_size=%s dimension=%s elapsed_ms=%s",
            self.is_loaded,
            self.model_path,
            self.backend_name,
            self.device,
            len(texts),
            self.batch_size,
            vector_dimension,
            int((time.perf_counter() - started_at) * 1000),
        )
        return vectors

    def _load_transformers_model_with_fallback(self) -> None:
        """
        加载 transformers 回退模型。

        说明:
            CUDA 加载失败且异常属于显存不足时，自动清理显存并改用 CPU。
        """

        try:
            self._load_transformers_model()
        except RuntimeError as exc:
            if self.device == "cuda" and self._is_cuda_oom(exc):
                logger.exception("transformers加载本地Embedding时显存不足，回退CPU: path=%s", self.model_path)
                self.device = "cpu"
                self._clear_cuda_cache()
                self._load_transformers_model()
                return
            raise

    def _load_transformers_model(self) -> None:
        """
        使用 transformers 加载本地模型。

        返回:
            None。加载失败时向上抛出异常，由业务层记录并返回标准错误。
        """

        self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_path), trust_remote_code=True)
        self.auto_model = AutoModel.from_pretrained(str(self.model_path), trust_remote_code=True).to(self.device)
        self.auto_model.eval()

    def _embed_with_sentence_transformer(self, texts: list[str]) -> list[list[float]]:
        """
        使用 sentence-transformers 生成向量。

        参数:
            texts: 待向量化文本列表。

        返回:
            已修正到目标维度的归一化向量列表。
        """

        vectors = self.sentence_model.encode(  # type: ignore[union-attr]
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [self._resize(vector.tolist()) for vector in vectors]

    @torch.inference_mode()
    def _embed_with_transformers(self, texts: list[str]) -> list[list[float]]:
        """
        使用 transformers AutoModel 生成向量。

        参数:
            texts: 待向量化文本列表。

        返回:
            已修正到目标维度的归一化向量列表。
        """

        vectors: list[list[float]] = []
        for start_index in range(0, len(texts), self.batch_size):
            # Qwen3-Embedding 的 sentence-transformers 配置使用 last-token pooling。
            batch_texts = texts[start_index : start_index + self.batch_size]
            encoded = self.tokenizer(  # type: ignore[operator]
                batch_texts,
                padding=True,
                truncation=True,
                max_length=4096,
                return_tensors="pt",
            ).to(self.device)
            output = self.auto_model(**encoded)  # type: ignore[misc]
            hidden = output.last_hidden_state
            attention_mask = encoded["attention_mask"]
            sequence_lengths = attention_mask.sum(dim=1) - 1
            batch_index = torch.arange(hidden.size(0), device=hidden.device)
            pooled = hidden[batch_index, sequence_lengths]
            pooled = F.normalize(pooled[:, : self.dimension], p=2, dim=1)
            vectors.extend(self._resize(vector) for vector in pooled.detach().cpu().float().tolist())
        return vectors

    def _resize(self, vector: list[float]) -> list[float]:
        """
        修正向量维度。

        参数:
            vector: 模型原始输出向量。

        返回:
            长度等于 EMBEDDING_DIM 的向量。
        """

        if len(vector) == self.dimension:
            return vector
        if len(vector) > self.dimension:
            return vector[: self.dimension]
        return vector + [0.0] * (self.dimension - len(vector))

    def _fallback_to_cpu(self) -> None:
        """
        将本地模型切换到 CPU。

        说明:
            显存不足时释放 CUDA 缓存，并尽量复用已加载模型，保障服务继续可用。
        """

        self.device = "cpu"
        self._clear_cuda_cache()
        if self.sentence_model is not None:
            self.sentence_model = SentenceTransformer(str(self.model_path), device="cpu", trust_remote_code=True)
            return
        if self.auto_model is not None:
            self.auto_model = self.auto_model.to("cpu")

    def _resolve_device(self, requested_device: str) -> str:
        """
        解析推理设备。

        参数:
            requested_device: 配置中的设备名。

        返回:
            实际使用的设备名。
        """

        normalized_device = requested_device.lower().strip()
        if normalized_device == "cuda":
            if torch.cuda.is_available() and self._cuda_smoke_test():
                return "cuda"
            logger.warning("配置请求CUDA但当前环境不可用，自动回退CPU")
        return "cpu"

    def _cuda_smoke_test(self) -> bool:
        """
        执行最小 CUDA 可用性测试。

        返回:
            True 表示当前 PyTorch CUDA 运行时可执行基础算子。
        """

        try:
            device = torch.device("cuda")
            tensor = torch.tensor([1], device=device)
            _ = tensor + 1
            torch.cuda.synchronize()
            return True
        except Exception:
            logger.exception("CUDA基础可用性测试失败")
            return False

    def _is_cuda_oom(self, exc: RuntimeError) -> bool:
        """
        判断异常是否为 CUDA 显存不足。

        参数:
            exc: RuntimeError 异常对象。

        返回:
            True 表示异常与 CUDA 显存不足相关。
        """

        message = str(exc).lower()
        return "cuda" in message and ("out of memory" in message or "memory" in message)

    def _clear_cuda_cache(self) -> None:
        """
        清理 CUDA 缓存。

        返回:
            None。没有 CUDA 时直接跳过。
        """

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _resolve_model_path(self, model_name: str) -> Path:
        """
        解析本地模型路径。

        参数:
            model_name: EMBEDDING_MODEL 配置值。

        返回:
            已存在的模型目录路径。
        """

        model_path = Path(model_name)
        if model_path.exists():
            return model_path
        raise FileNotFoundError(f"Embedding model path does not exist: {model_name}")


def get_local_embedding(model_name: str, device: str, batch_size: int, dimension: int) -> LocalQwenEmbedding:
    """
    获取本地 Embedding 单例。

    参数:
        model_name: 本地模型路径。
        device: 推理设备。
        batch_size: 推理批量大小。
        dimension: 输出向量维度。

    返回:
        LocalQwenEmbedding 实例。
    """

    cache_key = _build_cache_key(model_name, device, batch_size, dimension)
    with _LOCAL_EMBEDDING_CACHE_LOCK:
        cached_embedding = _LOCAL_EMBEDDING_CACHE.get(cache_key)
        if cached_embedding is not None:
            logger.info(
                "本地Embedding模型缓存命中: loaded=%s path=%s device=%s dimension=%s",
                cached_embedding.is_loaded,
                cached_embedding.model_path,
                cached_embedding.device,
                cached_embedding.dimension,
            )
            return cached_embedding

        logger.info(
            "本地Embedding模型缓存未命中，开始加载: loaded=%s model=%s requested_device=%s batch_size=%s dimension=%s",
            False,
            model_name,
            device,
            max(1, batch_size),
            dimension,
        )
        started_at = time.perf_counter()
        local_embedding = LocalQwenEmbedding(model_name=model_name, device=device, batch_size=batch_size, dimension=dimension)
        _LOCAL_EMBEDDING_CACHE[cache_key] = local_embedding
        logger.info(
            "本地Embedding模型已写入单例缓存: loaded=%s path=%s device=%s dimension=%s elapsed_ms=%s",
            local_embedding.is_loaded,
            local_embedding.model_path,
            local_embedding.device,
            local_embedding.dimension,
            int((time.perf_counter() - started_at) * 1000),
        )
        return local_embedding


def is_local_embedding_loaded(model_name: str, device: str, batch_size: int, dimension: int) -> bool:
    """
    查询本地 Embedding 模型是否已经在当前进程缓存。

    参数:
        model_name: 本地模型路径。
        device: 推理设备。
        batch_size: 推理批量大小。
        dimension: 输出向量维度。

    返回:
        True 表示同一进程后续调用会复用已加载模型。
    """

    cache_key = _build_cache_key(model_name, device, batch_size, dimension)
    with _LOCAL_EMBEDDING_CACHE_LOCK:
        cached_embedding = _LOCAL_EMBEDDING_CACHE.get(cache_key)
        return bool(cached_embedding and cached_embedding.is_loaded)


def _build_cache_key(model_name: str, device: str, batch_size: int, dimension: int) -> LocalEmbeddingCacheKey:
    """
    构造本地模型单例缓存键。

    说明:
        同一进程内相同模型、设备、批量和维度只加载一次，避免请求级重复加载。
    """

    return (model_name, device.lower().strip(), max(1, batch_size), dimension)
