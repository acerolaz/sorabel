from datetime import date

import pytest

from app.application.use_cases.answer_query import AnswerQueryUseCase
from app.domain.models import Chunk

CHUNK_A = Chunk(
    id="chunk-a",
    document_id="REF-8842",
    content="Tension nominale : 230V",
    content_type="text",
    title="Fiche REF-8842",
    product_ref="REF-8842",
    version="1",
    status="active",
    document_type="datasheet",
    published_date=date(2026, 1, 1),
    content_hash="h",
    source_path="p",
)
CHUNK_B = Chunk(
    id="chunk-b",
    document_id="REF-9000",
    content="Autre fiche non pertinente",
    content_type="text",
    title="Fiche REF-9000",
    product_ref="REF-9000",
    version="1",
    status="active",
    document_type="datasheet",
    published_date=date(2026, 1, 1),
    content_hash="h2",
    source_path="p2",
)


class FakeEmbeddingPort:
    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2]


class FakeVectorStore:
    def __init__(self, results: list[tuple[Chunk, int]]):
        self._results = results

    async def search(self, embedding, top_k, product_ref=None):
        return self._results

    async def upsert(self, chunks, embeddings):
        raise NotImplementedError

    async def delete_by_document_id(self, document_id):
        raise NotImplementedError


class FakeLexicalSearch:
    def __init__(self, results: list[tuple[Chunk, int]]):
        self._results = results

    async def search(self, query, top_k, product_ref=None):
        return self._results

    async def upsert(self, chunks):
        raise NotImplementedError

    async def delete_by_document_id(self, document_id):
        raise NotImplementedError


class FakeReranker:
    def __init__(self, scores: dict[str, float]):
        self._scores = scores

    async def score(self, query: str, chunk_text: str) -> float:
        for chunk in (CHUNK_A, CHUNK_B):
            if chunk.content == chunk_text:
                return self._scores.get(chunk.id, 0.0)
        return 0.0


class FakeLlm:
    async def generate(self, query, cited_chunks, hedge) -> str:
        return "Réponse générée à partir des extraits cités."


@pytest.mark.asyncio
async def test_high_confidence_result_generates_answer_with_citations():
    # Arrange
    use_case = AnswerQueryUseCase(
        embedding_port=FakeEmbeddingPort(),
        vector_store=FakeVectorStore([(CHUNK_A, 1)]),
        lexical_search=FakeLexicalSearch([(CHUNK_A, 1)]),
        reranker=FakeReranker({"chunk-a": 0.9}),
        llm=FakeLlm(),
    )

    # Act
    answer = await use_case.execute("tension supportée par REF-8842 ?")

    # Assert
    assert answer.confidence == "high"
    assert len(answer.citations) == 1
    assert answer.citations[0].product_ref == "REF-8842"


@pytest.mark.asyncio
async def test_low_confidence_result_hedges_but_still_answers():
    # Arrange
    use_case = AnswerQueryUseCase(
        embedding_port=FakeEmbeddingPort(),
        vector_store=FakeVectorStore([(CHUNK_A, 1)]),
        lexical_search=FakeLexicalSearch([]),
        reranker=FakeReranker({"chunk-a": 0.5}),
        llm=FakeLlm(),
    )

    # Act
    answer = await use_case.execute("question ambiguë")

    # Assert
    assert answer.confidence == "low"
    assert len(answer.citations) == 1


@pytest.mark.asyncio
async def test_below_threshold_refuses_without_calling_llm():
    # Arrange
    class ExplodingLlm:
        async def generate(self, query, cited_chunks, hedge):
            raise AssertionError("LLM must not be called on refusal")

    use_case = AnswerQueryUseCase(
        embedding_port=FakeEmbeddingPort(),
        vector_store=FakeVectorStore([(CHUNK_B, 1)]),
        lexical_search=FakeLexicalSearch([]),
        reranker=FakeReranker({"chunk-b": 0.1}),
        llm=ExplodingLlm(),
    )

    # Act
    answer = await use_case.execute("question hors corpus")

    # Assert
    assert answer.confidence == "refused"
    assert answer.citations == []


@pytest.mark.asyncio
async def test_no_retrieval_results_refuses():
    # Arrange
    use_case = AnswerQueryUseCase(
        embedding_port=FakeEmbeddingPort(),
        vector_store=FakeVectorStore([]),
        lexical_search=FakeLexicalSearch([]),
        reranker=FakeReranker({}),
        llm=FakeLlm(),
    )

    # Act
    answer = await use_case.execute("question sans résultat")

    # Assert
    assert answer.confidence == "refused"
