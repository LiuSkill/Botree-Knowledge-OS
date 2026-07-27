from app.knowledge.chunking.chunk_builder import ChunkBuilder


def test_structure_boundaries_are_preserved_before_length_fallback() -> None:
    builder = ChunkBuilder(chunk_size=80, overlap=10, rule_version="structure-v1", index_generation="gen-7")
    chunks = builder.build(
        [
            {
                "page_number": 3,
                "clean_content": "# 第一章\n泵的用途说明。\n\n1.1 启动条件\n入口阀必须开启。\n\n| 参数 | 数值 |\n| 压力 | 1.2 MPa |",
            }
        ]
    )

    assert [item["content"] for item in chunks] == [
        "# 第一章\n泵的用途说明。",
        "1.1 启动条件\n入口阀必须开启。",
        "| 参数 | 数值 |\n| 压力 | 1.2 MPa |",
    ]
    assert chunks[0]["metadata"]["chunk_rule_version"] == "structure-v1"
    assert chunks[0]["metadata"]["index_generation"] == "gen-7"
    assert chunks[0]["metadata"]["next_chunk_index"] == 2
    assert chunks[1]["metadata"]["previous_chunk_index"] == 1


def test_oversized_structural_section_uses_bounded_fallback() -> None:
    chunks = ChunkBuilder(chunk_size=20, overlap=5).build(
        [{"page_number": 1, "clean_content": "## 超长条款\n" + "A" * 35}]
    )

    assert len(chunks) == 3
    assert all(len(item["content"]) <= 20 for item in chunks)
