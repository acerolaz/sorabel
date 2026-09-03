from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Chunk
from app.infrastructure.postgres.mappers import apply_chunk_fields, row_to_chunk
from app.infrastructure.postgres.models import ChunkRow


class Bm25Repository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            row = await self._session.get(ChunkRow, chunk.id)
            if row is None:
                row = ChunkRow(id=chunk.id)
                self._session.add(row)
            apply_chunk_fields(row, chunk)
            # `search_vector` is a STORED generated column (migration 0002):
            # Postgres derives it from `content`. Assigning it here would be
            # rejected outright.

    async def search(
        self, query: str, top_k: int, product_ref: str | None = None
    ) -> list[tuple[Chunk, int]]:
        ts_query = func.plainto_tsquery("french", query)
        stmt = (
            select(ChunkRow)
            .where(ChunkRow.status == "active")
            .where(ChunkRow.search_vector.op("@@")(ts_query))
        )
        if product_ref is not None:
            stmt = stmt.where(ChunkRow.product_ref == product_ref)
        stmt = stmt.order_by(func.ts_rank(ChunkRow.search_vector, ts_query).desc()).limit(top_k)
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [(row_to_chunk(row), rank) for rank, row in enumerate(rows, start=1)]

    async def delete_by_document_id(self, document_id: str) -> None:
        await self._session.execute(delete(ChunkRow).where(ChunkRow.document_id == document_id))
