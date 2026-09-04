"""Azure OpenAI adapter implementing LLMPort — the SQL generator. Structured JSON
output avoids parsing free-text SQL out of prose."""

from __future__ import annotations

import json
from typing import Any, cast

import openai
from openai import AsyncAzureOpenAI
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionDeveloperMessageParam,
    ChatCompletionFunctionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)

from app.domain.errors import LlmServiceError
from app.domain.models import SqlCandidate

GENERATION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_ambiguous": {"type": "boolean"},
        "clarification_needed": {"type": ["string", "null"]},
        "is_out_of_schema": {"type": "boolean"},
        "sql": {"type": ["string", "null"]},
        "intent_reformulation": {"type": ["string", "null"]},
    },
    "required": [
        "is_ambiguous",
        "clarification_needed",
        "is_out_of_schema",
        "sql",
        "intent_reformulation",
    ],
    "additionalProperties": False,
}


class AzureOpenAiLlmClient:
    def __init__(self, client: AsyncAzureOpenAI, deployment: str) -> None:
        self._client = client
        self._deployment = deployment

    async def generate(
        self,
        system_prompt: str,
        question: str,
        previous_attempt_feedback: str | None = None,
    ) -> SqlCandidate:
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if previous_attempt_feedback:
            messages.append({"role": "system", "content": previous_attempt_feedback})
        messages.append({"role": "user", "content": question})

        try:
            response = await self._client.chat.completions.create(
                model=self._deployment,
                messages=cast(
                    list[
                        ChatCompletionDeveloperMessageParam
                        | ChatCompletionSystemMessageParam
                        | ChatCompletionUserMessageParam
                        | ChatCompletionAssistantMessageParam
                        | ChatCompletionToolMessageParam
                        | ChatCompletionFunctionMessageParam
                    ],
                    messages,
                ),
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "sql_generation", "schema": GENERATION_RESPONSE_SCHEMA},
                },
            )
        except openai.OpenAIError as exc:
            raise LlmServiceError(f"appel de génération échoué : {exc}") from exc

        # json.JSONDecodeError is a ValueError; TypeError covers a null content, and
        # IndexError/KeyError a response missing a choice or a required field.
        try:
            content = cast(str, response.choices[0].message.content)
            payload = cast(dict[str, Any], json.loads(content))
            return SqlCandidate(
                sql=payload["sql"] or "",
                intent_reformulation=payload["intent_reformulation"] or "",
                is_ambiguous=payload["is_ambiguous"],
                clarification_needed=payload["clarification_needed"],
                is_out_of_schema=payload["is_out_of_schema"],
            )
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise LlmServiceError("réponse de génération illisible") from exc
