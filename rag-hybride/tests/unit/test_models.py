from datetime import date

from app.domain.models import Answer, Chunk, RetrievalResult


def test_chunk_carries_all_required_citation_metadata():
    # Arrange / Act
    chunk = Chunk(
        id="chunk-1",
        document_id="REF-8842",
        content="Tension nominale : 230V",
        content_type="text",
        title="Fiche REF-8842",
        product_ref="REF-8842",
        version="2",
        status="active",
        document_type="datasheet",
        published_date=date(2026, 1, 15),
        content_hash="abc123",
        source_path="corpus/REF-8842.md",
    )

    # Assert
    assert chunk.product_ref == "REF-8842"
    assert chunk.content_type == "text"


def test_answer_with_no_citations_is_a_refusal_shape():
    # Arrange / Act
    answer = Answer(
        text="Je ne trouve pas cette information dans le corpus.",
        citations=[],
        confidence="refused",
    )

    # Assert
    assert answer.citations == []
    assert answer.confidence == "refused"


def test_retrieval_result_holds_both_ranks_and_scores():
    # Arrange
    chunk = Chunk(
        id="chunk-1",
        document_id="doc-1",
        content="x",
        content_type="text",
        title="t",
        product_ref="REF-1",
        version="1",
        status="active",
        document_type="datasheet",
        published_date=date(2026, 1, 1),
        content_hash="h",
        source_path="p",
    )

    # Act
    result = RetrievalResult(chunk=chunk, dense_rank=1, sparse_rank=None, fused_score=0.016)

    # Assert
    assert result.rerank_score is None
    assert result.sparse_rank is None
