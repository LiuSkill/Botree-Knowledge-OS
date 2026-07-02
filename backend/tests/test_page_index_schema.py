"""
PageIndex Schema Tests

职责：
1. 验证页级解析长文本字段在 MySQL 下使用 LONGTEXT
2. 防止整页表格/OCR 文本再次触发 TEXT 字节上限
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models.page_index import DocumentPage, DocumentPageBlock, PageIndex  # noqa: E402


def test_page_index_text_fields_compile_to_longtext_for_mysql() -> None:
    """页级解析文本可能超过 64KB，MySQL 下必须使用 LONGTEXT。"""

    page_sql = str(CreateTable(DocumentPage.__table__).compile(dialect=mysql.dialect()))
    block_sql = str(CreateTable(DocumentPageBlock.__table__).compile(dialect=mysql.dialect()))
    index_sql = str(CreateTable(PageIndex.__table__).compile(dialect=mysql.dialect()))

    for column_name in (
        "page_text",
        "clean_content",
        "filtered_content",
        "cleaning_metadata_json",
        "corrected_text",
    ):
        assert f"{column_name} LONGTEXT" in page_sql

    for column_name in ("text", "clean_text", "metadata_json"):
        assert f"{column_name} LONGTEXT" in block_sql

    assert "index_text LONGTEXT" in index_sql
