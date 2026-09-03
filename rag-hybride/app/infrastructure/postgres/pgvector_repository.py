from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Chunk
from app.infrastructure.postgres.mappers import apply_chunk_fields, row_to_chunk
from app.infrastructure.postgres.models import ChunkRow


class PgVectorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        for chunk, embedding in zip(chunks, embeddings):
            row = await self._session.get(ChunkRow, chunk.id)
            if row is None:
                row = ChunkRow(id=chunk.id)
                self._session.add(row)
            apply_chunk_fields(row, chunk)
            row.embedding = embedding

    async def search(
        self, embedding: list[float], top_k: int, product_ref: str | None = None
    ) -> list[tuple[Chunk, int]]:
        stmt = select(ChunkRow).where(ChunkRow.status == "active")
        if product_ref is not None:
            stmt = stmt.where(ChunkRow.product_ref == product_ref)
        stmt = stmt.order_by(ChunkRow.embedding.cosine_distance(embedding)).limit(top_k)
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [(row_to_chunk(row), rank) for rank, row in enumerate(rows, start=1)]

    async def delete_by_document_id(self, document_id: str) -> None:
        await self._session.execute(delete(ChunkRow).where(ChunkRow.document_id == document_id))
