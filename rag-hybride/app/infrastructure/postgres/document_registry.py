from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Document
from app.infrastructure.postgres.models import ChunkRow, DocumentRow


class PostgresDocumentRegistry:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_hash(self, product_ref: str, document_type: str) -> str | None:
        # Several versions of the same document may coexist; at most one of
        # them is active, so this cannot be a primary-key lookup.
        result = await self._session.execute(
            select(DocumentRow.content_hash)
            .where(DocumentRow.product_ref == product_ref)
            .where(DocumentRow.document_type == document_type)
            .where(DocumentRow.status == "active")
        )
        return result.scalar_one_or_none()

    async def register(self, document: Document) -> None:
        # Keyed by the version-scoped document id: a new version inserts a new
        # row and leaves the previous one in place, while re-registering the
        # same version updates it.
        row = await self._session.get(DocumentRow, document.id)
        if row is None:
            row = DocumentRow(id=document.id)
            self._session.add(row)
        row.product_ref = document.product_ref
        row.document_type = document.document_type
        row.title = document.title
        row.version = document.version
        row.status = "active"
        row.published_date = document.published_date
        row.source_path = document.source_path
        row.content_hash = document.content_hash

    async def deprecate(self, product_ref: str, document_type: str) -> None:
        # Find the currently active version to deprecate.
        # There is at most one active version per (product_ref, document_type)
        # due to the unique partial index.
        result = await self._session.execute(
            select(DocumentRow.id)
            .where(DocumentRow.product_ref == product_ref)
            .where(DocumentRow.document_type == document_type)
            .where(DocumentRow.status == "active")
        )
        active_document_id = result.scalar_one_or_none()
        if active_document_id is None:
            return  # No active version to deprecate
        
        # Mark only the active document as deprecated
        await self._session.execute(
            update(DocumentRow)
            .where(DocumentRow.id == active_document_id)
            .values(status="deprecated")
        )
        
        # Mark only chunks from that document as deprecated
        await self._session.execute(
            update(ChunkRow)
            .where(ChunkRow.document_id == active_document_id)
            .values(status="deprecated")
        )
