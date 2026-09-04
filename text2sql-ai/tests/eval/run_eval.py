"""Manual evaluation harness — replays the golden dataset against the real
generation pipeline (real Azure OpenAI calls, never executing SQL) and reports a
match rate per category (Text2SQL_Sorabel.md §2). Not wired into CI; run manually:

    python tests/eval/run_eval.py
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path

import sqlglot
from app.application.use_cases.generate_sql import GenerateSqlUseCase
from app.dependencies import (
    get_azure_client,
    get_business_rules,
    get_few_shot_examples,
    get_schema_repository,
    get_settings,
)
from app.domain.models import GenerationOutcomeType, GenerationRequest
from app.infrastructure.azure_openai.judge_client import (
    AzureOpenAiJudgeClient,
)
from app.infrastructure.azure_openai.llm_client import AzureOpenAiLlmClient

DATASET_PATH = Path(__file__).parent / "golden_dataset.jsonl"


def _normalize(sql: str) -> str:
    return sqlglot.parse_one(sql, dialect="postgres").sql(
        dialect="postgres", normalize=True
    )


def _sql_matches(generated: str, target: str) -> bool:
    try:
        return _normalize(generated) == _normalize(target)
    except sqlglot.errors.ParseError:
        return False


async def main() -> None:
    settings = get_settings()
    client = get_azure_client()
    use_case = GenerateSqlUseCase(
        schema_repository=get_schema_repository(),
        llm=AzureOpenAiLlmClient(client, settings.azure_openai_deployment_generator),
        judge=AzureOpenAiJudgeClient(client, settings.azure_openai_deployment_judge),
        business_rules=get_business_rules(),
        few_shot_examples=get_few_shot_examples(),
    )

    entries = [
        json.loads(line) for line in DATASET_PATH.read_text().splitlines() if line.strip()
    ]

    results_by_category: dict[str, list[bool]] = defaultdict(list)

    for entry in entries:
        outcome = await use_case.execute(
            GenerationRequest(
                question=entry["question"],
                profile="eval",
                allowed_tables=entry["allowed_tables"],
            )
        )
        category = entry["category"]

        if category == "hors_schema":
            passed = outcome.outcome == GenerationOutcomeType.REFUSED_OUT_OF_SCHEMA
        elif category == "ambigu":
            passed = outcome.outcome == GenerationOutcomeType.NEEDS_CLARIFICATION
        elif category == "recurrent":
            passed = (
                outcome.outcome == GenerationOutcomeType.GENERATED
                and _sql_matches(outcome.sql or "", entry["target_sql"])
            )
        else:
            raise ValueError(f"catégorie inconnue : {category}")

        results_by_category[category].append(passed)
        print(f"[{'PASS' if passed else 'FAIL'}] ({category}) {entry['question']}")

    print("\n--- Résumé ---")
    for category, results in results_by_category.items():
        rate = sum(results) / len(results) * 100 if results else 0.0
        print(f"{category}: {sum(results)}/{len(results)} ({rate:.0f}%)")


if __name__ == "__main__":
    asyncio.run(main())
