"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-02
"""

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

from app.infrastructure.postgres.models import EMBEDDING_DIM

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("product_ref", sa.String(), primary_key=True),
        sa.Column("document_type", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=False),
        sa.Column("source_path", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
    )
    op.create_index("ix_documents_status", "documents", ["status"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("product_ref", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("source_path", sa.String(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("search_vector", TSVECTOR(), nullable=True),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_product_ref", "chunks", ["product_ref"])
    op.create_index("ix_chunks_status", "chunks", ["status"])


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("documents")
    # The `vector` extension is deliberately left installed: it is
    # database-wide, may be shared with other schemas, and dropping it fails
    # as soon as anything outside this migration depends on it.
