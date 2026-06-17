"""
Parsed Content Cleaner Tests

职责：
1. 验证 MinerU 解析结果清洗会移除页眉、页脚、页码和目录页。
2. 验证清洗规则不会破坏表格块。
3. 验证原始解析字段会被保留，清洗结果写入 clean_* 字段。
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.knowledge.parsing.parsed_content_cleaner import ParsedContentCleaner  # noqa: E402
from app.knowledge.parsing.parsed_document import ParseSource, ParsedDocumentResult  # noqa: E402


def make_parse_result(pages: list[dict], raw_payload: dict | None = None) -> ParsedDocumentResult:
    """构造清洗器单测用解析结果。"""

    return ParsedDocumentResult(
        pages=pages,
        parser_name="mineru",
        parse_source=ParseSource(source_path="demo.pdf", source_kind="original", original_path="demo.pdf"),
        raw_payload=raw_payload,
        task_id="task-1",
        metadata={},
    )


def test_cleaner_removes_repeated_headers_footers_and_page_numbers() -> None:
    """跨页重复页眉页脚和页码应从 clean_content / clean_blocks 中移除。"""

    pages = [
        {
            "page_number": 1,
            "content": "ACME CONFIDENTIAL\n1 Scope\nReal page one content.\nPage 1 of 3",
            "blocks": [
                {"block_type": "text", "text": "ACME CONFIDENTIAL"},
                {"block_type": "text", "text": "1 Scope\nReal page one content."},
                {"block_type": "text", "text": "Page 1 of 3"},
            ],
        },
        {
            "page_number": 2,
            "content": "ACME CONFIDENTIAL\n2 Detail\nReal page two content.\nPage 2 of 3",
            "blocks": [
                {"block_type": "text", "text": "ACME CONFIDENTIAL"},
                {"block_type": "text", "text": "2 Detail\nReal page two content."},
                {"block_type": "text", "text": "Page 2 of 3"},
            ],
        },
        {
            "page_number": 3,
            "content": "ACME CONFIDENTIAL\n3 Result\nReal page three content.\nPage 3 of 3",
            "blocks": [
                {"block_type": "text", "text": "ACME CONFIDENTIAL"},
                {"block_type": "text", "text": "3 Result\nReal page three content."},
                {"block_type": "text", "text": "Page 3 of 3"},
            ],
        },
    ]

    cleaned = ParsedContentCleaner().clean_result(make_parse_result(pages))
    combined_raw_content = "\n".join(page["content"] for page in cleaned.pages)
    combined_content = "\n".join(page["clean_content"] for page in cleaned.pages)
    combined_blocks = "\n".join(block.get("clean_text", "") for page in cleaned.pages for block in page["clean_blocks"])
    summary = cleaned.metadata["content_cleaning"]

    assert "ACME CONFIDENTIAL" in combined_raw_content
    assert "ACME CONFIDENTIAL" not in combined_content
    assert "Page 1 of 3" not in combined_content
    assert "Real page two content." in combined_content
    assert "ACME CONFIDENTIAL" not in combined_blocks
    assert summary["removed_line_count"] >= 6
    assert summary["removed_block_count"] >= 6


def test_cleaner_removes_repeated_edge_header_even_when_layout_moves_to_middle() -> None:
    """MinerU 版面排序可能把页眉放到正文中间，已识别的重复页眉仍应删除。"""

    pages = [
        {
            "page_number": 1,
            "content": (
                "30 TREE\nDesign Basis\nNo. :BCE2408-PL-\n"
                "1 Plant capacity\nReal page one content.\n"
                "THIS DRAWING IS PROPERTY OF BOTREE, IT SHALL NOT BE REPRODUCED"
            ),
            "blocks": [
                {"block_type": "text", "text": "30 TREE\nDesign Basis\nNo. :BCE2408-PL-"},
                {"block_type": "text", "text": "1 Plant capacity\nReal page one content."},
            ],
        },
        {
            "page_number": 2,
            "content": (
                "2 Feedstock\nReal page two content.\n"
                "More body line 1\nMore body line 2\nMore body line 3\nMore body line 4\n"
                "30 TREE\nDesign Basis\nNo. :BCE2408-PL-\n"
                "THIS DRAWING IS PROPERTY OF BOTREE, IT SHALL NOT BE REPRODUCED"
            ),
            "blocks": [
                {
                    "block_type": "text",
                    "text": "2 Feedstock\nReal page two content.\nMore body line 1\nMore body line 2\nMore body line 3\nMore body line 4",
                },
                {"block_type": "text", "text": "30 TREE\nDesign Basis\nNo. :BCE2408-PL-"},
            ],
        },
        {
            "page_number": 3,
            "content": "30 TREE\nDesign Basis\nNo. :BCE2408-PL-\n3 Products\nReal page three content.",
            "blocks": [
                {"block_type": "text", "text": "30 TREE\nDesign Basis\nNo. :BCE2408-PL-"},
                {"block_type": "text", "text": "3 Products\nReal page three content."},
            ],
        },
    ]

    cleaned = ParsedContentCleaner().clean_result(make_parse_result(pages))
    combined_content = "\n".join(page["clean_content"] for page in cleaned.pages)
    combined_blocks = "\n".join(block.get("clean_text", "") for page in cleaned.pages for block in page["clean_blocks"])

    assert "30 TREE" not in combined_content
    assert "Design Basis" not in combined_content
    assert "No. :BCE2408-PL-" not in combined_content
    assert "PROPERTY OF BOTREE" not in combined_content
    assert "Real page two content." in combined_content
    assert "30 TREE" not in combined_blocks
    assert "Real page three content." in combined_blocks


def test_cleaner_removes_table_of_contents_page() -> None:
    """目录页应从正文和分块输入中剔除，并进入 filtered_content。"""

    pages = [
        {
            "page_number": 1,
            "content": "目录\n1 Introduction ........ 1\n2 Design Basis ........ 3\n3 Battery Limits ........ 8\n4 Appendix ........ 20",
            "blocks": [
                {"block_type": "title", "text": "目录"},
                {"block_type": "text", "text": "1 Introduction ........ 1"},
                {"block_type": "text", "text": "2 Design Basis ........ 3"},
            ],
        },
        {"page_number": 2, "content": "1 Introduction\nUseful engineering content.", "blocks": []},
    ]

    cleaned = ParsedContentCleaner().clean_result(make_parse_result(pages))
    summary = cleaned.metadata["content_cleaning"]

    assert cleaned.pages[0]["content"].startswith("目录")
    assert cleaned.pages[0]["clean_content"] == ""
    assert cleaned.pages[0]["clean_blocks"] == []
    assert "Design Basis" in cleaned.pages[0]["filtered_content"]
    assert cleaned.pages[1]["clean_content"] == "1 Introduction\nUseful engineering content."
    assert summary["removed_toc_page_numbers"] == [1]


def test_cleaner_removes_singular_content_toc_and_markdown_artifact() -> None:
    """英文单数 Content 目录页和孤立 Markdown 标记不应进入分块。"""

    pages = [
        {
            "page_number": 1,
            "content": "Content\n1 PLANT CAPACITY....3\n2 FEEDSTOCK....3\n3 PRODUCTS....7\n4 UTILITIES....9",
            "blocks": [
                {"block_type": "title", "text": "Content"},
                {"block_type": "text", "text": "1 PLANT CAPACITY....3"},
                {"block_type": "text", "text": "2 FEEDSTOCK....3"},
            ],
        },
        {
            "page_number": 2,
            "content": "#\n1 Plant capacity\nUseful engineering content.",
            "blocks": [{"block_type": "text", "text": "#\n1 Plant capacity\nUseful engineering content."}],
        },
    ]

    cleaned = ParsedContentCleaner().clean_result(make_parse_result(pages))

    assert cleaned.pages[0]["clean_content"] == ""
    assert cleaned.pages[1]["clean_content"] == "1 Plant capacity\nUseful engineering content."
    assert cleaned.metadata["content_cleaning"]["removed_toc_page_numbers"] == [1]


def test_cleaner_keeps_table_blocks_and_preserves_raw_payload() -> None:
    """表格块不能被重复行规则误判，raw_payload 必须保持 MinerU 原始结果。"""

    pages = [
        {
            "page_number": 1,
            "content": "BOTREE HEADER\nItem | Index Parameter\nNa2CO3 | >= 9.4%\n- 1 -",
            "blocks": [
                {"block_type": "text", "text": "BOTREE HEADER"},
                {"block_type": "table", "text": "Item | Index Parameter\nNa2CO3 | >= 9.4%"},
            ],
        },
        {
            "page_number": 2,
            "content": "BOTREE HEADER\nItem | Index Parameter\nNaCl | <= 0.3%\n- 2 -",
            "blocks": [
                {"block_type": "text", "text": "BOTREE HEADER"},
                {"block_type": "table", "text": "Item | Index Parameter\nNaCl | <= 0.3%"},
            ],
        },
    ]
    raw_payload = {"md_content": "BOTREE HEADER\nItem | Index Parameter\nNa2CO3 | >= 9.4%\nPage 1 of 2"}

    cleaned = ParsedContentCleaner().clean_result(make_parse_result(pages, raw_payload))

    assert cleaned.raw_payload == raw_payload
    assert "BOTREE HEADER" in cleaned.pages[0]["content"]
    assert "BOTREE HEADER" not in cleaned.pages[0]["clean_content"]
    assert "Item | Index Parameter" in cleaned.pages[0]["clean_content"]
    assert cleaned.pages[0]["clean_blocks"][0]["block_type"] == "table"
    assert "Item | Index Parameter" in cleaned.pages[0]["clean_blocks"][0]["clean_text"]
    assert "botree_cleaned_markdown" not in (cleaned.raw_payload or {})


def test_cleaner_removes_inline_toc_noise_and_keeps_body_tail() -> None:
    """MinerU inline TOC noise should be removed while preserving real body text after it."""

    toc_line = (
        "## Content ## 1 PLANT CAPACITY....3 1.1 PRODUCTION CAPACITY....3 "
        "2 FEEDSTOCK....3 2.1 BLACK MASS....3 3 PRODUCTS....7 "
        "4 UTILITIES....9 5 SITE CONDITIONS....10 6 CODES AND STANDARDS....11 "
        "7 FORMAT....12 8 ENGINEERING PHILOSOPHY....15 8.6.2 Noise....17 "
        "## # 1 Plant capacity ## 1.1 Production capacity The plant design is based on the following capacities:"
    )
    pages = [
        {
            "page_number": 1,
            "content": toc_line,
            "blocks": [{"block_type": "text", "text": toc_line}],
        }
    ]
    raw_payload = {"md_content": f"{toc_line}\n\nBlack mass Feed | Design (100%)"}

    cleaned = ParsedContentCleaner().clean_result(make_parse_result(pages, raw_payload))
    cleaned_markdown = ParsedContentCleaner().clean_markdown_text(raw_payload["md_content"])

    assert cleaned.raw_payload == raw_payload
    assert "## Content ##" not in cleaned.pages[0]["clean_content"]
    assert "FEEDSTOCK....3" not in cleaned.pages[0]["clean_content"]
    assert "# 1 Plant capacity" in cleaned.pages[0]["clean_content"]
    assert "The plant design is based on the following capacities:" in cleaned_markdown
    assert "Black mass Feed | Design (100%)" in cleaned_markdown


def test_cleaner_uses_mineru_discarded_blocks_first() -> None:
    """MinerU 已标记的 discarded_blocks 应优先进入 filtered_blocks，不进入 clean_blocks。"""

    pages = [
        {
            "page_number": 1,
            "content": "Watermark\n1 Scope\nUseful body.",
            "blocks": [
                {"id": "h1", "block_type": "text", "text": "Watermark"},
                {"id": "b1", "block_type": "text", "text": "1 Scope\nUseful body."},
            ],
            "discarded_blocks": [{"id": "h1", "block_type": "text", "text": "Watermark"}],
        }
    ]

    cleaned = ParsedContentCleaner().clean_result(make_parse_result(pages))
    clean_text = "\n".join(block.get("clean_text", "") for block in cleaned.pages[0]["clean_blocks"])
    filtered_text = cleaned.pages[0]["filtered_content"]

    assert "Useful body." in cleaned.pages[0]["clean_content"]
    assert "Watermark" not in clean_text
    assert "Watermark" in filtered_text
    assert cleaned.pages[0]["filtered_blocks"][0]["filter_reason"] == "mineru_discarded"
