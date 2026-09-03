from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from app.config import Settings
from app.domain.errors import EmbeddingServiceError
from app.domain.models import Chunk
from app.infrastructure.azure_openai.llm_client import AzureLlmClient

CHUNK = Chunk(
    id="chunk-1",
    document_id="REF-1",
    content="Tension nominale : 230V",
    content_type="text",
    title="Fiche REF-1",
    product_ref="REF-1",
    version="1",
    status="active",
    document_type="datasheet",
    published_date=date(2026, 1, 1),
    content_hash="h",
    source_path="p",
)


def make_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        azure_openai_api_key="key",
        azure_openai_endpoint="https://example.openai.azure.com/",
        azure_openai_embedding_deployment="text-embedding-3-large",
        azure_openai_chat_deployment="gpt-4o",
    )


@pytest.mark.asyncio
async def test_generate_returns_the_completion_text_and_includes_cited_content():
    # Arrange
    with patch("app.infrastructure.azure_openai.llm_client.AsyncAzureOpenAI") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Réponse générée."))]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        client = AzureLlmClient(make_settings())

        # Act
        text = await client.generate("tension supportée ?", [CHUNK], hedge=False)

        # Assert
        assert text == "Réponse générée."
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        user_message = call_kwargs["messages"][1]["content"]
        assert "230V" in user_message


@pytest.mark.asyncio
async def test_hedge_true_adds_a_cautious_instruction_to_the_system_prompt():
    # Arrange
    with patch("app.infrastructure.azure_openai.llm_client.AsyncAzureOpenAI") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Réponse prudente."))]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        client = AzureLlmClient(make_settings())

        # Act
        await client.generate("question", [CHUNK], hedge=True)

        # Assert
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        system_message = call_kwargs["messages"][0]["content"]
        assert "prudente" in system_message


@pytest.mark.asyncio
async def test_generate_wraps_openai_errors_as_embedding_service_error():
    # Arrange
    with patch("app.infrastructure.azure_openai.llm_client.AsyncAzureOpenAI") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai.APIConnectionError(request=MagicMock())
        )
        client = AzureLlmClient(make_settings())

        # Act / Assert
        with pytest.raises(EmbeddingServiceError):
            await client.generate("question", [CHUNK], hedge=False)
