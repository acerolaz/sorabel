"""retrieval indexes and generated search_vector

Adds the two indexes the hybrid pipeline actually reads through (GIN for
lexical, HNSW for dense) and moves `chunks.search_vector` from a
repository-maintained column to a Postgres STORED generated column.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TSVECTOR_EXPRESSION = "to_tsvector('french'::regconfig, content)"


def upgrade() -> None:
    # Replace the plain column with a generated one. Dropping and re-adding is
    # safe here because the values are fully derived from `content`: Postgres
    # recomputes every row on add.
    op.drop_column("chunks", "search_vector")
    op.add_column(
        "chunks",
        sa.Column(
            "search_vector",
            TSVECTOR(),
            sa.Computed(TSVECTOR_EXPRESSION, persisted=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_chunks_search_vector_gin",
        "chunks",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": "16", "ef_construction": "64"},
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.drop_index("ix_chunks_search_vector_gin", table_name="chunks")

    op.drop_column("chunks", "search_vector")
    op.add_column("chunks", sa.Column("search_vector", TSVECTOR(), nullable=True))
