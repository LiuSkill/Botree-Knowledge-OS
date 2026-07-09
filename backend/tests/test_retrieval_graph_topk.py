from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.langgraph.retrieval_graph import RetrievalGraph  # noqa: E402
from app.retrieval.schemas import Evidence  # noqa: E402


def test_retrieval_graph_uses_fixed_topk_defaults() -> None:
    graph = object.__new__(RetrievalGraph)
    state = {
        "query_profile": {
            "query_type": "process_flow",
            "answer_shape": "process_steps",
            "need_visual_asset": True,
        },
        "query_features": {},
        "raw": {},
    }

    assert graph._candidate_k(state) == 20  # noqa: SLF001
    assert graph._rerank_top_k(state) == 20  # noqa: SLF001
    assert graph._eval_top_k(state) == 10  # noqa: SLF001
    assert graph._answer_top_k(state) == 10  # noqa: SLF001


def test_explicit_topk_is_capped_by_fixed_pipeline_limits() -> None:
    graph = object.__new__(RetrievalGraph)
    state = {
        "query_profile": {"query_type": "process_flow"},
        "query_features": {},
        "raw": {
            "candidate_k": 48,
            "rerank_top_k": 18,
            "eval_top_k": 16,
        },
    }

    assert graph._candidate_k(state) == 20  # noqa: SLF001
    assert graph._rerank_top_k(state) == 18  # noqa: SLF001
    assert graph._eval_top_k(state) == 10  # noqa: SLF001
    assert graph._answer_top_k(state) == 10  # noqa: SLF001


def test_process_flow_page_index_candidates_skip_heavy_reranker() -> None:
    graph = object.__new__(RetrievalGraph)
    state = {
        "query_profile": {
            "query_type": "process_flow",
            "answer_shape": "process_steps",
            "need_visual_asset": True,
        },
        "query_features": {},
        "raw": {},
        "intent_type": "project_fact",
    }
    candidates = [
        Evidence(
            score=6.7,
            source_type="project",
            knowledge_base_id=1,
            project_id=2,
            document_id=101,
            chunk_id=1001,
            drawing_no="10-PS-0200-0000-001",
            file_name="Process Flow Diagram.pdf",
            page_number=1,
            content="Na2SO4 evaporation process flow diagram",
            retriever="page_index",
        )
    ]

    assert graph._reranker_skip_reason(state, candidates) == "FLOW_VISUAL_PAGE_INDEX_PRIORITY"  # noqa: SLF001


def test_merge_evidences_dedupes_same_chunk_across_drawing_no_variants() -> None:
    graph = object.__new__(RetrievalGraph)
    first = Evidence(
        score=6.7,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=308,
        chunk_id=51190,
        drawing_no="DWG-001",
        file_name="Product List.pdf",
        page_number=3,
        content="Product List",
        retriever="keyword",
    )
    second = Evidence(
        score=6.2,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=308,
        chunk_id=51190,
        drawing_no=None,
        file_name="Product List.pdf",
        page_number=3,
        content="Product List",
        retriever="ripgrep",
    )

    merged = graph._merge_evidences_by_source([[first], [second]], 5)  # noqa: SLF001

    assert merged == [first]


def test_structured_list_query_preserves_planner_ladder_in_full_mode() -> None:
    graph = object.__new__(RetrievalGraph)
    plan_dict = {
        "selected_retrievers": ["page_index", "ripgrep", "milvus"],
        "fallback_ladder": [["page_index"], ["ripgrep"], ["milvus"], ["keyword"]],
        "skip_reasons": {"graphrag": "not needed"},
        "metadata": {},
        "reason": "structured_list_lookup",
    }

    enforced = graph._enforce_default_hybrid_plan(  # noqa: SLF001
        plan_dict,
        ["page_index", "ripgrep", "milvus", "keyword", "graphrag"],
        "full",
        {"has_structured_list_lookup": True},
    )

    assert enforced["selected_retrievers"] == ["page_index", "ripgrep", "milvus"]
    assert enforced["fallback_ladder"] == [["page_index"], ["ripgrep"], ["milvus"], ["keyword"]]
    assert enforced["default_hybrid_used"] is False


