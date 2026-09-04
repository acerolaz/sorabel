import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest
from app.domain.errors import LlmServiceError
from app.infrastructure.azure_openai.llm_client import (
    GENERATION_RESPONSE_SCHEMA,
    AzureOpenAiLlmClient,
)


def _make_response(payload: dict) -> MagicMock:
    message = MagicMock()
    message.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


async def test_generate_returns_sql_candidate():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=_make_response(
            {
                "is_ambiguous": False,
                "clarification_needed": None,
                "is_out_of_schema": False,
                "sql": "SELECT quantity FROM stock",
                "intent_reformulation": "stock",
            }
        )
    )
    client = AzureOpenAiLlmClient(fake_client, "gen-deployment")

    candidate = await client.generate("system prompt", "quel est le stock ?")

    assert candidate.sql == "SELECT quantity FROM stock"
    assert candidate.intent_reformulation == "stock"
    assert candidate.is_ambiguous is False
    fake_client.chat.completions.create.assert_awaited_once()


async def test_generate_includes_feedback_message_when_retrying():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=_make_response(
            {
                "is_ambiguous": False,
                "clarification_needed": None,
                "is_out_of_schema": False,
                "sql": "SELECT quantity FROM stock",
                "intent_reformulation": "stock",
            }
        )
    )
    client = AzureOpenAiLlmClient(fake_client, "gen-deployment")

    await client.generate("system prompt", "question", previous_attempt_feedback="corrige X")

    _, kwargs = fake_client.chat.completions.create.call_args
    messages = kwargs["messages"]
    assert any("corrige X" in m["content"] for m in messages)


async def test_generate_detects_ambiguity():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=_make_response(
            {
                "is_ambiguous": True,
                "clarification_needed": "CA en montant ou en volume ?",
                "is_out_of_schema": False,
                "sql": None,
                "intent_reformulation": None,
            }
        )
    )
    client = AzureOpenAiLlmClient(fake_client, "gen-deployment")

    candidate = await client.generate("system prompt", "quel est le meilleur produit ?")

    assert candidate.is_ambiguous is True
    assert candidate.clarification_needed == "CA en montant ou en volume ?"
    assert candidate.sql == ""


async def test_generate_maps_out_of_schema_flag():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=_make_response(
            {
                "is_ambiguous": False,
                "clarification_needed": "le NPS n'est pas dans le schéma",
                "is_out_of_schema": True,
                "sql": None,
                "intent_reformulation": None,
            }
        )
    )
    client = AzureOpenAiLlmClient(fake_client, "gen-deployment")

    candidate = await client.generate("system prompt", "quel est le NPS ?")

    assert candidate.is_out_of_schema is True
    assert candidate.sql == ""


async def test_generation_response_schema_requires_out_of_schema_flag():
    assert "is_out_of_schema" in GENERATION_RESPONSE_SCHEMA["properties"]
    assert "is_out_of_schema" in GENERATION_RESPONSE_SCHEMA["required"]


async def test_generate_wraps_sdk_failure_in_domain_error():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        side_effect=openai.APIConnectionError(
            request=httpx.Request("POST", "https://dummy.openai.azure.com/")
        )
    )
    client = AzureOpenAiLlmClient(fake_client, "gen-deployment")

    with pytest.raises(LlmServiceError):
        await client.generate("system prompt", "question")


async def test_generate_wraps_unreadable_payload_in_domain_error():
    fake_client = MagicMock()
    response = _make_response({})
    response.choices[0].message.content = "not json at all"
    fake_client.chat.completions.create = AsyncMock(return_value=response)
    client = AzureOpenAiLlmClient(fake_client, "gen-deployment")

    with pytest.raises(LlmServiceError):
        await client.generate("system prompt", "question")


async def test_generate_wraps_missing_field_in_domain_error():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=_make_response({"sql": "SELECT 1"})
    )
    client = AzureOpenAiLlmClient(fake_client, "gen-deployment")

    with pytest.raises(LlmServiceError):
        await client.generate("system prompt", "question")
