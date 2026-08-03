"""
Independent Embedding/Reranker Model Service

负责：
1. 在独立进程中常驻加载本地 Embedding 与 Reranker 模型。
2. 为 API / Worker 提供内部 HTTP 推理接口。
3. 用进程级并发闸门控制 GPU 推理并发，避免显存峰值失控。
"""

from __future__ import annotations

import logging
import base64
import io
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.config import get_settings


def configure_logging() -> None:
    """配置模型服务日志。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()
_INFERENCE_GATE = BoundedSemaphore(max(1, int(settings.model_service_max_concurrency or 1)))

app = FastAPI(
    title="Botree Model Service",
    description="Internal Embedding/Reranker model service for Botree Knowledge OS",
    version="0.1.0",
)


class EmbeddingRequest(BaseModel):
    """OpenAI-compatible Embedding 请求。"""

    model: str | None = None
    input: str | list[str]
    dimensions: int | None = None


class EmbeddingResponseItem(BaseModel):
    """单条 Embedding 响应。"""

    object: str = "embedding"
    index: int
    embedding: list[float]


class EmbeddingResponse(BaseModel):
    """OpenAI-compatible Embedding 响应。"""

    object: str = "list"
    model: str
    data: list[EmbeddingResponseItem]


class VisualEmbeddingResponse(EmbeddingResponse):
    """携带视觉索引兼容性约束的 Embedding 响应。"""

    index_generation: str
    dimension: int
    distance_metric: str


class VisualEmbeddingInput(BaseModel):
    """视觉 Embedding 的文本或图片输入，二者必须且只能提供一种。"""

    text: str | None = None
    image_base64: str | None = None
    mime_type: str | None = None


class VisualEmbeddingRequest(BaseModel):
    model: str | None = None
    input: list[VisualEmbeddingInput]
    dimensions: int | None = None


class RerankRequest(BaseModel):
    """Reranker 请求。"""

    model: str | None = None
    query: str
    documents: list[str] = Field(default_factory=list)
    top_n: int | None = None


class RerankResult(BaseModel):
    """单条 Reranker 结果。"""

    index: int
    score: float


class RerankResponse(BaseModel):
    """Reranker 响应。"""

    model: str
    backend: str
    device: str
    results: list[RerankResult]


def _configured_embedding_model() -> str:
    model_name = str(settings.model_service_embedding_model or settings.embedding_model or "").strip()
    if not model_name:
        raise HTTPException(status_code=500, detail="MODEL_SERVICE_EMBEDDING_MODEL 未配置")
    return model_name


def _configured_reranker_model() -> str:
    model_name = str(settings.model_service_reranker_model or settings.reranker_model or "").strip()
    if not model_name:
        raise HTTPException(status_code=500, detail="MODEL_SERVICE_RERANKER_MODEL 未配置")
    return model_name


def _configured_embedding_dimension() -> int:
    return int(settings.model_service_embedding_dimension or settings.embedding_dim)


def _configured_embedding_device() -> str:
    """获取并校验文本 Embedding 的 GPU 设备。"""

    device = str(settings.model_service_embedding_device or "").strip().lower()
    if not (device == "cuda" or device.startswith("cuda:")):
        raise HTTPException(status_code=500, detail="文本 Embedding 必须使用 GPU")
    return device


def _configured_visual_embedding_model() -> str:
    model_name = str(settings.visual_embedding_model or "").strip()
    if not model_name:
        raise HTTPException(status_code=500, detail="VISUAL_EMBEDDING_MODEL 未配置")
    return model_name


def _configured_visual_embedding_device() -> str:
    """获取视觉模型独立的推理设备，兼容旧配置回退到 Embedding 设备。"""

    return str(
        getattr(settings, "model_service_visual_embedding_device", None)
        or settings.model_service_embedding_device
    )


def _configured_visual_embedding_batch_size() -> int:
    """获取视觉模型独立的推理批量，兼容旧配置回退到 Embedding 批量。"""

    return max(
        1,
        int(
            getattr(settings, "model_service_visual_embedding_batch_size", 0)
            or settings.model_service_embedding_batch_size
        ),
    )


def _authorize(request: Request) -> None:
    expected_api_key = str(settings.model_service_api_key or "").strip()
    if not expected_api_key:
        return
    authorization = request.headers.get("authorization") or ""
    if authorization != f"Bearer {expected_api_key}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid model service API key")


def _normalize_text_input(value: str | list[str]) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _validate_model_name(request_model: str | None, configured_model: str) -> None:
    if not request_model:
        return
    normalized_request = request_model.strip()
    if normalized_request == configured_model:
        return
    if Path(normalized_request).name == Path(configured_model).name:
        return
    raise HTTPException(
        status_code=400,
        detail=f"请求模型与模型服务配置不一致: requested={request_model} configured={configured_model}",
    )


@contextmanager
def _inference_slot():
    _INFERENCE_GATE.acquire()
    try:
        yield
    finally:
        _INFERENCE_GATE.release()


@app.get("/health")
def health() -> dict[str, Any]:
    """返回模型服务健康状态与当前进程缓存状态。"""

    from app.services.embedding_local import is_local_embedding_loaded
    from app.services.reranker_local import is_local_reranker_loaded

    embedding_model = _configured_embedding_model()
    reranker_model = _configured_reranker_model()
    return {
        "status": "ok",
        "model_service_enabled": settings.model_service_enabled,
        "embedding": {
            "model": embedding_model,
            "device": _configured_embedding_device(),
            "batch_size": settings.model_service_embedding_batch_size,
            "dimension": _configured_embedding_dimension(),
            "loaded": is_local_embedding_loaded(
                embedding_model,
                _configured_embedding_device(),
                settings.model_service_embedding_batch_size,
                _configured_embedding_dimension(),
            ),
        },
        "reranker": {
            "model": reranker_model,
            "device": settings.model_service_reranker_device,
            "batch_size": settings.model_service_reranker_batch_size,
            "loaded": is_local_reranker_loaded(
                reranker_model,
                settings.model_service_reranker_device,
                settings.model_service_reranker_batch_size,
            ),
        },
        "visual_embedding": {
            "model": _configured_visual_embedding_model() if settings.visual_embedding_model else None,
            "device": _configured_visual_embedding_device(),
            "batch_size": _configured_visual_embedding_batch_size(),
        },
        "max_concurrency": max(1, int(settings.model_service_max_concurrency or 1)),
    }


@app.post("/embeddings", response_model=EmbeddingResponse)
def create_embeddings(request: Request, payload: EmbeddingRequest) -> EmbeddingResponse:
    """生成文本向量。"""

    _authorize(request)
    configured_model = _configured_embedding_model()
    _validate_model_name(payload.model, configured_model)
    dimension = _configured_embedding_dimension()
    if payload.dimensions is not None and int(payload.dimensions) != dimension:
        raise HTTPException(
            status_code=400,
            detail=f"Embedding维度与模型服务配置不一致: requested={payload.dimensions} configured={dimension}",
        )

    texts = _normalize_text_input(payload.input)
    started_at = time.perf_counter()
    from app.services.embedding_local import get_local_embedding

    with _inference_slot():
        model = get_local_embedding(
            configured_model,
            _configured_embedding_device(),
            settings.model_service_embedding_batch_size,
            dimension,
        )
        vectors = model.embed_texts(texts)
    if len(vectors) != len(texts):
        raise HTTPException(status_code=502, detail=f"Embedding返回数量不匹配: expected={len(texts)} actual={len(vectors)}")
    logger.info(
        "模型服务Embedding调用完成: model=%s count=%s device=%s elapsed_ms=%s",
        configured_model,
        len(texts),
        getattr(model, "device", _configured_embedding_device()),
        int((time.perf_counter() - started_at) * 1000),
    )
    return EmbeddingResponse(
        model=configured_model,
        data=[EmbeddingResponseItem(index=index, embedding=vector) for index, vector in enumerate(vectors)],
    )


@app.post("/rerank", response_model=RerankResponse)
def rerank(request: Request, payload: RerankRequest) -> RerankResponse:
    """对候选文本执行重排打分。"""

    _authorize(request)
    configured_model = _configured_reranker_model()
    _validate_model_name(payload.model, configured_model)
    documents = [str(document) for document in payload.documents]
    if not documents:
        return RerankResponse(
            model=configured_model,
            backend="model_service",
            device=settings.model_service_reranker_device,
            results=[],
        )

    started_at = time.perf_counter()
    from app.services.reranker_local import get_local_reranker

    with _inference_slot():
        model = get_local_reranker(
            configured_model,
            settings.model_service_reranker_device,
            settings.model_service_reranker_batch_size,
        )
        scores = model.predict(payload.query, documents)
    if len(scores) != len(documents):
        raise HTTPException(status_code=502, detail=f"Reranker返回数量不匹配: expected={len(documents)} actual={len(scores)}")

    results = [RerankResult(index=index, score=float(score)) for index, score in enumerate(scores)]
    results.sort(key=lambda item: item.score, reverse=True)
    if payload.top_n is not None:
        results = results[: max(0, int(payload.top_n))]
    logger.info(
        "模型服务Reranker调用完成: model=%s count=%s device=%s elapsed_ms=%s",
        configured_model,
        len(documents),
        getattr(model, "device", settings.model_service_reranker_device),
        int((time.perf_counter() - started_at) * 1000),
    )
    return RerankResponse(
        model=configured_model,
        backend="model_service",
        device=getattr(model, "device", settings.model_service_reranker_device),
        results=results,
    )


@app.post("/visual-embeddings", response_model=VisualEmbeddingResponse)
def create_visual_embeddings(request: Request, payload: VisualEmbeddingRequest) -> VisualEmbeddingResponse:
    """使用 Qwen3-VL-Embedding 生成图文对齐向量。"""

    from PIL import Image
    from app.services.visual_embedding_local import get_local_visual_embedding

    _authorize(request)
    configured_model = _configured_visual_embedding_model()
    _validate_model_name(payload.model, configured_model)
    dimension = int(payload.dimensions or settings.visual_embedding_dim)
    if dimension != settings.visual_embedding_dim:
        raise HTTPException(status_code=400, detail="视觉 Embedding 维度与服务配置不一致")
    inputs: list[Any] = []
    for item in payload.input:
        if bool(item.text) == bool(item.image_base64):
            raise HTTPException(status_code=400, detail="视觉 Embedding 输入必须且只能包含 text 或 image_base64")
        if item.text is not None:
            inputs.append(item.text)
            continue
        try:
            raw = base64.b64decode(item.image_base64 or "", validate=True)
            image = Image.open(io.BytesIO(raw))
            image.load()
            inputs.append(image.convert("RGB"))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="视觉 Embedding 图片数据无效") from exc
    with _inference_slot():
        model = get_local_visual_embedding(
            configured_model,
            _configured_visual_embedding_device(),
            _configured_visual_embedding_batch_size(),
            dimension,
        )
        vectors = model.encode(inputs)
    return VisualEmbeddingResponse(
        model=configured_model,
        index_generation=settings.visual_index_generation,
        dimension=dimension,
        distance_metric=settings.visual_embedding_distance_metric,
        data=[EmbeddingResponseItem(index=index, embedding=vector) for index, vector in enumerate(vectors)],
    )


@app.on_event("startup")
def warmup_models() -> None:
    """按配置在模型服务启动时预热本地模型。"""

    if not settings.model_service_warmup_on_startup:
        logger.info("跳过模型服务启动预热: MODEL_SERVICE_WARMUP_ON_STARTUP=false")
        return
    try:
        from app.services.embedding_local import get_local_embedding

        get_local_embedding(
            _configured_embedding_model(),
            _configured_embedding_device(),
            settings.model_service_embedding_batch_size,
            _configured_embedding_dimension(),
        )
        logger.info("模型服务Embedding预热完成")
    except Exception:
        logger.exception("模型服务Embedding预热失败")
        raise
    try:
        from app.services.reranker_local import get_local_reranker

        get_local_reranker(
            _configured_reranker_model(),
            settings.model_service_reranker_device,
            settings.model_service_reranker_batch_size,
        )
        logger.info("模型服务Reranker预热完成")
    except Exception:
        logger.exception("模型服务Reranker预热失败，继续提供Embedding服务")
    if not str(settings.visual_embedding_model or "").strip():
        logger.info("跳过视觉Embedding预热: VISUAL_EMBEDDING_MODEL未配置")
        return
    try:
        from app.services.visual_embedding_local import get_local_visual_embedding

        # 仅加载权重不足以验证处理器与输出维度；执行一次最小文本编码，
        # 让部署在进入就绪状态前即暴露模型或契约错误。
        visual_model = get_local_visual_embedding(
            _configured_visual_embedding_model(),
            _configured_visual_embedding_device(),
            _configured_visual_embedding_batch_size(),
            settings.visual_embedding_dim,
        )
        vectors = visual_model.encode(["visual embedding warmup"])
        if len(vectors) != 1 or len(vectors[0]) != settings.visual_embedding_dim:
            raise ValueError(
                f"视觉Embedding预热维度不一致: expected={settings.visual_embedding_dim} "
                f"actual={len(vectors[0]) if vectors else 0}"
            )
        logger.info("模型服务视觉Embedding预热完成: dimension=%s", settings.visual_embedding_dim)
    except Exception:
        logger.exception("模型服务视觉Embedding预热失败")
        raise
