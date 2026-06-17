"""chat citation visual assets

Revision ID: 20260616_chat_citation_visual_assets
Revises: 20260616_document_version_lifecycle
Create Date: 2026-06-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260616_chat_citation_visual_assets"
down_revision: str | None = "20260616_document_version_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _has_column("chat_citations", "assets_json"):
        op.add_column("chat_citations", sa.Column("assets_json", sa.Text(), nullable=True, comment="引用关联图片资产JSON"))


def downgrade() -> None:
    if _has_column("chat_citations", "assets_json"):
        op.drop_column("chat_citations", "assets_json")
