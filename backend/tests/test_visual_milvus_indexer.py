from __future__ import annotations

import sys
import warnings
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))


def make_settings() -> SimpleNamespace:
    return SimpleNamespace(
        visual_index_enabled=True,
        milvus_host="127.0.0.1",
        milvus_port=19530,
        visual_milvus_collection="unit_test_visual_collection",
        visual_embedding_dim=3,
    )


def make_fake_pymilvus() -> tuple[dict[str, object], dict[str, ModuleType]]:
    state: dict[str, object] = {"instances": []}

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
        def connect(self, **_: object) -> None:
            from pymilvus.exceptions import PyMilvusDeprecationWarning

            warnings.warn(
                "`connections.connect` is an ORM-style PyMilvus API and will be removed in PyMilvus 3.1. Use `MilvusClient` instead.",
                PyMilvusDeprecationWarning,
            )

    class FakeUtility:
        def has_collection(self, _: str, using: str | None = None) -> bool:  # noqa: ARG002
            return True

    class FakeCollection:
        def __init__(
            self,
            name: str,
            schema: FakeCollectionSchema | None = None,
            using: str | None = None,
        ) -> None:
            del name, using
            self.schema = schema or FakeCollectionSchema(
                [
                    FakeFieldSchema(name=field)
                    for field in (
                        "id",
                        "asset_id",
                        "knowledge_base_id",
                        "project_id",
                        "document_id",
                        "version_no",
                        "page_id",
                        "page_no",
                        "block_id",
                        "block_index",
                        "previous_block_id",
                        "next_block_id",
                        "asset_type",
                        "security_level",
                        "index_generation",
                        "publication_token",
                        "embedding",
                    )
                ]
            )
            self.load_calls = 0
            instances = state["instances"]
            assert isinstance(instances, list)
            instances.append(self)

        def create_index(self, field_name: str, params: dict[str, object]) -> None:
            del field_name, params

        def load(self) -> None:
            self.load_calls += 1

        def search(self, **_: object) -> list[list[object]]:
            return [[]]

    pymilvus = ModuleType("pymilvus")
    pymilvus.Collection = FakeCollection
    pymilvus.CollectionSchema = FakeCollectionSchema
    pymilvus.DataType = FakeDataType
    pymilvus.FieldSchema = FakeFieldSchema
    pymilvus.connections = FakeConnections()
    pymilvus.utility = FakeUtility()

    exceptions = ModuleType("pymilvus.exceptions")

    class PyMilvusDeprecationWarning(Warning):
        pass

    exceptions.PyMilvusDeprecationWarning = PyMilvusDeprecationWarning
    return state, {"pymilvus": pymilvus, "pymilvus.exceptions": exceptions}


def latest_collection(state: dict[str, object]):
    instances = state["instances"]
    assert isinstance(instances, list)
    return instances[-1]


def test_visual_search_suppresses_pymilvus_orm_warning() -> None:
    state, modules = make_fake_pymilvus()
    with patch.dict(sys.modules, modules):
        sys.modules.pop("app.knowledge.indexing.visual_milvus_indexer", None)
        from app.knowledge.indexing.visual_milvus_indexer import VisualMilvusIndexer

        indexer = VisualMilvusIndexer()
        indexer.settings = make_settings()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            hits = indexer.search(query_vector=[0.1, 0.2, 0.3], limit=5)

    collection = latest_collection(state)
    assert hits == []
    assert collection.load_calls == 1
    assert not any(item.category.__name__ == "PyMilvusDeprecationWarning" for item in caught)
