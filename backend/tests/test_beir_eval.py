"""Tests for the standalone BEIR evaluation utilities."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

BASE_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BASE_DIR.parent
sys.path.insert(0, str(WORKSPACE_ROOT))
sys.path.insert(0, str(BASE_DIR))

from eval.beir.fusion import concat_dedupe_fusion, reciprocal_rank_fusion, weighted_fusion  # noqa: E402
from eval.beir.keyword import BM25KeywordAdapter  # noqa: E402
from eval.beir.cli import parse_args  # noqa: E402
from eval.beir.milvus_store import BeirMilvusStore  # noqa: E402
from eval.beir.report_writer import write_eval_reports  # noqa: E402
from eval.beir.reporting import write_reports  # noqa: E402
from eval.beir.rerank import BeirReranker  # noqa: E402
from eval.beir.runner import BeirEvalConfig, BeirEvaluationRunner  # noqa: E402
from eval.beir.types import QueryTrace, SearchHit  # noqa: E402


def test_reciprocal_rank_fusion_promotes_multi_source_hit() -> None:
    """RRF 应提升多路同时命中的文档。"""

    fused = reciprocal_rank_fusion(
        {
            "milvus": [
                SearchHit(doc_id="d1", score=0.9, rank=1, retriever="milvus"),
                SearchHit(doc_id="d2", score=0.8, rank=2, retriever="milvus"),
            ],
            "bm25": [
                SearchHit(doc_id="d2", score=7.0, rank=1, retriever="bm25"),
                SearchHit(doc_id="d3", score=3.0, rank=2, retriever="bm25"),
            ],
        },
        top_k=3,
    )

    assert [hit.doc_id for hit in fused] == ["d2", "d1", "d3"]
    assert fused[0].metadata["sources"]["milvus"]["rank"] == 2
    assert fused[0].metadata["sources"]["bm25"]["rank"] == 1


def test_weighted_and_concat_fusion_are_deterministic() -> None:
    """组合检索融合应稳定保留原始 doc_id 和来源信息。"""

    groups = {
        "milvus": [
            SearchHit(doc_id="d1", score=0.9, rank=1, retriever="milvus"),
            SearchHit(doc_id="d2", score=0.1, rank=2, retriever="milvus"),
        ],
        "bm25": [
            SearchHit(doc_id="d2", score=10.0, rank=1, retriever="bm25"),
            SearchHit(doc_id="d3", score=1.0, rank=2, retriever="bm25"),
        ],
    }

    weighted = weighted_fusion(groups, weights={"bm25": 1.0, "milvus": 2.0}, top_k=3)
    concat = concat_dedupe_fusion(groups, top_k=3)

    assert weighted[0].doc_id == "d1"
    assert weighted[1].doc_id == "d2"
    assert [hit.doc_id for hit in concat] == ["d1", "d2", "d3"]


def test_bm25_keyword_adapter_returns_relevant_document() -> None:
    """BM25 baseline 应根据 query token 返回相关文档。"""

    adapter = BM25KeywordAdapter()
    adapter.index(
        {
            "d1": {"title": "neural retrieval", "text": "dense vector search for scientific documents"},
            "d2": {"title": "gardening notes", "text": "soil water and sun"},
        }
    )

    hits = adapter.search("scientific vector retrieval", top_k=2)

    assert hits
    assert hits[0].doc_id == "d1"
    assert hits[0].score > 0


def test_cli_online_answer_is_disabled_by_default(monkeypatch) -> None:
    """full_rag 即使请求 include_answer，也应默认禁用在线 answer LLM。"""

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "beir-cli",
            "--dataset",
            "scifact",
            "--retriever",
            "full_rag",
            "--include_answer",
            "true",
        ],
    )

    args = parse_args()

    assert args.include_answer is True
    assert args.enable_online_answer is False


def test_beir_reranker_records_inputs_and_score_order() -> None:
    """Reranker adapter 搴旇褰?title+text 杈撳叆銆佹柊鏃?rank 鍜?qrels 鍛戒腑銆?"""

    corpus = {
        "d1": {"title": "alpha title", "text": "alpha body"},
        "d2": {"title": "beta title", "text": "beta body"},
    }
    hits = [
        SearchHit(doc_id="d1", score=10.0, rank=1, retriever="rrf"),
        SearchHit(doc_id="d2", score=1.0, rank=2, retriever="rrf"),
    ]

    result = BeirReranker(
        db=None,
        score_order="asc",
        require_real_reranker=False,
        allow_fallback=True,
    ).rerank(
        query_id="q1",
        query="alpha",
        hits=hits,
        corpus=corpus,
        expected_doc_ids={"d2"},
        limit=2,
    )

    assert result.model_name == "deterministic_fallback"
    assert result.hits[0].doc_id == "d2"
    assert result.input_samples[0]["query_text"] == "alpha"
    assert "alpha title" in result.input_samples[0]["candidate_text_preview"]
    assert result.debug_rows[0]["old_rank"] == 2
    assert result.debug_rows[0]["new_rank"] == 1
    assert result.debug_rows[0]["is_qrels_hit"] is True
    assert any("RERANKER_MODEL_UNCONFIGURED" in warning for warning in result.warnings)


def test_write_reports_creates_json_and_markdown(tmp_path: Path) -> None:
    """报告输出应同时生成 JSON 和 Markdown。"""

    trace = QueryTrace(
        query_id="q1",
        query="what is retrieval",
        elapsed_ms=12,
        top_docs=["d1"],
        rankings=[{"rank": 1, "doc_id": "d1", "score": 1.0, "qrels_hit": True}],
        qrels_doc_ids=["d1"],
        hit_qrels=["d1"],
        retriever="milvus",
        rerank=False,
    )
    paths = write_reports(
        report_dir=tmp_path,
        dataset="scifact",
        retriever="milvus",
        top_k=10,
        rerank=False,
        payload={
            "config": {
                "dataset": "scifact",
                "split": "test",
                "retriever": "milvus",
                "keyword_adapter": "bm25",
                "top_k": 10,
                "rerank": False,
                "collection_name": "beir_test",
                "query_count": 1,
                "corpus_count": 1,
            },
            "metrics": {"flat": {"NDCG@10": 1.0}},
            "results": {"q1": {"d1": 1.0}},
        },
        traces=[trace],
    )

    assert paths["json"].exists()
    assert paths["markdown"].exists()
    assert "NDCG@10" in paths["markdown"].read_text(encoding="utf-8")


def test_write_eval_reports_creates_required_files(tmp_path: Path) -> None:
    """统一报告输出应包含 metrics、query details、failed cases 和 markdown report。"""

    payload = {
        "config": {
            "dataset": "scifact",
            "split": "test",
            "mode": "eval",
            "retriever": "bm25",
            "retrievers": ["bm25"],
            "fusion": "rrf",
            "rerank": False,
            "reranker_score_order": "desc",
            "top_k": 100,
            "candidate_k": 100,
            "collection_name": "beir_test",
            "query_count": 1,
            "corpus_count": 1,
        },
        "metrics": {"flat": {"NDCG@10": 1.0, "Recall@100": 1.0}},
        "latency": {"total_ms": 10, "retrieval_avg_ms": 3},
        "hit_summary": {"hit_at_10": {"hit_queries": 1, "total_queries": 1, "hit_rate": 1.0}},
        "rerank_summary": {"enabled": False},
        "rerank_debug_rows": [],
        "warnings": [],
        "errors": [],
        "results": {"q1": {"d1": 1.0}},
        "query_traces": [
            {
                "query_id": "q1",
                "query_text": "what is retrieval",
                "expected_doc_ids": ["d1"],
                "retrieved_doc_ids": ["d1"],
                "hit_at": {"1": True, "3": True, "5": True, "10": True, "50": True, "100": True},
                "first_hit_rank": 1,
                "retriever_route": "bm25",
                "fusion_method": "",
                "rerank_enabled": False,
                "reranker_model_name": "",
                "reranker_score_order": "",
                "rerank_before_first_hit_rank": 1,
                "latency_ms": {
                    "total_ms": 3,
                    "embedding_ms": 0,
                    "retrieval_ms": 3,
                    "fusion_ms": 0,
                    "rerank_ms": 0,
                    "planner_ms": 0,
                },
                "error": "",
            }
        ],
    }

    paths = write_eval_reports(tmp_path, payload)

    assert set(paths) == {
        "metrics_json",
        "query_details_csv",
        "query_details_jsonl",
        "rerank_debug_csv",
        "failed_cases_md",
        "report_md",
    }
    assert "query_id,query_text,candidate_k,rerank_top_k,eval_top_k,answer_top_k,expected_doc_ids" in paths[
        "query_details_csv"
    ].read_text(encoding="utf-8-sig")
    assert "query_id,doc_id,old_rank,new_rank,rank_delta" in paths["rerank_debug_csv"].read_text(encoding="utf-8-sig")
    assert "NDCG@10" in paths["report_md"].read_text(encoding="utf-8")


def test_milvus_store_creates_beir_doc_id_schema(monkeypatch) -> None:
    """BEIR collection schema 必须包含原始 beir_doc_id 字段。"""

    state: dict[str, object] = {"instances": [], "has_collection": False}

    class FakeDataType:
        VARCHAR = "VARCHAR"
        FLOAT_VECTOR = "FLOAT_VECTOR"

    class FakeFieldSchema:
        def __init__(self, name: str, **kwargs: object) -> None:
            self.name = name
            self.params = kwargs

    class FakeCollectionSchema:
        def __init__(self, fields: list[FakeFieldSchema], description: str = "") -> None:
            self.fields = fields
            self.description = description

    class FakeConnections:
        def connect(self, **_: object) -> None:
            return None

    class FakeUtility:
        def has_collection(self, _: str, using: str | None = None) -> bool:
            return bool(state["has_collection"])

    class FakeCollection:
        def __init__(self, name: str, schema: FakeCollectionSchema | None = None, using: str | None = None) -> None:
            self.name = name
            self.schema = schema
            self.using = using
            self.loaded = False
            instances = state["instances"]
            assert isinstance(instances, list)
            instances.append(self)

        def create_index(self, field_name: str, params: dict[str, object]) -> None:
            self.index_field_name = field_name
            self.index_params = params

        def load(self) -> None:
            self.loaded = True

    pymilvus = ModuleType("pymilvus")
    pymilvus.Collection = FakeCollection
    pymilvus.CollectionSchema = FakeCollectionSchema
    pymilvus.DataType = FakeDataType
    pymilvus.FieldSchema = FakeFieldSchema
    pymilvus.connections = FakeConnections()
    pymilvus.utility = FakeUtility()
    monkeypatch.setitem(sys.modules, "pymilvus", pymilvus)

    settings = SimpleNamespace(milvus_enabled=True, milvus_host="127.0.0.1", milvus_port=19530, embedding_dim=3)
    store = BeirMilvusStore("beir_unit_test", settings=settings)
    collection = store._collection(load_for_search=False)

    field_names = [field.name for field in collection.schema.fields]
    assert "beir_doc_id" in field_names
    assert "embedding" in field_names


class FakeMilvusStore:
    """Minimal Milvus store fake for index-plan tests."""

    def __init__(self, exists: bool, count: int) -> None:
        self.exists = exists
        self.count = count

    def collection_exists(self) -> bool:
        return self.exists

    def count_dataset_documents(self, dataset: str) -> int:
        return self.count


def make_runner_config(tmp_path: Path, **overrides: object) -> BeirEvalConfig:
    """Create a runner config for index decision tests."""

    values = {
        "dataset": "scifact",
        "retriever": "milvus",
        "top_k": 10,
        "rerank": False,
        "collection_name": "beir_unit_test",
        "data_dir": tmp_path / "datasets",
        "reports_dir": tmp_path / "reports",
    }
    values.update(overrides)
    return BeirEvalConfig(**values)


def test_index_plan_skips_ready_collection(tmp_path: Path) -> None:
    """collection 文档数匹配 corpus 时默认跳过 corpus embedding。"""

    runner = BeirEvaluationRunner(make_runner_config(tmp_path))
    plan = runner._build_index_plan(FakeMilvusStore(exists=True, count=5183), corpus_count=5183)

    assert plan.should_index is False
    assert plan.reason == "collection_ready"


def test_index_plan_requires_force_reindex_on_count_mismatch(tmp_path: Path) -> None:
    """collection 文档数不匹配时不得默认重新向量化 corpus。"""

    runner = BeirEvaluationRunner(make_runner_config(tmp_path))

    try:
        runner._build_index_plan(FakeMilvusStore(exists=True, count=1280), corpus_count=5183)
    except RuntimeError as exc:
        assert "--force_reindex" in str(exc)
    else:
        raise AssertionError("count mismatch should require --force_reindex")
