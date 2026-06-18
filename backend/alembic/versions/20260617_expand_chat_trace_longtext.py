"""expand chat trace fields to longtext

Revision ID: 20260617_expand_chat_trace_longtext
Revises: 20260616_chat_citation_visual_assets
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260617_expand_chat_trace_longtext"
down_revision: str | None = "20260616_chat_citation_visual_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def _alter_longtext(table_name: str, column_name: str, comment: str) -> None:
    if not _is_mysql() or not _has_column(table_name, column_name):
        return
    op.alter_column(
        table_name,
        column_name,
        type_=mysql.LONGTEXT(),
        existing_nullable=True,
        existing_comment=comment,
        comment=comment,
    )


def upgrade() -> None:
    _alter_longtext("chat_messages", "agent_trace_json", "Agent执行过程JSON")
    for column_name, comment in (
        ("sub_queries_json", "查询拆解JSON"),
        ("retriever_hits_json", "各检索器命中数量JSON"),
        ("rerank_result_json", "重排结果JSON"),
        ("citations_json", "最终引用JSON"),
        ("trace_json", "LangGraph执行轨迹JSON"),
    ):
        _alter_longtext("retrieval_traces", column_name, comment)


def downgrade() -> None:
    # 不自动降级，避免 LONGTEXT 中已有的大体积审计数据被 TEXT 截断。
    pass
