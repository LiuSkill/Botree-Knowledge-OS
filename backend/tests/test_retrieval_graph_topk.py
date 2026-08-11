from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.langgraph.retrieval_graph import RetrievalGraph  # noqa: E402
from app.retrieval.schemas import Evidence, EvidenceAsset  # noqa: E402


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


def test_debug_evidence_payload_keeps_content_scores_source_and_assets() -> None:
    """Debugger 候选快照必须足以复盘召回与重排，不得只保留摘要。"""

    graph = object.__new__(RetrievalGraph)
    evidence = Evidence(
        score=0.87,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=101,
        chunk_id=1001,
        drawing_no="PFD-001",
        file_name="process.pdf",
        page_number=3,
        content="蒸发温度为 80 摄氏度。",
        retriever="vector",
        metadata={"original_score": 0.72, "filter_reason": None},
        assets=[
            EvidenceAsset(
                asset_id=9,
                asset_type="page_image",
                url="/assets/9",
                mime_type="image/png",
                file_name="page-3.png",
                file_size=128,
                page_number=3,
            )
        ],
    )

    payload = graph._evidence_debug_payload(evidence)  # noqa: SLF001

    assert payload["content"] == "蒸发温度为 80 摄氏度。"
    assert payload["score"] == 0.87
    assert payload["retriever"] == "vector"
    assert payload["metadata"]["original_score"] == 0.72
    assert payload["assets"][0]["asset_id"] == 9


def test_trace_details_keep_stage_data_needed_for_debugger_replay() -> None:
    """节点事件必须携带召回候选和最终证据，不能只在结束事件保存整包状态。"""

    graph = object.__new__(RetrievalGraph)
    evidence = Evidence(
        score=0.91,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=101,
        chunk_id=1001,
        drawing_no=None,
        file_name="cooling-water.pdf",
        page_number=42,
        content="循环水供水温度为 32℃，回水温度为 42℃。",
        retriever="vector",
        metadata={},
        assets=[],
    )
    candidate = graph._evidence_debug_payload(evidence)  # noqa: SLF001
    state = {
        "raw": {
            "retrieval_before_rerank_candidates": [candidate],
            "rerank_after_candidates": [{**candidate, "score": 0.96}],
        },
        "rerank_details": [{"chunk_id": 1001, "rank_before": 2, "rank_after": 1}],
        "evidences": [evidence],
        "model_routes": {},
    }

    retrieval = graph._trace_details("检索召回与数据组装", state, "retrieval")  # noqa: SLF001
    evidence_judge = graph._trace_details("资料证据有效性判断", state, "evidence_judge")  # noqa: SLF001

    assert retrieval["retrieval_before_rerank_candidates"][0]["content"].startswith("循环水")
    assert retrieval["rerank_after_candidates"][0]["score"] == 0.96
    assert retrieval["rerank_details"][0]["rank_after"] == 1
    assert evidence_judge["final_evidence_set"][0]["file_name"] == "cooling-water.pdf"


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


def test_process_flow_kept_visual_candidate_does_not_skip_reranker() -> None:
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
    page_index = Evidence(
        score=0.04,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=101,
        chunk_id=1001,
        drawing_no=None,
        file_name="BMI黑粉两段浸出实验实验报告.docx",
        page_number=4,
        content="两段浸出实验结果表",
        retriever="page_index",
    )
    visual = Evidence(
        score=0.016,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=6128,
        chunk_id=-52099,
        drawing_no=None,
        file_name="BMI黑粉两段浸出实验实验报告.docx",
        page_number=2,
        content="视觉证据：第2页 （2）实验流程",
        retriever="visual",
        metadata={"asset_id": 52099},
        assets=[
            EvidenceAsset(
                asset_id=52099,
                asset_type="block_image",
                url="/api/documents/assets/52099",
                mime_type="image/jpeg",
                file_name="page_0002_block_0003.jpg",
                file_size=22113,
                page_number=2,
                block_id=283802,
            )
        ],
    )

    assert graph._reranker_skip_reason(state, [page_index, visual]) is None  # noqa: SLF001


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
