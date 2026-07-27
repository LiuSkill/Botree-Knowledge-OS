"""add atomic index publication manifest

Revision ID: 20260727_index_manifest
Revises: 20260727_multimodal_admission
"""

from alembic import op
import sqlalchemy as sa

revision = "20260727_index_manifest"
down_revision = "20260727_multimodal_admission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "index_publication_manifests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("knowledge_base_id", sa.Integer(), sa.ForeignKey("knowledge_bases.id"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("index_generation", sa.String(120), nullable=False),
        sa.Column("publication_token", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="staging"),
        sa.Column("coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("partial_coverage", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("required_json", sa.Text(), nullable=False),
        sa.Column("completed_json", sa.Text(), nullable=False),
        sa.Column("missing_json", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_index_manifest_document_version", "index_publication_manifests", ["document_id", "version_no"])
    op.create_index("idx_index_manifest_generation_status", "index_publication_manifests", ["index_generation", "status"])


def downgrade() -> None:
    op.drop_index("idx_index_manifest_generation_status", table_name="index_publication_manifests")
    op.drop_index("idx_index_manifest_document_version", table_name="index_publication_manifests")
    op.drop_table("index_publication_manifests")
