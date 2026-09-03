from datetime import date

import pytest

from app.domain.models import Chunk
from app.domain.versioning import make_document_id
from app.infrastructure.postgres.bm25_repository import Bm25Repository


def make_chunk(chunk_id: str, product_ref: str, content: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        document_id=make_document_id(product_ref, "datasheet", "1"),
        content=content,
        content_type="text",
        title=f"Fiche {product_ref}",
        product_ref=product_ref,
        version="1",
        status="active",
        document_type="datasheet",
        published_date=date(2026, 1, 1),
        content_hash="h",
        source_path="p",
    )


@pytest.mark.asyncio
async def test_upsert_then_search_matches_on_exact_reference_token(
    db_session, given_parent_documents
):
    # Arrange
    repo = Bm25Repository(db_session)
    chunk_ref = make_chunk("chunk-ref", "REF-8842", "La reference REF-8842 supporte 230V")
    chunk_other = make_chunk("chunk-other", "REF-9000", "Un autre produit sans rapport")
    await given_parent_documents(chunk_ref, chunk_other)
    await repo.upsert([chunk_ref, chunk_other])

    # Act
    results = await repo.search("REF-8842", top_k=5)

    # Assert
    assert results[0][0].id == "chunk-ref"


@pytest.mark.asyncio
async def test_search_can_be_scoped_to_a_product_ref(db_session, given_parent_documents):
    # Arrange
    repo = Bm25Repository(db_session)
    chunk_a = make_chunk("chunk-a", "REF-A", "tension nominale 230V")
    chunk_b = make_chunk("chunk-b", "REF-B", "tension nominale 230V")
    await given_parent_documents(chunk_a, chunk_b)
    await repo.upsert([chunk_a, chunk_b])

    # Act
    results = await repo.search("tension", top_k=10, product_ref="REF-A")

    # Assert
    assert len(results) == 1
    assert results[0][0].product_ref == "REF-A"


@pytest.mark.asyncio
async def test_delete_by_document_id_removes_its_chunks(db_session, given_parent_documents):
    # Arrange
    repo = Bm25Repository(db_session)
    chunk = make_chunk("chunk-x", "REF-X", "contenu a supprimer")
    await given_parent_documents(chunk)
    await repo.upsert([chunk])

    # Act
    await repo.delete_by_document_id(chunk.document_id)
    results = await repo.search("contenu", top_k=10)

    # Assert
    assert results == []
