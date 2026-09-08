import pytest
from httpx import ASGITransport, AsyncClient

from app.application.use_cases.answer_query import AnswerQueryUseCase
from app.application.use_cases.ingest_document import IngestDocumentUseCase
from app.dependencies import get_answer_query_use_case, get_ingest_document_use_case
from app.domain.models import Chunk, Document
from app.infrastructure.parsers.markdown_parser import MarkdownParser
from app.main import app

VALID_MARKDOWN = b"""---
title: Fiche REF-8842
product_ref: REF-8842
version: "1"
published_date: 2026-01-15
---

# Caracteristiques

Tension nominale : 230V. Cet appareil est conforme aux normes en vigueur pour ce type
de produit electrique domestique standard et courant.
"""


class InMemoryRegistry:
    def __init__(self):
        self._hashes: dict[tuple[str, str], str] = {}

    async def get_active_hash(self, product_ref, document_type):
        return self._hashes.get((product_ref, document_type))

    async def register(self, document: Document):
        self._hashes[(document.product_ref, document.document_type)] = document.content_hash

    async def deprecate(self, product_ref, document_type):
        self._hashes.pop((product_ref, document_type), None)


class InMemoryIndex:
    def __init__(self):
        self.chunks: dict[str, Chunk] = {}

    async def upsert(self, chunks, embeddings=None):
        for chunk in chunks:
            self.chunks[chunk.id] = chunk

    async def search(self, query_or_embedding, top_k, product_ref=None):
        # Matches both VectorStorePort.search(embedding, top_k, product_ref) and
        # LexicalSearchPort.search(query, top_k, product_ref) positionally. Only a
        # string first argument (lexical) filters by keyword match; a vector first
        # argument (dense) just returns all active matches — sufficient for this
        # single-document acceptance flow.
        matches = [c for c in self.chunks.values() if c.status == "active"]
        if product_ref is not None:
            matches = [c for c in matches if c.product_ref == product_ref]
        if isinstance(query_or_embedding, str):
            words = query_or_embedding.lower().split()
            matches = [c for c in matches if any(w in c.content.lower() for w in words)]
        return [(c, rank) for rank, c in enumerate(matches[:top_k], start=1)]

    async def delete_by_document_id(self, document_id):
        self.chunks = {k: v for k, v in self.chunks.items() if v.document_id != document_id}


class FixedEmbeddingPort:
    async def embed(self, text: str) -> list[float]:
        return [1.0]


class AlwaysConfidentReranker:
    async def score(self, query: str, chunk_text: str) -> float:
        return 0.95


class EchoingLlm:
    async def generate(self, query, cited_chunks, hedge) -> str:
        titles = ", ".join(c.title for c in cited_chunks)
        return f"Réponse basée sur : {titles}"


def build_use_cases():
    registry = InMemoryRegistry()
    vector_store = InMemoryIndex()
    lexical_search = InMemoryIndex()
    ingest_use_case = IngestDocumentUseCase(
        parsers={"md": MarkdownParser()},
        registry=registry,
        embedding_port=FixedEmbeddingPort(),
        vector_store=vector_store,
        lexical_search=lexical_search,
    )
    answer_use_case = AnswerQueryUseCase(
        embedding_port=FixedEmbeddingPort(),
        vector_store=vector_store,
        lexical_search=lexical_search,
        reranker=AlwaysConfidentReranker(),
        llm=EchoingLlm(),
    )
    return ingest_use_case, answer_use_case


@pytest.mark.asyncio
async def test_ingested_document_is_answerable_with_citations():
    # Arrange
    ingest_use_case, answer_use_case = build_use_cases()
    app.dependency_overrides[get_ingest_document_use_case] = lambda: ingest_use_case
    app.dependency_overrides[get_answer_query_use_case] = lambda: answer_use_case

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Act — ingest
        ingest_response = await client.post(
            "/api/v1/ingest",
            data={"document_type": "datasheet"},
            files={"file": ("REF-8842.md", VALID_MARKDOWN, "text/markdown")},
        )
        # Act — query
        query_response = await client.post(
            "/api/v1/query", json={"query": "tension nominale REF-8842"}
        )

    # Assert
    assert ingest_response.status_code == 200
    assert ingest_response.json()["status"] == "created"
    assert query_response.status_code == 200
    query_data = query_response.json()
    assert query_data["refused"] is False
    assert len(query_data["citations"]) >= 1
    assert query_data["citations"][0]["product_ref"] == "REF-8842"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_out_of_corpus_question_is_explicitly_refused():
    # Arrange
    _ingest_use_case, answer_use_case = build_use_cases()
    app.dependency_overrides[get_answer_query_use_case] = lambda: answer_use_case

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Act — no document ever ingested for this use case instance
        response = await client.post(
            "/api/v1/query", json={"query": "question totalement hors corpus"}
        )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["refused"] is True
    assert data["citations"] == []

    app.dependency_overrides.clear()
