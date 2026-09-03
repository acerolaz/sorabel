from datetime import date

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.models import Chunk
from app.domain.versioning import make_document_id
from app.infrastructure.postgres.models import Base, ChunkRow
from app.infrastructure.postgres.pgvector_repository import PgVectorRepository


@pytest_asyncio.fixture
async def db_session(postgres_container):
    # Override the default 1536-dim embedding column with a 2-dim one for fast, readable
    # assertions in this file only. ChunkRow.__table__ is shared, process-wide state, so we
    # must restore the original type afterward or it leaks into every other test file that
    # touches ChunkRow for the rest of the pytest session.
    original_type = ChunkRow.__table__.columns["embedding"].type
    try:
        ChunkRow.__table__.columns["embedding"].type = Vector(2)
        engine = create_async_engine(postgres_container.get_connection_url())
        async with engine.begin() as conn:
            await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            yield session
            await session.rollback()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
    finally:
        ChunkRow.__table__.columns["embedding"].type = original_type


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
async def test_upsert_then_search_returns_closest_chunk_first(db_session, given_parent_documents):
    # Arrange
    repo = PgVectorRepository(db_session)
    chunk_close = make_chunk("chunk-close", "REF-1", "Tension nominale 230V")
    chunk_far = make_chunk("chunk-far", "REF-2", "Procédure de retour produit")
    await given_parent_documents(chunk_close, chunk_far)
    await repo.upsert([chunk_close, chunk_far], [[1.0, 0.0], [0.0, 1.0]])

    # Act
    results = await repo.search(embedding=[1.0, 0.0], top_k=2)

    # Assert
    assert results[0][0].id == "chunk-close"
    assert results[0][1] == 1


@pytest.mark.asyncio
async def test_search_can_be_scoped_to_a_product_ref(db_session, given_parent_documents):
    # Arrange
    repo = PgVectorRepository(db_session)
    chunk_a = make_chunk("chunk-a", "REF-A", "contenu A")
    chunk_b = make_chunk("chunk-b", "REF-B", "contenu B")
    await given_parent_documents(chunk_a, chunk_b)
    await repo.upsert([chunk_a, chunk_b], [[1.0, 0.0], [1.0, 0.0]])

    # Act
    results = await repo.search(embedding=[1.0, 0.0], top_k=10, product_ref="REF-A")

    # Assert
    assert len(results) == 1
    assert results[0][0].product_ref == "REF-A"


@pytest.mark.asyncio
async def test_delete_by_document_id_removes_its_chunks(db_session, given_parent_documents):
    # Arrange
    repo = PgVectorRepository(db_session)
    chunk = make_chunk("chunk-x", "REF-X", "à supprimer")
    await given_parent_documents(chunk)
    await repo.upsert([chunk], [[0.5, 0.5]])

    # Act
    await repo.delete_by_document_id(chunk.document_id)
    results = await repo.search(embedding=[0.5, 0.5], top_k=10)

    # Assert
    assert results == []
