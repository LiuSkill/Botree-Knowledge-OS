from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models.base import Base  # noqa: E402
from app.models.model_config import ModelConfig  # noqa: E402
from app.retrieval.schemas import Evidence  # noqa: E402
from app.scripts import configure_model_service  # noqa: E402
from app.services.embedding_service import EmbeddingService, RuntimeEmbeddingConfig  # noqa: E402
from app.services.reranker_service import RerankerService, RuntimeRerankerConfig  # noqa: E402


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


def _make_evidence(content: str, score: float = 0.5) -> Evidence:
    return Evidence(
        score=score,
        source_type="project",
        knowledge_base_id=1,
        project_id=1,
        document_id=1,
        chunk_id=1,
        drawing_no="D-1",
        file_name="unit.md",
        page_number=1,
        content=content,
        retriever="milvus",
        metadata={"security_level": "public"},
    )


def test_embedding_model_service_request_uses_embedding_api_base(monkeypatch) -> None:
    service = object.__new__(EmbeddingService)
    service.settings = SimpleNamespace(embedding_timeout_seconds=5, embedding_dim=3)
    captured: dict[str, Any] = {}

    def fake_post(url: str, headers: dict[str, str], json: dict[str, Any], timeout: int):  # noqa: A002
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _FakeResponse(
            {
                "data": [
                    {"index": 1, "embedding": [0.4, 0.5, 0.6]},
                    {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                ]
            }
        )

    monkeypatch.setattr("app.services.embedding_service.requests.post", fake_post)

    vectors = service._request_embeddings(  # noqa: SLF001
        ["alpha", "beta"],
        RuntimeEmbeddingConfig(
            provider="model_service",
            model_name="Qwen3-Embedding-0.6B",
            api_base="http://botree-model-service:8890",
            api_key="secret",
        ),
    )

    assert captured["url"] == "http://botree-model-service:8890/embeddings"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["json"] == {
        "model": "Qwen3-Embedding-0.6B",
        "input": ["alpha", "beta"],
        "dimensions": 3,
    }
    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


def test_reranker_model_service_maps_scores_back_to_evidences(monkeypatch) -> None:
    service = RerankerService(None)
    service.settings = SimpleNamespace(reranker_timeout_seconds=5)
    runtime_config = RuntimeRerankerConfig(
        provider="model_service",
        model_name="bge-reranker-v2-m3",
        api_base="http://botree-model-service:8890",
        api_key=None,
    )
    captured: dict[str, Any] = {}

    def fake_post(url: str, headers: dict[str, str], json: dict[str, Any], timeout: float):  # noqa: A002, ARG001
        captured.update({"url": url, "json": json, "timeout": timeout})
        return _FakeResponse(
            {
                "backend": "model_service",
                "device": "cuda",
                "results": [
                    {"index": 1, "score": 0.91},
                    {"index": 0, "score": 0.23},
                ],
            }
        )

    monkeypatch.setattr("app.services.reranker_service.requests.post", fake_post)

    results = service._rerank_with_model_service(  # noqa: SLF001
        "项目参数",
        [_make_evidence("低相关", 0.4), _make_evidence("高相关", 0.5)],
        limit=2,
        score_order="desc",
        runtime_config=runtime_config,
    )

    assert captured["url"] == "http://botree-model-service:8890/rerank"
    assert captured["json"]["documents"] == ["低相关", "高相关"]
    assert [item.content for item in results] == ["高相关", "低相关"]
    assert results[0].metadata["rerank_backend"] == "model_service"
    assert results[0].metadata["rerank_model"] == "bge-reranker-v2-m3"
    assert results[0].metadata["rerank_resolved_device"] == "cuda"
    assert service.last_runtime["provider"] == "model_service"
    assert service.last_runtime["fallback_used"] is False


def test_configure_model_service_overwrites_existing_local_defaults(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    db = SessionLocal()
    try:
        db.add(
            ModelConfig(
                provider="local",
                model_name="/app/models/old-embedding",
                api_base=None,
                api_key=None,
                model_type="embedding",
                is_default=True,
                enabled=True,
            )
        )
        db.add(
            ModelConfig(
                provider="local",
                model_name="/app/models/old-reranker",
                api_base=None,
                api_key=None,
                model_type="reranker",
                is_default=True,
                enabled=True,
            )
        )
        db.commit()

        monkeypatch.setattr(
            configure_model_service,
            "get_settings",
            lambda: SimpleNamespace(
                model_service_enabled=True,
                embedding_model="/app/models/Qwen3-Embedding-0.6B",
                model_service_embedding_model=None,
                reranker_model="/app/models/bge-reranker-v2-m3",
                model_service_reranker_model=None,
                embedding_api_base="http://botree-model-service:8890",
                reranker_api_base="http://botree-model-service:8890",
                model_service_api_base="http://botree-model-service:8890",
                embedding_api_key=None,
                reranker_api_key=None,
                model_service_api_key=None,
            ),
        )

        configure_model_service.sync_model_service_configs(db)

        configs = {
            item.model_type: item
            for item in db.scalars(select(ModelConfig).where(ModelConfig.is_default.is_(True))).all()
        }
        assert configs["embedding"].provider == "model_service"
        assert configs["embedding"].api_base == "http://botree-model-service:8890"
        assert configs["reranker"].provider == "model_service"
        assert configs["reranker"].model_name == "/app/models/bge-reranker-v2-m3"
    finally:
        db.close()
