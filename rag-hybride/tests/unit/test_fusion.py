from app.domain.fusion import RankedChunk, reciprocal_rank_fusion


def test_fusion_favors_a_chunk_present_in_both_rankings():
    # Arrange
    dense_results = [
        RankedChunk(chunk_id="chunk-both", rank=3),
        RankedChunk(chunk_id="chunk-dense-only", rank=1),
    ]
    sparse_results = [
        RankedChunk(chunk_id="chunk-both", rank=2),
        RankedChunk(chunk_id="chunk-sparse-only", rank=1),
    ]

    # Act
    fused = reciprocal_rank_fusion(dense_results, sparse_results)

    # Assert
    assert fused[0][0] == "chunk-both"


def test_fusion_computes_reciprocal_rank_sum():
    # Arrange
    dense_results = [RankedChunk(chunk_id="chunk-1", rank=1)]
    sparse_results = [RankedChunk(chunk_id="chunk-1", rank=1)]

    # Act
    fused = reciprocal_rank_fusion(dense_results, sparse_results, k=60)

    # Assert
    expected_score = 1 / (60 + 1) + 1 / (60 + 1)
    assert fused[0] == ("chunk-1", expected_score)


def test_fusion_handles_empty_result_lists():
    # Arrange / Act
    fused = reciprocal_rank_fusion([], [])

    # Assert
    assert fused == []