def test_structured_list_answer_context_prefers_row_chunks() -> None:
    graph = object.__new__(RetrievalGraph)
    header = Evidence(
        score=26.0,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=308,
        chunk_id=51192,
        drawing_no="DWG-001",
        file_name="Product List.pdf",
        page_number=3,
        content="| 序号NO. | 产品名称Product Name | 产出位置SERVICE |",
        retriever="page_index",
    )
    row_one = Evidence(
        score=25.0,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=308,
        chunk_id=51193,
        drawing_no="DWG-001",
        file_name="Product List.pdf",
        page_number=3,
        content="| 1 | Li2CO3 | Li2CO3 Drying |",
        retriever="page_index",
    )
    row_two = Evidence(
        score=24.0,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=308,
        chunk_id=51194,
        drawing_no="DWG-001",
        file_name="Product List.pdf",
        page_number=3,
        content="| 2 | FePO4·2H2O | FePO4 Synthesis |",
        retriever="page_index",
    )
    other = Evidence(
        score=20.0,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=307,
        chunk_id=51160,
        drawing_no="DWG-002",
        file_name="Waste List.pdf",
        page_number=3,
        content="| 1 | Dust | Pyrolysis Kiln |",
        retriever="ripgrep",
    )
    state = {
        "query_features": {"has_structured_list_lookup": True},
        "evidences": [header, other, row_one, row_two],
        "raw": {},
    }

    answer_context = graph._record_answer_context(state)  # noqa: SLF001

    assert [e.chunk_id for e in answer_context[:3]] == [51192, 51193, 51194]


def test_structured_list_answer_context_prefers_higher_scoring_row_group_over_larger_noise_group() -> None:
    graph = object.__new__(RetrievalGraph)
    product_row_one = Evidence(
        score=22.6,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=308,
        chunk_id=51193,
        drawing_no="DWG-001",
        file_name="Product List.pdf",
        page_number=3,
        content="| 1 | Li2CO3 | Li2CO3 Drying |",
        retriever="page_index",
    )
    product_row_two = Evidence(
        score=20.2,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=308,
        chunk_id=51194,
        drawing_no="DWG-001",
        file_name="Product List.pdf",
        page_number=3,
        content="| 2 | FePO4·2H2O | FePO4 Synthesis |",
        retriever="page_index",
    )
    noise_rows = [
        Evidence(
            score=12.1 - index * 0.2,
            source_type="project",
            knowledge_base_id=1,
            project_id=2,
            document_id=307,
            chunk_id=51160 + index,
            drawing_no="DWG-002",
            file_name="Waste List.pdf",
            page_number=3,
            content=f"| {index + 1} | Dust {index + 1} | Pretreatment Unit |",
            retriever="ripgrep",
        )
        for index in range(4)
    ]
    state = {
        "query_features": {"has_structured_list_lookup": True},
        "evidences": [product_row_one, *noise_rows, product_row_two],
        "raw": {},
    }

    answer_context = graph._record_answer_context(state)  # noqa: SLF001

    assert [e.chunk_id for e in answer_context[:2]] == [51193, 51194]


def test_structured_list_partial_skips_retry_when_rows_are_ready() -> None:
    graph = object.__new__(RetrievalGraph)
    row_one = Evidence(
        score=25.0,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=308,
        chunk_id=51193,
        drawing_no="DWG-001",
        file_name="Product List.pdf",
        page_number=3,
        content="| 1 | Li2CO3 | Li2CO3 Drying |",
        retriever="page_index",
    )
    row_two = Evidence(
        score=24.0,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=308,
        chunk_id=51194,
        drawing_no="DWG-001",
        file_name="Product List.pdf",
        page_number=3,
        content="| 2 | FePO4·2H2O | FePO4 Synthesis |",
        retriever="page_index",
    )
    row_three = Evidence(
        score=23.0,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=308,
        chunk_id=51195,
        drawing_no="DWG-001",
        file_name="Product List.pdf",
        page_number=3,
        content="| 3 | Na2SO4 | Na2SO4 Evaporation |",
        retriever="page_index",
    )
    state = {
        "query_features": {"has_structured_list_lookup": True},
        "evidences": [row_one, row_two, row_three],
    }

    should_skip = graph._should_skip_retry_for_structured_list_partial(  # noqa: SLF001
        state,
        {"evidence_status": "PARTIAL"},
    )

    assert should_skip is True
