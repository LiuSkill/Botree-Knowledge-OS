"""add multimodal index admission fields

Revision ID: 20260727_multimodal_admission
Revises: 20260721_table_sensitive_rules
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260727_multimodal_admission"
down_revision: str | None = "20260721_table_sensitive_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in ("document_pages", "document_page_blocks"):
        op.add_column(
            table_name,
            sa.Column("index_admission_status", sa.String(length=30), nullable=False, server_default="waiting_correction"),
        )
        op.add_column(table_name, sa.Column("index_admission_reason_json", sa.Text(), nullable=True))
        op.add_column(table_name, sa.Column("text_quality_score", sa.Integer(), nullable=False, server_default="0"))
        op.create_index(f"idx_{table_name}_admission", table_name, ["index_admission_status"])


def downgrade() -> None:
    for table_name in ("document_page_blocks", "document_pages"):
        op.drop_index(f"idx_{table_name}_admission", table_name=table_name)
        op.drop_column(table_name, "text_quality_score")
        op.drop_column(table_name, "index_admission_reason_json")
        op.drop_column(table_name, "index_admission_status")
