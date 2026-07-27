from app.retrieval.merger import EvidenceMerger
from app.retrieval.schemas import Evidence


def evidence(retriever: str, chunk_id: int, content: str, score: float, document_id: int = 1) -> Evidence:
    return Evidence(score, "base", 1, None, document_id, chunk_id, None, "doc.pdf", 1, content, retriever)


def test_cross_modal_scores_are_rank_fused_instead_of_compared_raw() -> None:
    merged = EvidenceMerger().merge(
        [
            [evidence("milvus", 1, "文本第一", 0.95), evidence("milvus", 2, "文本第二", 0.90)],
            [evidence("visual", -9, "视觉第一", 0.12), evidence("visual", -10, "视觉第二", 0.11)],
        ],
        limit=4,
    )

    assert {item.content for item in merged[:2]} == {"文本第一", "视觉第一"}
    assert all(item.metadata["fusion_method"] == "rrf" for item in merged)


def test_exact_duplicate_content_keeps_all_source_mappings() -> None:
    merged = EvidenceMerger().merge(
        [
            [evidence("milvus", 1, "相同参数表", 0.9, document_id=1)],
            [evidence("keyword", 8, "相同参数表", 9.0, document_id=2)],
        ]
    )

    assert len(merged) == 1
    assert {item["document_id"] for item in merged[0].metadata["source_mappings"]} == {1, 2}


def test_near_duplicates_are_retained_but_diversified_by_source_page() -> None:
    merged = EvidenceMerger().merge(
        [[
            evidence("milvus", 1, "压力 1.0 MPa", 0.99, document_id=1),
            evidence("milvus", 2, "压力 1.1 MPa", 0.98, document_id=1),
            evidence("milvus", 3, "温度 80 C", 0.97, document_id=2),
        ]],
        limit=3,
    )

    assert len(merged) == 3
    assert [item.document_id for item in merged[:2]] == [1, 2]
