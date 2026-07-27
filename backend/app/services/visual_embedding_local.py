"""Qwen3-VL-Embedding 本地推理，仅供独立模型服务进程使用。"""

from __future__ import annotations

import logging
from threading import RLock
from typing import Any

import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)

_CACHE: dict[tuple[str, str, int, int], "LocalQwenVLVisualEmbedding"] = {}
_CACHE_LOCK = RLock()


class LocalQwenVLVisualEmbedding:
    """把文本与 PIL 图片编码到 Qwen3-VL 的统一向量空间。"""

    def __init__(self, model_name: str, device: str, batch_size: int, dimension: int) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.device = device if device != "cuda" or torch.cuda.is_available() else "cpu"
        self.batch_size = max(1, batch_size)
        self.dimension = dimension
        self.model: Any = SentenceTransformer(model_name, device=self.device, trust_remote_code=True)

    def encode(self, inputs: list[Any]) -> list[list[float]]:
        if not inputs:
            return []
        vectors = self.model.encode(
            inputs,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_tensor=True,
            show_progress_bar=False,
        )
        if vectors.ndim == 1:
            vectors = vectors.unsqueeze(0)
        if self.dimension > vectors.shape[1]:
            raise ValueError(f"视觉 Embedding 维度超过模型输出: requested={self.dimension} native={vectors.shape[1]}")
        vectors = F.normalize(vectors[:, : self.dimension], p=2, dim=1)
        return vectors.detach().cpu().float().tolist()


def get_local_visual_embedding(
    model_name: str,
    device: str,
    batch_size: int,
    dimension: int,
) -> LocalQwenVLVisualEmbedding:
    key = (model_name, device, max(1, batch_size), dimension)
    with _CACHE_LOCK:
        model = _CACHE.get(key)
        if model is None:
            model = LocalQwenVLVisualEmbedding(*key)
            _CACHE[key] = model
            logger.info("视觉 Embedding 模型加载完成: model=%s device=%s dimension=%s", model_name, model.device, dimension)
        return model
