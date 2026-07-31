import json
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.document import Document
from app.models.document_asset import DocumentAsset
from app.models.page_index import DocumentPage
from app.retrieval.retrievers.visual_retriever import VisualRetriever
from app.retrieval.router import RetrievalRouter


class QueryEmbeddingClient:
    def embed_queries(self, queries: list[str]) -> list[list[float]]:
        return [[0.3, 0.7] for _ in queries]


class VisualHitIndex:
    def search(self, query_vector: list[float], limit: int, expr: str | None = None) -> list[dict[str, object]]:
        return [
            {
                "asset_id": 31,
                "document_id": 7,
                "version_no": 2,
                "page_id": 21,
                "page_no": 4,
                "block_id": 0,
                "score": 0.88,
                "asset_type": "page_preview",
                "index_generation": "vl-2026-07",
                "publication_token": "token-1",
            }
        ]


def test_visual_retriever_recalls_page_without_text_chunk(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            Document(
                id=7,
                knowledge_base_id=3,
                knowledge_type="base",
                file_name="scan.pdf",
                file_type="pdf",
                storage_path="scan.pdf",
                version_no=2,
                review_status="approved",
                index_status="indexed",
                security_level="internal",
            )
        )
        db.add(
            DocumentPage(
                id=21,
                knowledge_base_id=3,
                document_id=7,
                version_no=2,
                page_no=4,
                page_text="",
                security_level="internal",
            )
        )
        image_path = tmp_path / "scan-page-4.png"
        image_path.write_bytes(b"image")
        db.add(
            DocumentAsset(
                id=31,
                document_id=7,
                version_no=2,
                page_id=21,
                asset_type="page_preview",
                file_name=image_path.name,
                mime_type="image/png",
                storage_backend="local",
                storage_path=str(image_path),
                file_size=5,
                status="ready",
                metadata_json=json.dumps(
                    {
                        "source_file_name": "scan.pdf",
                        "visual_admission": {
                            "status": "accepted",
                            "category": "flow_diagram",
                            "priority_score": 428,
                            "page_title": "浸出流程图",
                            "figure_title": "图2 一次浸出流程图",
                            "adjacent_texts": ["上游为配料段", "下游连接过滤段"],
                            "context_text": "scan.pdf | 浸出流程图 | 图2 一次浸出流程图 | 上游为配料段 | 下游连接过滤段",
                        },
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
        retriever = VisualRetriever(db, QueryEmbeddingClient(), VisualHitIndex())

        evidences = retriever.search(
            "流程中泵在哪里？",
            "base_only",
            None,
            SimpleNamespace(id=9, roles=[]),
            retrieval_scope={"document_ids": [7], "publication_tokens": ["token-1"]},
        )

    assert len(evidences) == 1
    assert evidences[0].retriever == "visual"
    assert evidences[0].chunk_id == -31
    assert evidences[0].page_number == 4
    assert evidences[0].content == "视觉证据：scan.pdf 第4页"
    assert evidences[0].assets[0].asset_id == 31
    assert evidences[0].metadata["index_generation"] == "vl-2026-07"
    assert evidences[0].metadata["visual_context"]["figure_title"] == "图2 一次浸出流程图"
    assert evidences[0].assets[0].metadata["visual_context"]["source_file_name"] == "scan.pdf"


def test_router_exposes_visual_retriever_when_visual_index_is_configured(monkeypatch) -> None:
    settings = SimpleNamespace(
        milvus_enabled=False,
        visual_index_enabled=True,
        visual_embedding_api_base="http://model-service:8890",
        model_service_api_base="http://model-service:8890",
        visual_embedding_api_key=None,
        model_service_api_key=None,
        visual_embedding_model="Qwen3-VL-Embedding-2B",
        visual_embedding_dim=2048,
        visual_embedding_timeout_seconds=60,
        visual_index_generation="qwen3-vl-embedding-2b-v1",
        visual_embedding_distance_metric="COSINE",
    )
    monkeypatch.setattr("app.retrieval.router.get_settings", lambda: settings)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        router = RetrievalRouter(db)

    assert "visual" in router.available_retrievers()
