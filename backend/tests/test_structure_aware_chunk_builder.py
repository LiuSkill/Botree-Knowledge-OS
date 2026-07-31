from app.knowledge.chunking.chunk_builder import ChunkBuilder


def test_adjacent_structures_are_packed_without_breaking_boundaries() -> None:
    builder = ChunkBuilder(chunk_size=80, overlap=10, rule_version="structure-v1", index_generation="gen-7")
    chunks = builder.build(
        [
            {
                "page_number": 3,
                "clean_content": "# 第一章\n泵的用途说明。\n\n1.1 启动条件\n入口阀必须开启。\n\n| 参数 | 数值 |\n| 压力 | 1.2 MPa |",
            }
        ]
    )

    combined = "\n".join(item["content"] for item in chunks)
    assert "# 第一章\n泵的用途说明。" in combined
    assert "1.1 启动条件\n入口阀必须开启。" in combined
    assert "| 参数 | 数值 |\n| 压力 | 1.2 MPa |" in combined
    assert len(chunks) == 1
    assert all(len(item["content"]) <= 80 for item in chunks)
    assert chunks[0]["metadata"]["chunk_rule_version"] == "structure-v1"
    assert chunks[0]["metadata"]["index_generation"] == "gen-7"
    assert chunks[0]["metadata"]["next_chunk_index"] is None


def test_oversized_structural_section_uses_bounded_fallback() -> None:
    chunks = ChunkBuilder(chunk_size=20, overlap=5).build(
        [{"page_number": 1, "clean_content": "## 超长条款\n" + "A" * 35}]
    )

    assert len(chunks) == 3
    assert all(len(item["content"]) <= 20 for item in chunks)


def test_mineru_table_metadata_is_indexed_when_clean_content_exists() -> None:
    chunks = ChunkBuilder(chunk_size=200).build(
        [
            {
                "page_number": 1,
                "clean_content": "1 Test results",
                "clean_blocks": [
                    {"block_type": "title", "clean_text": "1 Test results"},
                    {
                        "block_type": "table",
                        "clean_text": "",
                        "metadata": {
                            "table_caption": ["Table 1 Composition"],
                            "table_body": (
                                "<table><tr><th>Element</th><th>Content</th></tr>"
                                "<tr><td>Ni</td><td>16.73%</td></tr></table>"
                            ),
                        },
                    },
                ],
            }
        ]
    )

    combined = "\n".join(item["content"] for item in chunks)
    assert "Table 1 Composition" in combined
    assert "| Element | Content |" in combined
    assert "| Ni | 16.73% |" in combined


def test_formula_block_is_not_split_when_it_fits_chunk_limit() -> None:
    formula = "$$\n\\begin{array}{l}\n" + " \\\\\n".join(f"x_{index}=y_{index}" for index in range(18)) + "\n\\end{array}\n$$"
    assert len(formula) < 260

    chunks = ChunkBuilder(chunk_size=260, overlap=20).build(
        [
            {
                "page_number": 1,
                "clean_content": f"Formula introduction\n{formula}",
                "clean_blocks": [
                    {"block_type": "text", "clean_text": "Formula introduction"},
                    {"block_type": "formula", "clean_text": formula},
                ],
            }
        ]
    )

    formula_chunks = [item for item in chunks if "\\begin{array}" in item["content"]]
    assert len(formula_chunks) == 1
    assert formula_chunks[0]["content"].count("$$") == 2
    assert "\\end{array}" in formula_chunks[0]["content"]


def test_oversized_formula_repeats_delimiters_and_stays_bounded() -> None:
    equations = [f"x_{{{index}}}=y_{{{index}}}+z_{{{index}}}" for index in range(16)]
    formula = "$$\n\\begin{array}{l}\n" + " \\\\\n".join(equations) + "\n\\end{array}\n$$"
    chunks = ChunkBuilder(chunk_size=120, overlap=10).build(
        [
            {
                "page_number": 1,
                "clean_blocks": [{"block_type": "formula", "clean_text": formula}],
            }
        ]
    )

    assert len(chunks) > 1
    assert all(len(item["content"]) <= 120 for item in chunks)
    assert all(item["content"].count("$$") == 2 for item in chunks)
    assert all("\\begin{array}{l}" in item["content"] for item in chunks)
    assert all("\\end{array}" in item["content"] for item in chunks)
    combined = "\n".join(item["content"] for item in chunks)
    for equation in equations:
        assert combined.count(equation) == 1


def test_long_table_chunks_repeat_caption_and_header() -> None:
    rows = "".join(
        f"<tr><td>{index}</td><td>Element-{index}</td><td>{index * 10}%</td></tr>" for index in range(1, 9)
    )
    chunks = ChunkBuilder(chunk_size=115).build(
        [
            {
                "page_number": 2,
                "clean_content": "2 Results",
                "clean_blocks": [
                    {"block_type": "title", "clean_text": "2 Results"},
                    {
                        "block_type": "table",
                        "metadata": {
                            "table_caption": ["Table 2 Leaching results"],
                            "table_body": (
                                "<table><tr><th>No.</th><th>Element</th><th>Rate</th></tr>" + rows + "</table>"
                            ),
                        },
                    },
                ],
            }
        ]
    )

    table_chunks = [item for item in chunks if "| No. | Element | Rate |" in item["content"]]
    assert len(table_chunks) > 1
    assert all("Table 2 Leaching results" in item["content"] for item in table_chunks)
    assert all("| No. | Element | Rate |" in item["content"] for item in table_chunks)
    assert all(len(item["content"]) <= 115 for item in table_chunks)
    combined = "\n".join(item["content"] for item in table_chunks)
    for index in range(1, 9):
        assert combined.count(f"| {index} | Element-{index} | {index * 10}% |") == 1


