"""versioned document key

Replaces the composite (product_ref, document_type) primary key on `documents`
with a surrogate, version-scoped `id`, so a superseded version keeps its own
row instead of being overwritten. `chunks.document_id` becomes a real foreign
key onto it.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# Mirrors app.domain.versioning.make_document_id.
DOCUMENT_ID = "product_ref || '::' || document_type || '::' || version"


def upgrade() -> None:
    op.add_column("documents", sa.Column("id", sa.String(), nullable=True))
    op.execute(f"UPDATE documents SET id = {DOCUMENT_ID}")
    op.alter_column("documents", "id", nullable=False)

    op.drop_constraint("documents_pkey", "documents", type_="primary")
    op.create_primary_key("documents_pkey", "documents", ["id"])

    # Chunks denormalize every document field, so a parent row that the old
    # delete-then-overwrite flow lost can be rebuilt from them. Done before
    # the foreign key exists, or these chunks could not be reattached at all.
    op.execute(
        f"""
        INSERT INTO documents (
            id, product_ref, document_type, title, version,
            status, published_date, source_path, content_hash
        )
        SELECT DISTINCT ON (product_ref, document_type, version)
            {DOCUMENT_ID}, product_ref, document_type, title, version,
            status, published_date, source_path, content_hash
        FROM chunks
        ORDER BY product_ref, document_type, version, (status = 'active') DESC
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(f"UPDATE chunks SET document_id = {DOCUMENT_ID}")

    op.create_unique_constraint(
        "uq_documents_product_ref_document_type_version",
        "documents",
        ["product_ref", "document_type", "version"],
    )
    op.create_index(
        "ix_documents_ref_type_status",
        "documents",
        ["product_ref", "document_type", "status"],
    )
    # Ensure at most one active version per (product_ref, document_type) pair
    op.create_index(
        "uq_documents_ref_type_active",
        "documents",
        ["product_ref", "document_type"],
        unique=True,
        postgresql_where="status = 'active'",
    )
    op.create_foreign_key(
        "fk_chunks_document_id_documents",
        "chunks",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_chunks_document_id_documents", "chunks", type_="foreignkey")
    op.drop_index("uq_documents_ref_type_active", table_name="documents")
    op.drop_index("ix_documents_ref_type_status", table_name="documents")
    op.drop_constraint("uq_documents_product_ref_document_type_version", "documents")

    # Lossy by nature: a composite (product_ref, document_type) key cannot
    # represent more than one version, so superseded rows are discarded and the
    # active one is kept.
    op.execute(
        """
        DELETE FROM documents WHERE id NOT IN (
            SELECT DISTINCT ON (product_ref, document_type) id
            FROM documents
            ORDER BY product_ref, document_type,
                     (status = 'active') DESC, version DESC
        )
        """
    )
    op.execute("UPDATE chunks SET document_id = product_ref || '::' || document_type")

    op.drop_constraint("documents_pkey", "documents", type_="primary")
    op.create_primary_key("documents_pkey", "documents", ["product_ref", "document_type"])
    op.drop_column("documents", "id")
