import json
from unittest.mock import AsyncMock, MagicMock

from app.infrastructure.azure_openai.llm_client import AzureOpenAiLlmClient


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
