"""独立视觉索引构建服务。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.core.exceptions import AppException

logger = logging.getLogger(__name__)


class VisualEmbeddingClient(Protocol):
    """隔离视觉模型进程的批量 Embedding 契约。"""

    def embed_images(self, image_paths: list[Path]) -> list[list[float]]: ...


class VisualVectorIndexer(Protocol):
    """独立视觉向量库写入契约。"""

    def upsert(self, records: list[dict[str, Any]]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class VisualIndexAsset:
    """一个可独立召回的整页或局部区域视觉资产。"""

    asset_id: int
    asset_type: str
    image_path: Path
    knowledge_base_id: int
    project_id: int | None
    document_id: int
    version_no: int
    page_id: int
    page_no: int
    block_id: int | None
    block_index: int | None
    security_level: str
    previous_block_id: int | None = None
    next_block_id: int | None = None


class VisualIndexService:
    """把派生图片转换为多粒度、可追溯的视觉索引记录。"""

    def __init__(self, embedding_client: VisualEmbeddingClient, indexer: VisualVectorIndexer) -> None:
        self.embedding_client = embedding_client
        self.indexer = indexer

    def build_records(
        self, assets: list[VisualIndexAsset], index_generation: str, publication_token: str
    ) -> dict[str, Any]:
        if not assets:
            return {"status": "skipped", "vector_count": 0}
        if not index_generation.strip():
            raise AppException("视觉索引代际不能为空", status_code=500, code=500)

        missing_paths = [str(asset.image_path) for asset in assets if not asset.image_path.is_file()]
        if missing_paths:
            raise AppException(
                f"视觉索引资产不存在: {missing_paths[:3]}",
                status_code=500,
                code=500,
            )

        started_at = time.perf_counter()
        vectors = self.embedding_client.embed_images([asset.image_path for asset in assets])
        if len(vectors) != len(assets):
            raise AppException("视觉 Embedding 返回数量与资产数量不一致", status_code=502, code=502)

        records = [
            self._to_record(asset, vector, index_generation, publication_token)
            for asset, vector in zip(assets, vectors, strict=True)
        ]
        result = self.indexer.upsert(records)
        logger.info(
            "视觉索引构建完成: asset_count=%s generation=%s status=%s elapsed_ms=%s",
            len(assets),
            index_generation,
            result.get("status"),
            int((time.perf_counter() - started_at) * 1000),
        )
        return result

    @staticmethod
    def _to_record(
        asset: VisualIndexAsset, vector: list[float], index_generation: str, publication_token: str
    ) -> dict[str, Any]:
        return {
            "id": f"visual:{asset.asset_id}",
            "asset_id": asset.asset_id,
            "asset_type": asset.asset_type,
            "knowledge_base_id": asset.knowledge_base_id,
            "project_id": asset.project_id or 0,
            "document_id": asset.document_id,
            "version_no": asset.version_no,
            "page_id": asset.page_id,
            "page_no": asset.page_no,
            "block_id": asset.block_id or 0,
            "block_index": asset.block_index if asset.block_index is not None else -1,
            "previous_block_id": asset.previous_block_id or 0,
            "next_block_id": asset.next_block_id or 0,
            "security_level": asset.security_level,
            "index_generation": index_generation,
            "publication_token": publication_token,
            "embedding": vector,
        }
