"""Azure OpenAI adapter implementing JudgePort (Text2SQL_Sorabel.md §9) — a second,
separate LLM call whose only role is to judge alignment between the question and the
generated SQL. Never generates SQL itself."""

from __future__ import annotations

import json
from typing import Any, cast

from openai import AsyncAzureOpenAI

from app.domain.models import JudgeVerdict, JudgeVerdictLabel

JUDGE_SYSTEM_PROMPT = (
    "Tu es un juge chargé de vérifier qu'une requête SQL générée par un autre "
    "modèle répond fidèlement à la question posée, sans dérive. Tu ne génères "
    "jamais de SQL toi-même. Réponds uniquement par le JSON demandé."
)

JUDGE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["ALIGNED", "DRIFT", "UNCERTAIN"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}


class AzureOpenAiJudgeClient:
    def __init__(self, client: AsyncAzureOpenAI, deployment: str) -> None:
        self._client = client
        self._deployment = deployment

    async def evaluate(self, question: str, intent_reformulation: str, sql: str) -> JudgeVerdict:
        user_content = (
            f"Question originale : {question}\n"
            f"Reformulation de l'intention : {intent_reformulation}\n"
            f"Requête SQL générée : {sql}"
        )
        response = await self._client.chat.completions.create(
            model=self._deployment,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "judge_verdict", "schema": JUDGE_RESPONSE_SCHEMA},
            },
        )
        content = cast(str, response.choices[0].message.content)
        payload_any = json.loads(content)
        payload = cast(dict[str, Any], payload_any)

        return JudgeVerdict(verdict=JudgeVerdictLabel(payload["verdict"]), reason=payload["reason"])
