"""Qwen3-VL-Embedding 本地推理，仅供独立模型服务进程使用。"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from threading import RLock
from typing import Any

import torch
import torch.nn.functional as F
from PIL import Image

logger = logging.getLogger(__name__)

_CACHE: dict[tuple[str, str, int, int], "LocalQwenVLVisualEmbedding"] = {}
_CACHE_LOCK = RLock()
_OFFICIAL_SCRIPT = "scripts/qwen3_vl_embedding.py"


def _resolve_official_script(model_name: str) -> Path:
    model_path = Path(model_name).expanduser()
    if model_path.is_dir():
        script_path = model_path / _OFFICIAL_SCRIPT
        if script_path.is_file():
            return script_path
        raise RuntimeError(f"Qwen3-VL-Embedding official inference script is missing: {script_path}")

    try:
        from huggingface_hub import hf_hub_download

        return Path(hf_hub_download(repo_id=model_name, filename=_OFFICIAL_SCRIPT))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Unable to load the official Qwen3-VL-Embedding inference script: model={model_name}"
        ) from exc


def _load_official_embedder_class(model_name: str) -> type[Any]:
    script_path = _resolve_official_script(model_name)
    module_name = f"_qwen3_vl_embedding_{abs(hash(script_path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import Qwen3-VL-Embedding inference script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    embedder_class = getattr(module, "Qwen3VLEmbedder", None)
    if embedder_class is None:
        raise RuntimeError(f"Qwen3VLEmbedder is missing from official inference script: {script_path}")
    return embedder_class


class LocalQwenVLVisualEmbedding:
    """使用 Qwen 官方适配器将文本与图片编码到统一向量空间。"""

    def __init__(self, model_name: str, device: str, batch_size: int, dimension: int) -> None:
        self.model_name = model_name
        self.device = device if device != "cuda" or torch.cuda.is_available() else "cpu"
        self.batch_size = max(1, batch_size)
        self.dimension = dimension

        embedder_class = _load_official_embedder_class(model_name)
        dtype = torch.float16 if self.device.startswith("cuda") else torch.float32
        self.model: Any = embedder_class(model_name_or_path=model_name, dtype=dtype)
        underlying_model = getattr(self.model, "model", None)
        if underlying_model is not None:
            underlying_model.to(self.device)

    @staticmethod
    def _prepare_input(item: Any) -> dict[str, Any]:
        if isinstance(item, str):
            return {"text": item}
        if isinstance(item, Image.Image):
            return {"image": item}
        raise TypeError(f"Unsupported visual embedding input type: {type(item).__name__}")

    def encode(self, inputs: list[Any]) -> list[list[float]]:
        if not inputs:
            return []

        encoded: list[list[float]] = []
        for start in range(0, len(inputs), self.batch_size):
            batch = [self._prepare_input(item) for item in inputs[start : start + self.batch_size]]
            vectors = self.model.process(batch)
            if vectors.ndim == 1:
                vectors = vectors.unsqueeze(0)
            if self.dimension > vectors.shape[1]:
                raise ValueError(
                    "Visual embedding dimension exceeds model output: "
                    f"requested={self.dimension} native={vectors.shape[1]}"
                )
            vectors = F.normalize(vectors[:, : self.dimension].float(), p=2, dim=1)
            encoded.extend(vectors.detach().cpu().tolist())
        return encoded


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
            logger.info(
                "Visual embedding model loaded: model=%s device=%s dimension=%s batch_size=%s backend=qwen_official",
                model_name,
                model.device,
                dimension,
                model.batch_size,
            )
        return model
