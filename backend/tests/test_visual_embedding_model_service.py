from __future__ import annotations

import base64
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.model_service import main as model_service


_ONE_PIXEL_PNG = base64.b64encode(
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
).decode("ascii")


class _AlignedVisualEmbedding:
    def encode(self, inputs: list[object]) -> list[list[float]]:
        return [[0.1, 0.2], [0.3, 0.4]][: len(inputs)]


def test_startup_warmup_loads_and_encodes_visual_model(monkeypatch) -> None:
    encoded_inputs: list[object] = []

    class _WarmVisualEmbedding:
        def encode(self, inputs: list[object]) -> list[list[float]]:
            encoded_inputs.extend(inputs)
            return [[0.1, 0.2]]

    monkeypatch.setattr(
        model_service,
        "settings",
        SimpleNamespace(
            model_service_warmup_on_startup=True,
            model_service_embedding_model="text-model",
            embedding_model="text-model",
            model_service_embedding_device="cpu",
            model_service_embedding_batch_size=2,
            model_service_embedding_dimension=2,
            embedding_dim=2,
            model_service_reranker_model="reranker-model",
            reranker_model="reranker-model",
            model_service_reranker_device="cpu",
            model_service_reranker_batch_size=2,
            visual_embedding_model="visual-model",
            visual_embedding_dim=2,
        ),
    )
    monkeypatch.setattr("app.services.embedding_local.get_local_embedding", lambda *args: object())
    monkeypatch.setattr("app.services.reranker_local.get_local_reranker", lambda *args: object())
    monkeypatch.setattr(
        "app.services.visual_embedding_local.get_local_visual_embedding",
        lambda *args: _WarmVisualEmbedding(),
    )

    model_service.warmup_models()

    assert encoded_inputs == ["visual embedding warmup"]


def test_visual_embedding_response_declares_compatible_index_generation(monkeypatch) -> None:
    """查询端必须能从响应判断向量是否与已发布视觉索引兼容。"""

    monkeypatch.setattr(
        model_service,
        "settings",
        SimpleNamespace(
            model_service_api_key=None,
            visual_embedding_model="Qwen3-VL-Embedding-2B",
            visual_embedding_dim=2,
            visual_index_generation="vl-2026-07",
            visual_embedding_distance_metric="COSINE",
            model_service_embedding_device="cpu",
            model_service_embedding_batch_size=2,
        ),
    )
    monkeypatch.setattr(
        "app.services.visual_embedding_local.get_local_visual_embedding",
        lambda *args: _AlignedVisualEmbedding(),
    )

    response = TestClient(model_service.app).post(
        "/visual-embeddings",
        json={
            "model": "Qwen3-VL-Embedding-2B",
            "dimensions": 2,
            "input": [
                {"text": "换热器管口方向"},
                {"image_base64": _ONE_PIXEL_PNG, "mime_type": "image/png"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "model": "Qwen3-VL-Embedding-2B",
        "index_generation": "vl-2026-07",
        "dimension": 2,
        "distance_metric": "COSINE",
        "data": [
            {"object": "embedding", "index": 0, "embedding": [0.1, 0.2]},
            {"object": "embedding", "index": 1, "embedding": [0.3, 0.4]},
        ],
    }
