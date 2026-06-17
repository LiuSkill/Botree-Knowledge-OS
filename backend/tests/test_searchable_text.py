"""
Searchable text tests.

验证表格 metadata 会进入 Chunk 和 PageIndex 使用的检索文本。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.knowledge.chunking.chunk_builder import ChunkBuilder  # noqa: E402
from app.knowledge.parsing.searchable_text import build_page_searchable_text  # noqa: E402
from app.services.page_index_service import PageIndexService  # noqa: E402


def make_page_with_table_metadata() -> dict:
    """构造 MinerU 表格正文只存在于 metadata.table_body 的页。"""

    return {
        "page_number": 5,
        "content": "2 Feedstock\n2.1 Black Mass",
        "blocks": [
            {"block_type": "text", "text": "2 Feedstock\n2.1 Black Mass"},
            {
                "block_type": "table",
                "text": "",
                "metadata": {
                    "table_caption": ["Black mass composition"],
                    "table_body": (
                        "<table>"
                        "<tr><td>No.</td><td>Element</td><td>Calculation in design</td></tr>"
                        "<tr><td>1</td><td>Li</td><td>4.063</td></tr>"
                        "<tr><td>2</td><td>Ni</td><td>25.581</td></tr>"
                        "</table>"
                    ),
                    "image_candidates": [{"payload_base64": "data:image/png;base64,secret"}],
                },
            },
        ],
    }


def test_build_page_searchable_text_appends_table_body() -> None:
    """页级可检索文本应包含表格单元格，但不包含图片 payload。"""

    text = build_page_searchable_text(make_page_with_table_metadata())

    assert "2.1 Black Mass" in text
    assert "Black mass composition" in text
    assert "Element" in text
    assert "Calculation in design" in text
    assert "Li" in text
    assert "Ni" in text
    assert "payload_base64" not in text
    assert "secret" not in text


def test_build_page_searchable_text_expands_rowspan_cells() -> None:
    """rowspan 合并单元格必须展开到后续行，避免表格列错位。"""

    page = {
        "page_number": 5,
        "content": "2.1 Black Mass",
        "blocks": [
            {
                "block_type": "table",
                "metadata": {
                    "table_body": (
                        "<table>"
                        "<tr><td>No.</td><td>Element</td><td>Percentage</td><td>Min</td><td>Max</td><td>Calculation in design</td></tr>"
                        "<tr><td>2</td><td>Ni</td><td>wt%</td><td rowspan=\"3\">20</td><td rowspan=\"3\">40</td><td>25.581</td></tr>"
                        "<tr><td>3</td><td>Co</td><td>wt%</td><td>3.211</td></tr>"
                        "<tr><td>4</td><td>Mn</td><td>wt%</td><td>2.993</td></tr>"
                        "</table>"
                    )
                },
            }
        ],
    }

    text = build_page_searchable_text(page)

    assert "| 2 | Ni | wt% | 20 | 40 | 25.581 |" in text
    assert "| 3 | Co | wt% | 20 | 40 | 3.211 |" in text
    assert "| 4 | Mn | wt% | 20 | 40 | 2.993 |" in text
    assert "| 3 | Co | wt% | 3.211 |" not in text


def test_chunk_builder_indexes_table_body() -> None:
    """ChunkBuilder 应使用增强后的页文本生成 chunk。"""

    chunks = ChunkBuilder(chunk_size=1000).build([make_page_with_table_metadata()])

    assert len(chunks) == 1
    assert chunks[0]["page_number"] == 5
    assert "Element" in chunks[0]["content"]
    assert "Calculation in design" in chunks[0]["content"]
    assert "Li" in chunks[0]["content"]


def test_page_index_normalize_page_indexes_table_body() -> None:
    """PageIndex 页文本应与 ChunkBuilder 一样包含表格内容。"""

    service = object.__new__(PageIndexService)
    document = SimpleNamespace(drawing_no=None)

    normalized = service._normalize_page(document, make_page_with_table_metadata(), fallback_no=5)

    assert normalized["page_no"] == 5
    assert "Element" not in normalized["page_text"]
    assert "Element" in normalized["clean_content"]
    assert "Calculation in design" in normalized["clean_content"]
    assert "Ni" in normalized["clean_content"]


def test_build_page_searchable_text_prefers_clean_content_and_clean_blocks() -> None:
    """索引用文本必须优先使用 clean_content / clean_blocks，避开原始页眉噪声。"""

    page = {
        "content": "HEADER\nRaw content",
        "clean_content": "Clean body",
        "blocks": [{"block_type": "text", "text": "HEADER", "filter_status": "filtered"}],
        "clean_blocks": [{"block_type": "text", "clean_text": "Clean body"}],
    }

    text = build_page_searchable_text(page)

    assert text == "Clean body"


def test_build_page_searchable_text_does_not_fallback_when_clean_content_empty() -> None:
    """clean_content 明确为空时代表该页已被清洗为空，不能回退到原始 content。"""

    page = {
        "content": "HEADER\nRaw content",
        "clean_content": "",
        "clean_blocks": [],
    }

    assert build_page_searchable_text(page) == ""
