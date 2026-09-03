from collections.abc import Callable, Coroutine
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.domain.models import Chunk
from app.infrastructure.postgres.models import Base, DocumentRow


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as container:
        yield container


@pytest_asyncio.fixture
async def db_session(postgres_container) -> AsyncSession:
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


@pytest.fixture
def given_parent_documents(
    db_session: AsyncSession,
) -> Callable[..., Coroutine[Any, Any, None]]:
    """Create the `documents` rows that `chunks.document_id` points at.

    `chunks.document_id` is a foreign key, so a test that writes chunks
    directly has to supply their parent document — the ingestion use case
    registers it before indexing anything.
    """

    async def _given(*chunks: Chunk) -> None:
        for document_id in dict.fromkeys(chunk.document_id for chunk in chunks):
            source = next(chunk for chunk in chunks if chunk.document_id == document_id)
            db_session.add(
                DocumentRow(
                    id=document_id,
                    product_ref=source.product_ref,
                    document_type=source.document_type,
                    title=source.title,
                    version=source.version,
                    status=source.status,
                    published_date=source.published_date,
                    source_path=source.source_path,
                    content_hash=source.content_hash,
                )
            )
        await db_session.flush()

    return _given
