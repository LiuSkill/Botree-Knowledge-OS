"""
Chat Trace Schema Tests

职责：
1. 验证问答执行 Trace 字段在 MySQL 下使用 LONGTEXT
2. 防止大体积审计 JSON 再次触发 TEXT 字节上限
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models.chat import ChatMessage  # noqa: E402
from app.models.retrieval_trace import RetrievalTrace  # noqa: E402


def test_chat_trace_fields_compile_to_longtext_for_mysql() -> None:
    """问答 Trace JSON 可能超过 64KB，MySQL 下必须使用 LONGTEXT。"""

    chat_sql = str(CreateTable(ChatMessage.__table__).compile(dialect=mysql.dialect()))
    retrieval_sql = str(CreateTable(RetrievalTrace.__table__).compile(dialect=mysql.dialect()))

    assert "agent_trace_json LONGTEXT" in chat_sql
    assert "feedback_status VARCHAR(20)" in chat_sql
    for column_name in (
        "sub_queries_json",
        "retriever_hits_json",
        "rerank_result_json",
        "citations_json",
        "trace_json",
    ):
        assert f"{column_name} LONGTEXT" in retrieval_sql
