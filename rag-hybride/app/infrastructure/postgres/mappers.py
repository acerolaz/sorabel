from app.domain.models import Chunk
from app.infrastructure.postgres.models import ChunkRow


def apply_chunk_fields(row: ChunkRow, chunk: Chunk) -> None:
    row.document_id = chunk.document_id
    row.content = chunk.content
    row.content_type = chunk.content_type
    row.title = chunk.title
    row.product_ref = chunk.product_ref
    row.version = chunk.version
    row.status = chunk.status
    row.document_type = chunk.document_type
    row.published_date = chunk.published_date
    row.content_hash = chunk.content_hash
    row.source_path = chunk.source_path


def row_to_chunk(row: ChunkRow) -> Chunk:
    return Chunk(
        id=row.id,
        document_id=row.document_id,
        content=row.content,
        content_type=row.content_type,
        title=row.title,
        product_ref=row.product_ref,
        version=row.version,
        status=row.status,
        document_type=row.document_type,
        published_date=row.published_date,
        content_hash=row.content_hash,
        source_path=row.source_path,
    )
