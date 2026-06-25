"""add visible chat progress

Revision ID: 20260625_chat_visible_progress
Revises: 20260618_chat_message_feedback
Create Date: 2026-06-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260625_chat_visible_progress"
down_revision: str | None = "20260618_chat_message_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if _has_column("chat_messages", "progress_json"):
        return
    column_type = mysql.LONGTEXT() if op.get_bind().dialect.name == "mysql" else sa.Text()
    op.add_column(
        "chat_messages",
        sa.Column("progress_json", column_type, nullable=True, comment="用户可见处理进度JSON"),
    )


def downgrade() -> None:
    if not _has_column("chat_messages", "progress_json"):
        return
    op.drop_column("chat_messages", "progress_json")
