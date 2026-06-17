"""document version lifecycle fields

Revision ID: 20260616_document_version_lifecycle
Revises:
Create Date: 2026-06-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260616_document_version_lifecycle"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("document_status", sa.String(length=30), nullable=False, server_default="pending_review"))
    op.add_column("documents", sa.Column("parse_status", sa.String(length=30), nullable=False, server_default="unparsed"))
    op.add_column("documents", sa.Column("parse_started_at", sa.DateTime(), nullable=True))
    op.add_column("documents", sa.Column("parse_finished_at", sa.DateTime(), nullable=True))
    op.add_column("documents", sa.Column("parse_error", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("parse_log", sa.Text(), nullable=True))
    op.create_index("idx_documents_document_status", "documents", ["document_status"])
    op.create_index("idx_documents_parse_status", "documents", ["parse_status"])

    op.add_column("document_versions", sa.Column("file_type", sa.String(length=50), nullable=False, server_default=""))
    op.add_column("document_versions", sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("document_versions", sa.Column("version_status", sa.String(length=30), nullable=False, server_default="pending_review"))
    op.add_column("document_versions", sa.Column("parse_status", sa.String(length=30), nullable=False, server_default="unparsed"))
    op.add_column("document_versions", sa.Column("parse_started_at", sa.DateTime(), nullable=True))
    op.add_column("document_versions", sa.Column("parse_finished_at", sa.DateTime(), nullable=True))
    op.add_column("document_versions", sa.Column("parse_error", sa.Text(), nullable=True))
    op.add_column("document_versions", sa.Column("parse_log", sa.Text(), nullable=True))
    op.add_column("document_versions", sa.Column("reviewed_by", sa.Integer(), nullable=True))
    op.add_column("document_versions", sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    op.add_column("document_versions", sa.Column("review_comment", sa.Text(), nullable=True))
    op.add_column("document_versions", sa.Column("build_started_at", sa.DateTime(), nullable=True))
    op.add_column("document_versions", sa.Column("build_finished_at", sa.DateTime(), nullable=True))
    op.add_column("document_versions", sa.Column("build_error", sa.Text(), nullable=True))
    op.create_index("idx_document_versions_version_status", "document_versions", ["version_status"])
    op.create_index("idx_document_versions_parse_status", "document_versions", ["parse_status"])

    op.add_column("review_tasks", sa.Column("version_id", sa.Integer(), nullable=True))
    op.add_column("review_tasks", sa.Column("version_no", sa.Integer(), nullable=True))
    op.create_index("idx_review_tasks_version_id", "review_tasks", ["version_id"])

    op.add_column("review_logs", sa.Column("version_id", sa.Integer(), nullable=True))
    op.add_column("review_logs", sa.Column("version_no", sa.Integer(), nullable=True))

    op.add_column("index_tasks", sa.Column("version_id", sa.Integer(), nullable=True))
    op.create_index("idx_index_tasks_version_id", "index_tasks", ["version_id"])


def downgrade() -> None:
    op.drop_index("idx_index_tasks_version_id", table_name="index_tasks")
    op.drop_column("index_tasks", "version_id")

    op.drop_column("review_logs", "version_no")
    op.drop_column("review_logs", "version_id")

    op.drop_index("idx_review_tasks_version_id", table_name="review_tasks")
    op.drop_column("review_tasks", "version_no")
    op.drop_column("review_tasks", "version_id")

    op.drop_index("idx_document_versions_parse_status", table_name="document_versions")
    op.drop_index("idx_document_versions_version_status", table_name="document_versions")
    for column_name in (
        "build_error",
        "build_finished_at",
        "build_started_at",
        "review_comment",
        "reviewed_at",
        "reviewed_by",
        "parse_log",
        "parse_error",
        "parse_finished_at",
        "parse_started_at",
        "parse_status",
        "version_status",
        "file_size",
        "file_type",
    ):
        op.drop_column("document_versions", column_name)

    op.drop_index("idx_documents_parse_status", table_name="documents")
    op.drop_index("idx_documents_document_status", table_name="documents")
    for column_name in ("parse_log", "parse_error", "parse_finished_at", "parse_started_at", "parse_status", "document_status"):
        op.drop_column("documents", column_name)
