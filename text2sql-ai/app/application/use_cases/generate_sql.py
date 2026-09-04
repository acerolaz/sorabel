"""Orchestrates the generation pipeline (Text2SQL_Sorabel.md §4-§9): filter schema
→ build prompt → generate → guardrails → judge → bounded self-correction retry.
Never executes SQL — that is sorabelsql-api's responsibility.

Out-of-schema refusal is deterministic only when the filtered schema is empty; the
semantic case is signalled by the model itself (`is_out_of_schema`), which replaces
the lexical pre-check of the original design — see the amendment note in
docs/superpowers/specs/2026-09-04-text2sql-ai-mvp-design.md."""

from __future__ import annotations

import logging

from app.domain.guardrails import validate as validate_guardrails
from app.domain.models import (
    GenerationOutcome,
    GenerationOutcomeType,
    GenerationRequest,
    JudgeVerdictLabel,
)
from app.domain.ports import JudgePort, LLMPort, SchemaRepositoryPort
from app.domain.prompt import build_system_prompt

MAX_ATTEMPTS = 3

logger = logging.getLogger(__name__)


class GenerateSqlUseCase:
    def __init__(
        self,
        schema_repository: SchemaRepositoryPort,
        llm: LLMPort,
        judge: JudgePort,
        business_rules: dict[str, str],
        few_shot_examples: list[dict[str, str]],
    ) -> None:
        self._schema_repository = schema_repository
        self._llm = llm
        self._judge = judge
        self._business_rules = business_rules
        self._few_shot_examples = few_shot_examples

    async def execute(self, request: GenerationRequest) -> GenerationOutcome:
        tables = self._schema_repository.get_tables(request.allowed_tables)

        if not tables:
            return self._finish(
                request,
                GenerationOutcome(
                    outcome=GenerationOutcomeType.REFUSED_OUT_OF_SCHEMA,
                    message="La question ne correspond à aucune donnée disponible pour ce profil.",
                ),
            )

        system_prompt = build_system_prompt(tables, self._business_rules, self._few_shot_examples)

        feedback: str | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            candidate = await self._llm.generate(system_prompt, request.question, feedback)

            if candidate.is_out_of_schema:
                return self._finish(
                    request,
                    GenerationOutcome(
                        outcome=GenerationOutcomeType.REFUSED_OUT_OF_SCHEMA,
                        message=(
                            "La donnée demandée n'est pas disponible dans le schéma "
                            "accessible à ce profil."
                        ),
                        attempts=attempt,
                    ),
                )

            if candidate.is_ambiguous:
                return self._finish(
                    request,
                    GenerationOutcome(
                        outcome=GenerationOutcomeType.NEEDS_CLARIFICATION,
                        message=candidate.clarification_needed,
                        attempts=attempt,
                    ),
                )

            violation = validate_guardrails(candidate.sql, tables)
            if violation is not None:
                if attempt == MAX_ATTEMPTS:
                    return self._finish(
                        request,
                        GenerationOutcome(
                            outcome=GenerationOutcomeType.REJECTED_GUARDRAIL,
                            message=violation.reason,
                            attempts=attempt,
                        ),
                    )
                feedback = (
                    f"Ta requête précédente a été rejetée ({violation.rule}) : "
                    f"{violation.reason}. Requête rejetée : {candidate.sql}. Corrige-la."
                )
                continue

            verdict = await self._judge.evaluate(
                request.question, candidate.intent_reformulation, candidate.sql
            )

            if verdict.verdict == JudgeVerdictLabel.DRIFT:
                if attempt == MAX_ATTEMPTS:
                    return self._finish(
                        request,
                        GenerationOutcome(
                            outcome=GenerationOutcomeType.REJECTED_JUDGE,
                            message=verdict.reason,
                            judge_verdict=verdict.verdict,
                            attempts=attempt,
                        ),
                    )
                feedback = (
                    f"Le juge a détecté une dérive d'intention : {verdict.reason}. "
                    f"Requête concernée : {candidate.sql}. "
                    "Régénère une requête fidèle à la question."
                )
                continue

            if verdict.verdict == JudgeVerdictLabel.UNCERTAIN:
                return self._finish(
                    request,
                    GenerationOutcome(
                        outcome=GenerationOutcomeType.NEEDS_CLARIFICATION,
                        message=verdict.reason,
                        judge_verdict=verdict.verdict,
                        attempts=attempt,
                    ),
                )

            return self._finish(
                request,
                GenerationOutcome(
                    outcome=GenerationOutcomeType.GENERATED,
                    sql=candidate.sql,
                    intent_reformulation=candidate.intent_reformulation,
                    judge_verdict=verdict.verdict,
                    attempts=attempt,
                ),
            )

        raise AssertionError("generation loop exited without returning an outcome")

    def _finish(self, request: GenerationRequest, outcome: GenerationOutcome) -> GenerationOutcome:
        logger.info(
            "text2sql_generation",
            extra={
                "profile": request.profile,
                "allowed_tables": request.allowed_tables,
                "question": request.question,
                "sql": outcome.sql,
                "outcome": outcome.outcome.value,
                "attempts": outcome.attempts,
            },
        )
        return outcome
