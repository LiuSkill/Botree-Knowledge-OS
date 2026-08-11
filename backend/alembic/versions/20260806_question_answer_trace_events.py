"""create question answer trace event store

Revision ID: 20260806_qa_trace_events
Revises: 20260727_index_manifest
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260806_qa_trace_events"
down_revision = "20260727_index_manifest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_answer_traces",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("user_message_id", sa.Integer(), nullable=True),
        sa.Column("assistant_message_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="running"),
        sa.Column("completeness_status", sa.String(length=30), nullable=False, server_default="partial"),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("chat_type", sa.String(length=30), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("terminal_sequence", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("trace_id", name="uq_question_answer_traces_trace_id"),
    )
    op.create_index("idx_question_answer_traces_status", "question_answer_traces", ["status"])
    op.create_index("idx_question_answer_traces_session_id", "question_answer_traces", ["session_id"])
    op.create_index("idx_question_answer_traces_user_message_id", "question_answer_traces", ["user_message_id"])
    op.create_index("idx_question_answer_traces_created_at", "question_answer_traces", ["created_at"])

    op.create_table(
        "question_answer_trace_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("parent_node_id", sa.String(length=128), nullable=True),
        sa.Column("business_stage", sa.String(length=50), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.String(length=40), nullable=False),
        sa.Column("producer", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.Text().with_variant(mysql.LONGTEXT(), "mysql"), nullable=False),
        sa.Column("payload_ref", sa.String(length=500), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("trace_id", "event_id", name="uq_question_answer_trace_event"),
    )
    op.create_index(
        "idx_question_answer_trace_events_trace_sequence",
        "question_answer_trace_events",
        ["trace_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index("idx_question_answer_trace_events_trace_sequence", table_name="question_answer_trace_events")
    op.drop_table("question_answer_trace_events")
    op.drop_index("idx_question_answer_traces_created_at", table_name="question_answer_traces")
    op.drop_index("idx_question_answer_traces_user_message_id", table_name="question_answer_traces")
    op.drop_index("idx_question_answer_traces_session_id", table_name="question_answer_traces")
    op.drop_index("idx_question_answer_traces_status", table_name="question_answer_traces")
    op.drop_table("question_answer_traces")
