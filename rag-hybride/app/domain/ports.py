from typing import Protocol

from app.domain.chunking import RawSection
from app.domain.models import Chunk, Document


class DocumentParserPort(Protocol):
    def parse(
        self, raw_bytes: bytes, document_type: str, source_path: str
    ) -> tuple[Document, list[RawSection]]: ...


class EmbeddingPort(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class VectorStorePort(Protocol):
    async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None: ...

    async def search(
        self, embedding: list[float], top_k: int, product_ref: str | None = None
    ) -> list[tuple[Chunk, int]]: ...

    async def delete_by_document_id(self, document_id: str) -> None: ...


class LexicalSearchPort(Protocol):
    async def upsert(self, chunks: list[Chunk]) -> None: ...

    async def search(
        self, query: str, top_k: int, product_ref: str | None = None
    ) -> list[tuple[Chunk, int]]: ...

    async def delete_by_document_id(self, document_id: str) -> None: ...


class RerankerPort(Protocol):
    async def score(self, query: str, chunk_text: str) -> float: ...


class LLMPort(Protocol):
    async def generate(self, query: str, cited_chunks: list[Chunk], hedge: bool) -> str: ...


class DocumentRegistryPort(Protocol):
    async def get_active_hash(self, product_ref: str, document_type: str) -> str | None: ...

    async def register(self, document: Document) -> None: ...

    async def deprecate(self, product_ref: str, document_type: str) -> None: ...
