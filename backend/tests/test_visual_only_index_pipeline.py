from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.document import Document
from app.models.document_asset import DocumentAsset
from app.models.page_index import DocumentPage, IndexPublicationManifest
from app.services.index_pipeline_service import IndexPipelineService


class _VisualEmbeddingResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "index_generation": "vl-2026-07",
            "dimension": 2,
            "distance_metric": "COSINE",
            "data": [{"index": 0, "embedding": [0.1, 0.2]}],
        }


def test_visual_only_document_builds_and_publishes_without_text_chunks(tmp_path: Path, monkeypatch) -> None:
    """零 Chunk 文档可凭 ready 视觉资产完成版本级原子发布。"""

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    image_path = tmp_path / "drawing-page-1.png"
    image_path.write_bytes(b"visual-page")

    with Session(engine) as db:
        document = Document(
            knowledge_base_id=1,
            knowledge_type="base",
            file_name="drawing.pdf",
            file_type="pdf",
            file_size=100,
            storage_path="storage/uploads/drawing.pdf",
            review_status="approved",
            index_status="indexing",
            version_no=1,
        )
        db.add(document)
        db.flush()
        page = DocumentPage(
            knowledge_base_id=1,
            document_id=document.id,
            version_no=1,
            page_no=1,
            page_text="",
            index_admission_status="visual_indexed",
        )
        db.add(page)
        db.flush()
        db.add(
            DocumentAsset(
                document_id=document.id,
                version_no=1,
                page_id=page.id,
                asset_type="page_preview",
                file_name=image_path.name,
                mime_type="image/png",
                storage_path=str(image_path),
                file_size=image_path.stat().st_size,
                status="ready",
                metadata_json=json.dumps(
                    {
                        "source_file_name": "drawing.pdf",
                        "visual_admission": {
                            "status": "accepted",
                            "category": "generic_visual",
                            "priority_score": 140,
                        },
                    },
                    ensure_ascii=False,
                ),
            )
        )
        second_image_path = tmp_path / "drawing-page-1-logo.png"
        second_image_path.write_bytes(b"visual-logo")
        db.add(
            DocumentAsset(
                document_id=document.id,
                version_no=1,
                page_id=page.id,
                asset_type="block_image",
                file_name=second_image_path.name,
                mime_type="image/png",
                storage_path=str(second_image_path),
                file_size=second_image_path.stat().st_size,
                status="ready",
                metadata_json=json.dumps(
                    {
                        "source_file_name": "drawing.pdf",
                        "visual_admission": {
                            "status": "rejected",
                            "category": "excluded",
                            "priority_score": 0,
                        },
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()

        service = IndexPipelineService(db)
        service.settings = SimpleNamespace(
            visual_index_enabled=True,
            milvus_enabled=False,
            visual_embedding_api_base="http://model-service:8890",
            model_service_api_base="http://model-service:8890",
            visual_embedding_api_key=None,
            model_service_api_key=None,
            visual_embedding_model="Qwen3-VL-Embedding-2B",
            visual_embedding_dim=2,
            visual_embedding_timeout_seconds=12,
            visual_embedding_batch_size=4,
            visual_index_generation="vl-2026-07",
            visual_embedding_distance_metric="COSINE",
            resolve_local_path=lambda value: Path(value),
        )
        monkeypatch.setattr(
            "app.services.visual_embedding_service.requests.post",
            lambda *args, **kwargs: _VisualEmbeddingResponse(),
        )
        monkeypatch.setattr(
            "app.knowledge.indexing.visual_milvus_indexer.VisualMilvusIndexer.upsert",
            lambda self, records: {"status": "indexed", "vector_count": len(records)},
        )

        result = service.build_all(document, publish=True)

        manifest = db.scalar(select(IndexPublicationManifest))
        assert result["milvus"]["skipped"] is True
        assert result["page_index"] == {"skipped": True, "reason": "visual_only"}
        assert result["visual"]["vector_count"] == 1
        assert result["publish"]["published"] is True
        assert result["publish"]["coverage"] == 1.0
        assert manifest is not None
        assert manifest.status == "published"
