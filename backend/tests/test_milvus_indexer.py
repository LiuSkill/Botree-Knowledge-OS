"""
Milvus Indexer Tests

职责：
1. 验证索引写入不会触发 Collection load，避免后台任务被加载状态阻塞。
2. 验证向量检索会在 search 前加载 Collection。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.knowledge.indexing.milvus_indexer import MilvusIndexer  # noqa: E402


DEFAULT_FIELDS = [
    "id",
    "knowledge_base_id",
    "project_id",
    "document_id",
    "chunk_id",
    "page_no",
    "version_no",
    "drawing_no",
    "embedding",
]


def make_settings() -> SimpleNamespace:
    """创建不依赖真实环境变量的 Milvus 配置。"""

    return SimpleNamespace(
        milvus_enabled=True,
        milvus_host="127.0.0.1",
        milvus_port=19530,
        milvus_collection="unit_test_collection",
        embedding_dim=3,
    )


def make_fake_pymilvus() -> tuple[dict[str, object], dict[str, ModuleType]]:
    """
    构造轻量 pymilvus 替身。

    业务规则：
        单测只验证本地调用顺序，不连接真实 Milvus，避免外部服务状态影响测试结果。
    """

    state: dict[str, object] = {"instances": [], "has_collection": True}

    class FakeDataType:
        VARCHAR = "VARCHAR"
        INT64 = "INT64"
        FLOAT_VECTOR = "FLOAT_VECTOR"

    class FakeFieldSchema:
        def __init__(self, name: str, **_: object) -> None:
            self.name = name

    class FakeCollectionSchema:
        def __init__(self, fields: list[FakeFieldSchema], description: str = "") -> None:
            self.fields = fields
            self.description = description

    class FakeConnections:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def connect(self, **kwargs: object) -> None:
            self.calls.append(kwargs)

    class FakeUtility:
        def has_collection(self, _: str, using: str | None = None) -> bool:
            return bool(state["has_collection"])

    class FakeHit:
        id = "vec-1"
        score = 0.88
        entity = {"document_id": 8, "chunk_id": 11}

    class FakeCollection:
        def __init__(
            self,
            name: str,
            schema: FakeCollectionSchema | None = None,
            using: str | None = None,
        ) -> None:
            self.name = name
            self.using = using
            self.schema = schema or FakeCollectionSchema([FakeFieldSchema(name=field) for field in DEFAULT_FIELDS])
            self.load_calls = 0
            self.upserted: list[dict[str, object]] = []
            self.deleted_expr: str | None = None
            self.flushed = False
            self.index_created = False
            instances = state["instances"]
            assert isinstance(instances, list)
            instances.append(self)

        def create_index(self, field_name: str, params: dict[str, object]) -> None:
            self.index_created = True
            self.index_field_name = field_name
            self.index_params = params

        def load(self) -> None:
            self.load_calls += 1

        def upsert(self, records: list[dict[str, object]]) -> None:
            self.upserted = records

        def flush(self) -> None:
            self.flushed = True

        def delete(self, expr: str) -> None:
            self.deleted_expr = expr

        def search(self, **_: object) -> list[list[FakeHit]]:
            return [[FakeHit()]]

    pymilvus = ModuleType("pymilvus")
    pymilvus.Collection = FakeCollection
    pymilvus.CollectionSchema = FakeCollectionSchema
    pymilvus.DataType = FakeDataType
    pymilvus.FieldSchema = FakeFieldSchema
    pymilvus.connections = FakeConnections()
    pymilvus.utility = FakeUtility()

    exceptions = ModuleType("pymilvus.exceptions")
    exceptions.PyMilvusDeprecationWarning = Warning
    return state, {"pymilvus": pymilvus, "pymilvus.exceptions": exceptions}


def latest_collection(state: dict[str, object]):
    """取出最近一次创建的 fake Collection。"""

    instances = state["instances"]
    assert isinstance(instances, list)
    return instances[-1]


def test_upsert_chunks_does_not_load_collection() -> None:
    """写入向量只需要 Collection 可写，不应等待 load 完成。"""

    state, modules = make_fake_pymilvus()
    with patch.dict(sys.modules, modules):
        indexer = MilvusIndexer()
        indexer.settings = make_settings()

        result = indexer.upsert_chunks(
            [
                {
                    "id": "doc_8_chunk_1_v1",
                    "document_id": 8,
                    "chunk_id": 1,
                    "embedding": [0.1, 0.2, 0.3],
                    "ignored": "drop-me",
                }
            ]
        )

    collection = latest_collection(state)
    assert collection.load_calls == 0
    assert collection.upserted == [
        {
            "id": "doc_8_chunk_1_v1",
            "document_id": 8,
            "chunk_id": 1,
            "embedding": [0.1, 0.2, 0.3],
        }
    ]
    assert collection.flushed is True
    assert result["status"] == "indexed"
    assert result["vector_count"] == 1


def test_delete_vectors_does_not_load_collection() -> None:
    """删除向量同属写路径，不应触发查询节点加载。"""

    state, modules = make_fake_pymilvus()
    with patch.dict(sys.modules, modules):
        indexer = MilvusIndexer()
        indexer.settings = make_settings()

        result = indexer.delete_vectors(document_id=8, vector_ids=["doc_8_chunk_1_v1"])

    collection = latest_collection(state)
    assert collection.load_calls == 0
    assert collection.deleted_expr == 'id in ["doc_8_chunk_1_v1"]'
    assert collection.flushed is True
    assert result["status"] == "deleted"


def test_search_loads_collection_before_query() -> None:
    """向量检索需要 Collection 已加载，search 路径仍保留 load。"""

    state, modules = make_fake_pymilvus()
    with patch.dict(sys.modules, modules):
        indexer = MilvusIndexer()
        indexer.settings = make_settings()

        hits = indexer.search(query_vector=[0.1, 0.2, 0.3], limit=5)

    collection = latest_collection(state)
    assert collection.load_calls == 1
    assert hits == [{"vector_id": "vec-1", "score": 0.88, "document_id": 8, "chunk_id": 11}]
