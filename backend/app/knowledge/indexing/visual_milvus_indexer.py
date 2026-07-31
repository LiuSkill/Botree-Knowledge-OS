"""独立视觉 Milvus Collection 适配器。"""

from __future__ import annotations

import warnings
from typing import Any

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.knowledge.indexing.milvus_flush_control import flush_with_retry


class VisualMilvusIndexer:
    """存取整页和区域视觉向量，避免与文本 Chunk schema 混用。"""

    def __init__(self) -> None:
        self.settings = get_settings()

    def upsert(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        if not records:
            return {"status": "skipped", "vector_count": 0}
        collection = self._collection(load_for_search=False)
        collection.upsert(records)
        flush_with_retry(collection, collection_name=self.settings.visual_milvus_collection)
        return {
            "status": "indexed",
            "vector_count": len(records),
            "collection": self.settings.visual_milvus_collection,
        }

    def search(self, query_vector: list[float], limit: int, expr: str | None = None) -> list[dict[str, Any]]:
        collection = self._collection(load_for_search=True)
        results = collection.search(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {}},
            limit=limit,
            expr=expr,
            output_fields=[
                "asset_id", "asset_type", "document_id", "version_no", "page_id", "page_no",
                "block_id", "block_index", "previous_block_id", "next_block_id", "index_generation",
                "publication_token",
            ],
        )
        hits: list[dict[str, Any]] = []
        for hit in results[0]:
            item = {"score": float(hit.score)}
            for field_name in (
                "asset_id", "document_id", "version_no", "page_id", "page_no", "block_id",
                "block_index", "previous_block_id", "next_block_id",
            ):
                item[field_name] = int(hit.entity.get(field_name))
            item["asset_type"] = str(hit.entity.get("asset_type"))
            item["index_generation"] = str(hit.entity.get("index_generation"))
            item["publication_token"] = str(hit.entity.get("publication_token"))
            hits.append(item)
        return hits

    def delete_document(self, document_id: int, *, flush: bool = True) -> dict[str, Any]:
        # Milvus 对 delete 与 search 一样要求 collection 已加载；新建空集合后重建也必须满足该契约。
        collection = self._collection(load_for_search=True)
        result = collection.delete(f"document_id == {int(document_id)}")
        if flush:
            flush_with_retry(collection, collection_name=self.settings.visual_milvus_collection)
        return {"status": "deleted", "delete_count": int(getattr(result, "delete_count", 0) or 0)}

    def _collection(self, load_for_search: bool):
        if not self.settings.visual_index_enabled:
            raise AppException("视觉索引配置不完整", status_code=500, code=500)
        try:
            from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility
            try:
                from pymilvus.exceptions import PyMilvusDeprecationWarning

                # 视觉索引仍沿用当前稳定的 ORM-style 连接方式，先过滤 SDK 已知弃用告警，避免污染索引与检索日志。
                warnings.filterwarnings("ignore", category=PyMilvusDeprecationWarning)
            except Exception:
                warnings.filterwarnings("ignore", message=".*ORM-style PyMilvus API.*")
        except ImportError as exc:
            raise AppException("当前环境缺少 pymilvus", status_code=500, code=500) from exc

        alias = "botree_visual_milvus"
        connections.connect(alias=alias, host=self.settings.milvus_host, port=str(self.settings.milvus_port))
        name = self.settings.visual_milvus_collection
        if not utility.has_collection(name, using=alias):
            varchar = lambda field, size: FieldSchema(name=field, dtype=DataType.VARCHAR, max_length=size)
            integer_fields = [
                "asset_id", "knowledge_base_id", "project_id", "document_id", "version_no", "page_id",
                "page_no", "block_id", "block_index", "previous_block_id", "next_block_id",
            ]
            fields = [FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128)]
            fields.extend(FieldSchema(name=field, dtype=DataType.INT64) for field in integer_fields)
            fields.extend([
                varchar("asset_type", 30), varchar("security_level", 30), varchar("index_generation", 128),
                varchar("publication_token", 64),
            ])
            fields.append(
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.settings.visual_embedding_dim)
            )
            collection = Collection(name, schema=CollectionSchema(fields, description="Botree visual vectors"), using=alias)
            collection.create_index("embedding", {"metric_type": "COSINE", "index_type": "AUTOINDEX", "params": {}})
        else:
            collection = Collection(name, using=alias)
        if load_for_search:
            collection.load()
        return collection