def test_page_boundary_does_not_force_title_away_from_body() -> None:
    chunks = ChunkBuilder(chunk_size=100).build(
        [
            {
                "page_number": 1,
                "clean_content": "3 Conclusion",
                "clean_blocks": [{"block_type": "title", "clean_text": "3 Conclusion"}],
            },
            {
                "page_number": 2,
                "clean_content": "The experiment reached the expected recovery rate.",
                "clean_blocks": [
                    {"block_type": "text", "clean_text": "The experiment reached the expected recovery rate."}
                ],
            },
        ]
    )

    assert len(chunks) == 1
    assert chunks[0]["content"] == "3 Conclusion\nThe experiment reached the expected recovery rate."
    assert chunks[0]["page_number"] == 1
    assert chunks[0]["metadata"]["page_numbers"] == [1, 2]


def test_standalone_table_captions_bind_to_following_tables() -> None:
    chunks = ChunkBuilder(chunk_size=55).build(
        [
            {
                "page_number": 3,
                "clean_blocks": [
                    {"block_type": "text", "clean_text": "表4 95%酸用量浸出结果"},
                    {
                        "block_type": "table",
                        "metadata": {
                            "table_caption": ["表5 100%酸用量浸出结果"],
                            "table_body": (
                                "<table><tr><th>酸用量</th><th>浸出率</th></tr>"
                                "<tr><td>95%</td><td>99.24%</td></tr></table>"
                            ),
                        },
                    },
                    {
                        "block_type": "table",
                        "metadata": {
                            "table_body": (
                                "<table><tr><th>酸用量</th><th>浸出率</th></tr>"
                                "<tr><td>100%</td><td>99.60%</td></tr></table>"
                            )
                        },
                    },
                ],
            }
        ]
    )

    result_95 = next(item["content"] for item in chunks if "| 95% | 99.24% |" in item["content"])
    result_100 = next(item["content"] for item in chunks if "| 100% | 99.60% |" in item["content"])
    assert "表4 95%酸用量浸出结果" in result_95
    assert "表5 100%酸用量浸出结果" not in result_95
    assert "表5 100%酸用量浸出结果" in result_100


def test_last_structural_piece_continues_filling_chunk_window() -> None:
    chunks = ChunkBuilder(chunk_size=90).build(
        [
            {
                "page_number": 1,
                "clean_blocks": [
                    {"block_type": "text", "clean_text": "A" * 65},
                    {
                        "block_type": "table",
                        "metadata": {
                            "table_body": (
                                "<table><tr><th>Key</th><th>Value</th></tr>"
                                "<tr><td>Ni</td><td>16.73</td></tr></table>"
                            )
                        },
                    },
                    {"block_type": "text", "clean_text": "Result is valid."},
                ],
            }
        ]
    )

    table_chunk = next(item for item in chunks if "| Key | Value |" in item["content"])
    assert "| Ni | 16.73 |" in table_chunk["content"]
    assert "Result is valid." in table_chunk["content"]
    assert len(table_chunk["content"]) <= 90


def test_document_metadata_is_embedded_in_every_chunk_and_counts_toward_window() -> None:
    metadata = {
        "document_title": "BMI黑粉一次浸出实验实验报告",
        "file_name": "BMI黑粉一次浸出实验实验报告.docx",
        "project_id": 18,
    }
    chunks = ChunkBuilder(chunk_size=120).build(
        [{"page_number": 1, "clean_content": "第一段结论。\n\n" + "A" * 100}],
        document_metadata=metadata,
    )

    assert len(chunks) > 1
    assert all(item["content"].startswith("BMI黑粉一次浸出实验实验报告\n") for item in chunks)
    assert all("[文档元信息]" not in item["content"] for item in chunks)
    assert all("项目ID=" not in item["content"] for item in chunks)
    assert all("文件=" not in item["content"] for item in chunks)
    assert all(item["metadata"]["document_metadata"] == metadata for item in chunks)
    assert all(len(item["content"]) <= 120 for item in chunks)


def test_measurements_do_not_create_heading_boundaries() -> None:
    chunks = ChunkBuilder(chunk_size=80).build(
        [
            {
                "page_number": 1,
                "clean_blocks": [
                    {"block_type": "text", "clean_text": "Agitator motor"},
                    {"block_type": "text", "clean_text": "7.5 kW"},
                    {"block_type": "text", "clean_text": "Tank effective volume"},
                    {"block_type": "text", "clean_text": "10.5 m².02200×2800 mm"},
                ],
            }
        ]
    )

    assert len(chunks) == 1
    assert chunks[0]["metadata"].get("section_title") is None
    assert "Agitator motor\n7.5 kW" in chunks[0]["content"]
