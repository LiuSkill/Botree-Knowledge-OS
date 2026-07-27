from pathlib import Path

import pytest

from app.knowledge.indexing.visual_index_service import (
    VisualIndexAsset,
    VisualIndexService,
)
from app.services.visual_embedding_service import VisualEmbeddingService
from app.core.exceptions import AppException


class RecordingVisualEmbeddingClient:
    def embed_images(self, image_paths: list[Path]) -> list[list[float]]:
        return [[float(index), 1.0] for index, _ in enumerate(image_paths, start=1)]


class RecordingVisualIndexer:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def upsert(self, records: list[dict[str, object]]) -> dict[str, object]:
        self.records.extend(records)
        return {"status": "indexed", "vector_count": len(records)}


def test_visual_only_page_builds_page_and_region_records(tmp_path: Path) -> None:
    page_image = tmp_path / "page-1.png"
    region_image = tmp_path / "page-1-region-2.png"
    page_image.write_bytes(b"page")
    region_image.write_bytes(b"region")
    indexer = RecordingVisualIndexer()
    service = VisualIndexService(RecordingVisualEmbeddingClient(), indexer)

    result = service.build_records(
        [
            VisualIndexAsset(
                asset_id=11,
                asset_type="page_preview",
                image_path=page_image,
                knowledge_base_id=3,
                project_id=None,
                document_id=7,
                version_no=2,
                page_id=101,
                page_no=1,
                block_id=None,
                block_index=None,
                security_level="internal",
            ),
            VisualIndexAsset(
                asset_id=12,
                asset_type="block_image",
                image_path=region_image,
                knowledge_base_id=3,
                project_id=None,
                document_id=7,
                version_no=2,
                page_id=101,
                page_no=1,
                block_id=202,
                block_index=2,
                security_level="internal",
                previous_block_id=201,
                next_block_id=203,
            ),
        ],
        index_generation="vl-2026-07",
        publication_token="token-1",
    )

    assert result == {"status": "indexed", "vector_count": 2}
    assert indexer.records == [
        {
            "id": "visual:11",
            "asset_id": 11,
            "asset_type": "page_preview",
            "knowledge_base_id": 3,
            "project_id": 0,
            "document_id": 7,
            "version_no": 2,
            "page_id": 101,
            "page_no": 1,
            "block_id": 0,
            "block_index": -1,
            "previous_block_id": 0,
            "next_block_id": 0,
            "security_level": "internal",
            "index_generation": "vl-2026-07",
            "publication_token": "token-1",
            "embedding": [1.0, 1.0],
        },
        {
            "id": "visual:12",
            "asset_id": 12,
            "asset_type": "block_image",
            "knowledge_base_id": 3,
            "project_id": 0,
            "document_id": 7,
            "version_no": 2,
            "page_id": 101,
            "page_no": 1,
            "block_id": 202,
            "block_index": 2,
            "previous_block_id": 201,
            "next_block_id": 203,
            "security_level": "internal",
            "index_generation": "vl-2026-07",
            "publication_token": "token-1",
            "embedding": [2.0, 1.0],
        },
    ]


def test_visual_embedding_service_sends_images_to_isolated_model_service(tmp_path: Path, monkeypatch) -> None:
    image_path = tmp_path / "drawing.png"
    image_path.write_bytes(b"png-bytes")
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "index_generation": "vl-2026-07",
                "dimension": 2,
                "distance_metric": "COSINE",
                "data": [{"index": 0, "embedding": [0.1, 0.2]}],
            }

    def fake_post(url: str, headers: dict[str, str], json: dict[str, object], timeout: float) -> Response:  # noqa: A002
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr("app.services.visual_embedding_service.requests.post", fake_post)
    service = VisualEmbeddingService(
        api_base="http://model-service:8890",
        api_key="secret",
        model_name="Qwen3-VL-Embedding-2B",
        dimension=2,
        timeout_seconds=12,
        index_generation="vl-2026-07",
        distance_metric="COSINE",
    )

    vectors = service.embed_images([image_path])

    assert vectors == [[0.1, 0.2]]
    assert captured["url"] == "http://model-service:8890/visual-embeddings"
    assert captured["headers"] == {"Authorization": "Bearer secret"}
    assert captured["json"] == {
        "model": "Qwen3-VL-Embedding-2B",
        "dimensions": 2,
        "input": [{"image_base64": "cG5nLWJ5dGVz", "mime_type": "image/png"}],
    }


def test_visual_embedding_service_rejects_incompatible_index_generation(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "index_generation": "stale-generation",
                "dimension": 2,
                "distance_metric": "COSINE",
                "data": [{"index": 0, "embedding": [0.1, 0.2]}],
            }

    monkeypatch.setattr(
        "app.services.visual_embedding_service.requests.post",
        lambda *args, **kwargs: Response(),
    )
    service = VisualEmbeddingService(
        api_base="http://model-service:8890",
        api_key=None,
        model_name="Qwen3-VL-Embedding-2B",
        dimension=2,
        timeout_seconds=12,
        index_generation="vl-2026-07",
        distance_metric="COSINE",
    )

    with pytest.raises(AppException, match="索引代际不兼容"):
        service.embed_queries(["换热器管口方向"])
