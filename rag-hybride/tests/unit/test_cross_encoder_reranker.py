from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.reranker.cross_encoder_reranker import CrossEncoderReranker


@pytest.mark.asyncio
async def test_score_normalizes_raw_logit_to_zero_one_range():
    # Arrange
    patch_path = "app.infrastructure.reranker.cross_encoder_reranker.CrossEncoder"
    with patch(patch_path) as mock_cross_encoder_cls:
        mock_model = MagicMock()
        mock_model.predict.return_value = [0.0]
        mock_cross_encoder_cls.return_value = mock_model
        reranker = CrossEncoderReranker()

        # Act
        score = await reranker.score("tension supportée ?", "Tension nominale : 230V")

        # Assert
        assert score == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_high_raw_logit_scores_close_to_one():
    # Arrange
    patch_path = "app.infrastructure.reranker.cross_encoder_reranker.CrossEncoder"
    with patch(patch_path) as mock_cross_encoder_cls:
        mock_model = MagicMock()
        mock_model.predict.return_value = [10.0]
        mock_cross_encoder_cls.return_value = mock_model
        reranker = CrossEncoderReranker()

        # Act
        score = await reranker.score("query", "text")

        # Assert
        assert score > 0.99
