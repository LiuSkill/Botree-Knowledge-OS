"""Qwen3-VL-Embedding 独立模型服务客户端。"""

from __future__ import annotations

import base64
import logging
import mimetypes
import time
from pathlib import Path
from typing import Any

import requests

from app.core.exceptions import AppException

logger = logging.getLogger(__name__)


class VisualEmbeddingService:
    """为文本问题与图片生成同一语义空间的向量。"""

    def __init__(
        self,
        api_base: str,
        api_key: str | None,
        model_name: str,
        dimension: int,
        timeout_seconds: float,
        index_generation: str,
        distance_metric: str,
        batch_size: int = 4,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.dimension = dimension
        self.timeout_seconds = timeout_seconds
        self.index_generation = index_generation
        self.distance_metric = distance_metric.upper()
        self.batch_size = max(1, int(batch_size))

    def embed_images(self, image_paths: list[Path]) -> list[list[float]]:
        vectors: list[list[float]] = []
        # 视觉推理耗时远高于文本；限制单次 HTTP 请求规模，避免大文档整批超过客户端超时。
        for start in range(0, len(image_paths), self.batch_size):
            inputs = []
            for image_path in image_paths[start : start + self.batch_size]:
                mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
                inputs.append(
                    {
                        "image_base64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
                        "mime_type": mime_type,
                    }
                )
            vectors.extend(self._request(inputs))
        return vectors

    def embed_queries(self, queries: list[str]) -> list[list[float]]:
        return self._request([{"text": query} for query in queries])

    def _request(self, inputs: list[dict[str, str]]) -> list[list[float]]:
        if not inputs:
            return []
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload: dict[str, Any] = {
            "model": self.model_name,
            "dimensions": self.dimension,
            "input": inputs,
        }
        started_at = time.perf_counter()
        try:
            response = requests.post(
                f"{self.api_base}/visual-embeddings",
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("index_generation") != self.index_generation:
                raise ValueError("视觉 Embedding 索引代际不兼容")
            if int(payload.get("dimension", 0)) != self.dimension:
                raise ValueError("视觉 Embedding 维度不兼容")
            if str(payload.get("distance_metric", "")).upper() != self.distance_metric:
                raise ValueError("视觉 Embedding 距离度量不兼容")
            items = sorted(payload.get("data", []), key=lambda item: int(item["index"]))
            vectors = [[float(value) for value in item["embedding"]] for item in items]
            if len(vectors) != len(inputs) or any(len(vector) != self.dimension for vector in vectors):
                raise ValueError("视觉 Embedding 数量或维度不匹配")
            logger.info(
                "视觉 Embedding 调用完成: model=%s count=%s dimension=%s elapsed_ms=%s",
                self.model_name,
                len(inputs),
                self.dimension,
                int((time.perf_counter() - started_at) * 1000),
            )
            return vectors
        except requests.Timeout as exc:
            if len(inputs) > 1:
                midpoint = len(inputs) // 2
                logger.warning(
                    "视觉 Embedding 批次超时，拆分后重试: model=%s count=%s left=%s right=%s elapsed_ms=%s",
                    self.model_name,
                    len(inputs),
                    midpoint,
                    len(inputs) - midpoint,
                    int((time.perf_counter() - started_at) * 1000),
                )
                return self._request(inputs[:midpoint]) + self._request(inputs[midpoint:])
            logger.exception("视觉 Embedding 单条请求超时: model=%s", self.model_name)
            raise AppException(f"视觉 Embedding 服务调用超时: {exc}", status_code=502, code=502) from exc
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            logger.exception("视觉 Embedding 调用失败: model=%s count=%s", self.model_name, len(inputs))
            raise AppException(f"视觉 Embedding 服务调用失败: {exc}", status_code=502, code=502) from exc
