"""Milvus storage and search adapter for BEIR corpora."""

from __future__ import annotations

import hashlib
import logging
import time
import warnings
from collections.abc import Callable
from typing import Any

from eval.beir.types import BeirCorpus, SearchHit

logger = logging.getLogger(__name__)

MAX_DOC_ID_LENGTH = 512
MAX_DATASET_LENGTH = 128
MAX_SPLIT_LENGTH = 64
MAX_TITLE_LENGTH = 2048
MAX_TEXT_LENGTH = 65535
MILVUS_ALIAS = "botree_beir_milvus"


class BeirMilvusStore:
    """
    BEIR-specific Milvus collection.

    BEIR 文档使用原始字符串 doc_id，线上 collection 使用业务 document/chunk ID。
    因此评测 collection 独立建表，并显式保留 beir_doc_id 供 BEIR metrics 回填。
    """

    def __init__(self, collection_name: str, settings: Any | None = None) -> None:
        if settings is None:
            from app.core.config import get_settings

            settings = get_settings()
        self.collection_name = collection_name
        self.settings = settings
        self._loaded_collection: Any | None = None

    def upsert_corpus(
        self,
        dataset: str,
        corpus: BeirCorpus,
        embed_texts: Callable[[list[str]], list[list[float]]],
        batch_size: int,
        split: str = "test",
    ) -> dict[str, Any]:
        """Write BEIR corpus embeddings to Milvus while preserving original doc_id."""

        if not corpus:
            return {
                "status": "skipped",
                "vector_count": 0,
                "collection": self.collection_name,
                "embedding_total_ms": 0,
                "upsert_total_ms": 0,
                "elapsed_ms": 0,
            }

        collection = self._collection(load_for_search=False)
        doc_items = list(corpus.items())
        total = len(doc_items)
        indexed_count = 0
        embedding_total_ms = 0
        upsert_total_ms = 0
        started_at = time.perf_counter()
        for start in range(0, total, batch_size):
            batch_items = doc_items[start : start + batch_size]
            texts = [_embedding_text(item[1]) for item in batch_items]

            embedding_started_at = time.perf_counter()
            vectors = embed_texts(texts)
            embedding_elapsed_ms = int((time.perf_counter() - embedding_started_at) * 1000)
            embedding_total_ms += embedding_elapsed_ms
            if len(vectors) != len(batch_items):
                raise ValueError(f"Embedding count mismatch: expected={len(batch_items)} actual={len(vectors)}")

            records = [
                self._record(dataset=dataset, split=split, doc_id=doc_id, document=document, embedding=embedding)
                for (doc_id, document), embedding in zip(batch_items, vectors, strict=False)
            ]
            upsert_started_at = time.perf_counter()
            collection.upsert(records)
            upsert_elapsed_ms = int((time.perf_counter() - upsert_started_at) * 1000)
            upsert_total_ms += upsert_elapsed_ms
            indexed_count += len(records)
            logger.info(
                "stage=corpus_indexing action=batch_upsert_completed dataset=%s split=%s collection=%s indexed=%s total=%s embedding_ms=%s upsert_ms=%s elapsed_ms=%s",
                dataset,
                split,
                self.collection_name,
                indexed_count,
                total,
                embedding_elapsed_ms,
                upsert_elapsed_ms,
                int((time.perf_counter() - started_at) * 1000),
            )

        collection.flush()
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "stage=corpus_indexing action=upsert_completed dataset=%s split=%s collection=%s count=%s embedding_ms=%s upsert_ms=%s elapsed_ms=%s",
            dataset,
            split,
            self.collection_name,
            indexed_count,
            embedding_total_ms,
            upsert_total_ms,
            elapsed_ms,
        )
        return {
            "status": "indexed",
            "vector_count": indexed_count,
            "collection": self.collection_name,
            "embedding_total_ms": embedding_total_ms,
            "embedding_avg_ms": embedding_total_ms / max(indexed_count, 1),
            "upsert_total_ms": upsert_total_ms,
            "upsert_avg_ms": upsert_total_ms / max(indexed_count, 1),
            "elapsed_ms": elapsed_ms,
        }

    def collection_exists(self) -> bool:
        """Return whether the BEIR Milvus collection exists."""

        _, _, _, _, _, utility = self._milvus_api()
        return bool(utility.has_collection(self.collection_name, using=MILVUS_ALIAS))

    def drop_collection(self) -> bool:
        """Drop the BEIR Milvus collection for explicit force reindex."""

        _, _, _, _, _, utility = self._milvus_api()
        self._loaded_collection = None
        if not utility.has_collection(self.collection_name, using=MILVUS_ALIAS):
            logger.info("stage=corpus_indexing action=drop_collection status=skipped collection=%s", self.collection_name)
            return False
        utility.drop_collection(self.collection_name, using=MILVUS_ALIAS)
        logger.info("stage=corpus_indexing action=drop_collection status=completed collection=%s", self.collection_name)
        return True

    def count_dataset_documents(self, dataset: str) -> int:
        """Count indexed BEIR documents for the dataset in the collection."""

        if not self.collection_exists():
            return 0
        collection = self._collection(load_for_search=True)
        expr = f'dataset == "{_escape_expr_value(dataset)}"'
        try:
            rows = collection.query(expr=expr, output_fields=["count(*)"])
            if rows:
                count_value = rows[0].get("count(*)") or rows[0].get("count")
                return int(count_value)
        except Exception:
            logger.warning(
                "stage=corpus_indexing action=count_dataset_documents status=query_count_failed collection=%s dataset=%s fallback=num_entities",
                self.collection_name,
                dataset,
                exc_info=True,
            )
        return int(getattr(collection, "num_entities", 0))

    def load_for_search(self) -> Any:
        """Load the Milvus collection once for all query searches."""

        return self._collection(load_for_search=True)

    def search(self, dataset: str, query_vector: list[float], top_k: int) -> list[SearchHit]:
        """Run Milvus TopK vector retrieval and return BEIR doc_id hits."""

        collection = self.load_for_search()
        field_names = {field.name for field in getattr(collection.schema, "fields", [])}
        output_fields = [field for field in ("beir_doc_id", "title", "text") if field in field_names]
        results = collection.search(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {}},
            limit=top_k,
            expr=f'dataset == "{_escape_expr_value(dataset)}"',
            output_fields=output_fields or ["beir_doc_id"],
        )
        hits: list[SearchHit] = []
        for rank, hit in enumerate(results[0], start=1):
            doc_id = str(hit.entity.get("beir_doc_id"))
            hits.append(
                SearchHit(
                    doc_id=doc_id,
                    score=float(hit.score),
                    rank=rank,
                    retriever="milvus",
                    metadata={"vector_id": hit.id},
                    title=str(hit.entity.get("title", "") or ""),
                    text=str(hit.entity.get("text", "") or ""),
                )
            )
        return hits

    def _collection(self, load_for_search: bool) -> Any:
        """Connect to Milvus, create the BEIR collection if needed, and optionally load it."""

        if load_for_search and self._loaded_collection is not None:
            return self._loaded_collection

        Collection, CollectionSchema, DataType, FieldSchema, _, utility = self._milvus_api()
        if not utility.has_collection(self.collection_name, using=MILVUS_ALIAS):
            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
                FieldSchema(name="dataset", dtype=DataType.VARCHAR, max_length=MAX_DATASET_LENGTH),
                FieldSchema(name="split", dtype=DataType.VARCHAR, max_length=MAX_SPLIT_LENGTH),
                FieldSchema(name="beir_doc_id", dtype=DataType.VARCHAR, max_length=MAX_DOC_ID_LENGTH),
                FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=MAX_TITLE_LENGTH),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=MAX_TEXT_LENGTH),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.settings.embedding_dim),
            ]
            schema = CollectionSchema(fields=fields, description="BEIR RAG evaluation collection")
            collection = Collection(self.collection_name, schema=schema, using=MILVUS_ALIAS)
            collection.create_index("embedding", {"metric_type": "COSINE", "index_type": "AUTOINDEX", "params": {}})
            logger.info("stage=corpus_indexing action=create_collection collection=%s dim=%s", self.collection_name, self.settings.embedding_dim)
        else:
            collection = Collection(self.collection_name, using=MILVUS_ALIAS)
            self._validate_embedding_dim(collection)

        if load_for_search:
            collection.load()
            self._loaded_collection = collection
        return collection

    def _milvus_api(self) -> tuple[Any, Any, Any, Any, Any, Any]:
        """Import pymilvus and connect with the BEIR alias."""

        if not getattr(self.settings, "milvus_enabled", False):
            raise RuntimeError("MILVUS_HOST/MILVUS_PORT is not configured; BEIR vector retrieval must use real Milvus")
        try:
            from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

            try:
                from pymilvus.exceptions import PyMilvusDeprecationWarning

                warnings.filterwarnings("ignore", category=PyMilvusDeprecationWarning)
            except Exception:
                warnings.filterwarnings("ignore", message=".*ORM-style PyMilvus API.*")
        except ImportError as exc:
            raise RuntimeError("pymilvus is required for real BEIR Milvus evaluation") from exc

        connections.connect(alias=MILVUS_ALIAS, host=self.settings.milvus_host, port=str(self.settings.milvus_port))
        return Collection, CollectionSchema, DataType, FieldSchema, connections, utility

    def _record(self, dataset: str, split: str, doc_id: str, document: dict[str, str], embedding: list[float]) -> dict[str, Any]:
        """Build a Milvus row with a stable primary key and original BEIR doc_id."""

        return {
            "id": _primary_id(dataset, split, doc_id),
            "dataset": _truncate_varchar(dataset, MAX_DATASET_LENGTH),
            "split": _truncate_varchar(split, MAX_SPLIT_LENGTH),
            "beir_doc_id": _truncate_varchar(doc_id, MAX_DOC_ID_LENGTH),
            "title": _truncate_varchar(document.get("title", ""), MAX_TITLE_LENGTH),
            "text": _truncate_varchar(document.get("text", ""), MAX_TEXT_LENGTH),
            "embedding": [float(value) for value in embedding],
        }

    def _validate_embedding_dim(self, collection: Any) -> None:
        """Fail fast when an existing collection was created with a different vector dim."""

        for field in collection.schema.fields:
            if field.name == "embedding":
                params = getattr(field, "params", {}) or {}
                dim = int(params.get("dim", self.settings.embedding_dim))
                if dim != self.settings.embedding_dim:
                    raise ValueError(
                        f"Milvus collection vector dimension mismatch: collection={self.collection_name} "
                        f"collection_dim={dim} settings_dim={self.settings.embedding_dim}"
                    )
                return


def _embedding_text(document: dict[str, str]) -> str:
    """Combine BEIR title and text for document embedding."""

    title = (document.get("title") or "").strip()
    text = (document.get("text") or "").strip()
    if title and text:
        return f"{title}\n{text}"
    return title or text


def _primary_id(dataset: str, split: str, doc_id: str) -> str:
    """Create a Milvus-safe primary key while keeping original doc_id in beir_doc_id."""

    digest = hashlib.sha1(f"{dataset}:{split}:{doc_id}".encode("utf-8")).hexdigest()
    return f"beir_{digest}"


def _escape_expr_value(value: str) -> str:
    """Escape a string value for a Milvus boolean expression."""

    return value.replace("\\", "\\\\").replace('"', '\\"')


def _truncate_varchar(value: str, max_bytes: int) -> str:
    """Trim UTF-8 strings to Milvus VARCHAR byte limits."""

    encoded = str(value).encode("utf-8")
    if len(encoded) <= max_bytes:
        return str(value)
    return encoded[:max_bytes].decode("utf-8", errors="ignore")
