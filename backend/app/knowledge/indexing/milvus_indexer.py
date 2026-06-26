"""
Milvus Indexer

负责：
1. 连接真实 Milvus 向量数据库
2. 创建和维护文档 Chunk 向量集合
3. 执行向量写入、检索和删除
"""

from __future__ import annotations

import logging
import warnings
from typing import Any

from app.core.config import get_settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)

REQUIRED_COLLECTION_FIELDS = {
    "id",
    "knowledge_base_id",
    "project_id",
    "document_id",
    "chunk_id",
    "page_no",
    "version_no",
    "drawing_no",
    "security_level",
    "embedding",
}


class MilvusIndexer:
    """
    Milvus 索引器

    职责：
    - 按配置连接 Milvus
    - 确保集合、向量索引和加载状态可用
    - 提供 upsert/search/delete 三类真实向量操作
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def upsert_chunks(self, records: list[dict[str, Any]]) -> dict:
        """
        写入 Chunk 向量。

        参数:
            records: Milvus 行数据，必须包含 id、document_id、chunk_id、embedding。

        返回:
            写入结果摘要。
        """

        if not records:
            return {"status": "skipped", "vector_count": 0}

        collection = self._collection(load_for_search=False)
        collection_fields = {field.name for field in collection.schema.fields}
        if any(not str(record.get("security_level") or "").strip() for record in records):
            raise AppException("Milvus 写入记录缺少 security_level，已阻止无密级向量入库", status_code=500, code=500)
        filtered_records = [
            {key: value for key, value in record.items() if key in collection_fields}
            for record in records
        ]
        collection.upsert(filtered_records)
        collection.flush()
        logger.info("Milvus向量写入完成: collection=%s count=%s", self.settings.milvus_collection, len(records))
        return {"status": "indexed", "vector_count": len(records), "collection": self.settings.milvus_collection}

    def search(self, query_vector: list[float], limit: int, expr: str | None = None) -> list[dict[str, Any]]:
        """
        执行向量检索。

        参数:
            query_vector: 查询向量。
            limit: 最大返回数量。

        返回:
            包含 chunk_id、document_id 和 score 的结果列表。
        """

        collection = self._collection(load_for_search=True)
        results = collection.search(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {}},
            limit=limit,
            expr=expr,
            output_fields=["knowledge_base_id", "project_id", "document_id", "chunk_id", "version_no", "security_level"],
        )
        hits: list[dict[str, Any]] = []
        for hit in results[0]:
            hits.append(
                {
                    "vector_id": hit.id,
                    "score": float(hit.score),
                    "knowledge_base_id": int(hit.entity.get("knowledge_base_id")),
                    "project_id": int(hit.entity.get("project_id")),
                    "document_id": int(hit.entity.get("document_id")),
                    "chunk_id": int(hit.entity.get("chunk_id")),
                    "version_no": int(hit.entity.get("version_no")),
                    "security_level": str(hit.entity.get("security_level") or ""),
                }
            )
        return hits

    def delete_vectors(self, document_id: int, vector_ids: list[str] | None = None) -> dict:
        """
        删除文档向量。

        参数:
            document_id: 文档ID。
            vector_ids: 指定向量ID；为空时按 document_id 删除。

        返回:
            删除结果摘要。
        """

        collection = self._collection(load_for_search=False)
        if vector_ids:
            safe_ids = [item.replace("\\", "\\\\").replace('"', '\\"') for item in vector_ids]
            joined_ids = '","'.join(safe_ids)
            expr = f'id in ["{joined_ids}"]'
        else:
            expr = f"document_id == {int(document_id)}"
        collection.delete(expr)
        collection.flush()
        logger.info("Milvus向量删除完成: collection=%s document_id=%s ids=%s", self.settings.milvus_collection, document_id, len(vector_ids or []))
        return {"status": "deleted", "deleted_vector_count": len(vector_ids or []), "collection": self.settings.milvus_collection}

    def _collection(self, load_for_search: bool = False):
        """
        获取并准备 Milvus Collection。

        参数:
            load_for_search: 是否将 Collection 加载到查询节点。
                写入和删除不需要 load，避免索引任务被 Milvus 加载状态长时间阻塞。

        返回:
            已准备好的 Milvus Collection 对象。
        """

        if not self.settings.milvus_enabled:
            raise AppException("未配置 MILVUS_HOST，无法执行真实向量索引", status_code=500, code=500)
        try:
            from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility
            try:
                from pymilvus.exceptions import PyMilvusDeprecationWarning

                # 当前版本先保留 ORM-style API 以降低改造风险，过滤 SDK 已知弃用噪声。
                warnings.filterwarnings("ignore", category=PyMilvusDeprecationWarning)
            except Exception:
                warnings.filterwarnings("ignore", message=".*ORM-style PyMilvus API.*")
        except Exception as exc:
            raise AppException("当前环境缺少 pymilvus，无法连接真实 Milvus", status_code=500, code=500) from exc

        alias = "botree_milvus"
        connections.connect(alias=alias, host=self.settings.milvus_host, port=str(self.settings.milvus_port))
        if not utility.has_collection(self.settings.milvus_collection, using=alias):
            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
                FieldSchema(name="knowledge_base_id", dtype=DataType.INT64),
                FieldSchema(name="project_id", dtype=DataType.INT64),
                FieldSchema(name="document_id", dtype=DataType.INT64),
                FieldSchema(name="chunk_id", dtype=DataType.INT64),
                FieldSchema(name="page_no", dtype=DataType.INT64),
                FieldSchema(name="version_no", dtype=DataType.INT64),
                FieldSchema(name="drawing_no", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="security_level", dtype=DataType.VARCHAR, max_length=30),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.settings.embedding_dim),
            ]
            schema = CollectionSchema(fields=fields, description="Botree 文档 Chunk 向量集合")
            collection = Collection(self.settings.milvus_collection, schema=schema, using=alias)
            collection.create_index("embedding", {"metric_type": "COSINE", "index_type": "AUTOINDEX", "params": {}})
            logger.info("Milvus集合已创建: collection=%s dim=%s", self.settings.milvus_collection, self.settings.embedding_dim)
        else:
            collection = Collection(self.settings.milvus_collection, using=alias)
        self._ensure_schema_supported(collection)
        if load_for_search:
            collection.load()
        return collection

    def _ensure_schema_supported(self, collection: Any) -> None:
        """旧 Milvus 集合缺少密级字段时必须重建，避免无密级向量继续参与检索。"""

        field_names = {field.name for field in collection.schema.fields}
        missing_fields = sorted(REQUIRED_COLLECTION_FIELDS - field_names)
        if missing_fields:
            raise AppException(
                f"Milvus collection 缺少字段 {missing_fields}，请重建向量索引后再提供检索服务",
                status_code=500,
                code=500,
            )
