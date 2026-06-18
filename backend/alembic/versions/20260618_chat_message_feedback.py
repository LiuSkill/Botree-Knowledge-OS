"""add chat message feedback status

Revision ID: 20260618_chat_message_feedback
Revises: 20260617_seed_task_model_configs
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260618_chat_message_feedback"
down_revision: str | None = "20260617_seed_task_model_configs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if _has_column("chat_messages", "feedback_status"):
        return
    op.add_column(
        "chat_messages",
        sa.Column("feedback_status", sa.String(length=20), nullable=True, comment="回答反馈状态：like/dislike"),
    )


def downgrade() -> None:
    if not _has_column("chat_messages", "feedback_status"):
        return
    op.drop_column("chat_messages", "feedback_status")
