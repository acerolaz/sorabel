import asyncio
import hashlib
import uuid
from dataclasses import dataclass, replace

from app.domain.chunking import chunk_sections
from app.domain.errors import UnsupportedFormatError
from app.domain.models import Chunk
from app.domain.ports import (
    DocumentParserPort,
    DocumentRegistryPort,
    EmbeddingPort,
    LexicalSearchPort,
    VectorStorePort,
)
from app.domain.versioning import make_document_id, resolve_ingest_action


@dataclass
class IngestResult:
    document_id: str
    chunk_count: int
    status: str  # "created" | "updated" | "unchanged"


@dataclass
class IngestDocumentUseCase:
    parsers: dict[str, DocumentParserPort]
    registry: DocumentRegistryPort
    embedding_port: EmbeddingPort
    vector_store: VectorStorePort
    lexical_search: LexicalSearchPort

    async def execute(
        self,
        raw_bytes: bytes,
        filename: str,
        document_type: str,
        product_ref_override: str | None = None,
    ) -> IngestResult:
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        parser = self.parsers.get(extension)
        if parser is None:
            raise UnsupportedFormatError(f"unsupported file extension: '{extension}'")

        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        document, raw_sections = parser.parse(raw_bytes, document_type, filename)
        if product_ref_override is not None:
            document = replace(
                document,
                product_ref=product_ref_override,
                id=make_document_id(product_ref_override, document_type, document.version),
            )
        document = replace(document, content_hash=content_hash)

        existing_hash = await self.registry.get_active_hash(
            document.product_ref, document.document_type
        )
        action = resolve_ingest_action(existing_hash, content_hash)

        if action == "unchanged":
            return IngestResult(document_id=document.id, chunk_count=0, status="unchanged")

        if action == "updated":
            # Clears only this version's own chunks, so re-ingesting a version
            # is idempotent. Chunks of *earlier* versions carry a different
            # document_id and survive — `deprecate` marks them superseded
            # rather than deleting them, which is what keeps an audit trail.
            await self.vector_store.delete_by_document_id(document.id)
            await self.lexical_search.delete_by_document_id(document.id)
            await self.registry.deprecate(document.product_ref, document.document_type)

        chunk_candidates = chunk_sections(raw_sections)
        chunks = [
            Chunk(
                id=str(uuid.uuid4()),
                document_id=document.id,
                content=candidate.content,
                content_type=candidate.content_type,
                title=document.title,
                product_ref=document.product_ref,
                version=document.version,
                status="active",
                document_type=document.document_type,
                published_date=document.published_date,
                content_hash=document.content_hash,
                source_path=document.source_path,
            )
            for candidate in chunk_candidates
        ]

        embeddings = await asyncio.gather(
            *[self.embedding_port.embed(chunk.content) for chunk in chunks]
        )

        # The document row must exist before its chunks: `chunks.document_id`
        # is a foreign key onto it.
        await self.registry.register(document)

        await self.vector_store.upsert(chunks, embeddings)
        await self.lexical_search.upsert(chunks)

        return IngestResult(document_id=document.id, chunk_count=len(chunks), status=action)
