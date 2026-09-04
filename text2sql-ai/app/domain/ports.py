"""Abstract interfaces (ports) the application layer depends on. Implementations
live in infrastructure/ and are wired in via app/dependencies.py — the application
layer never imports a concrete adapter directly."""

from __future__ import annotations

from typing import Protocol

from app.domain.models import JudgeVerdict, SchemaTable, SqlCandidate


class SchemaRepositoryPort(Protocol):
    def get_tables(self, allowed_tables: list[str]) -> list[SchemaTable]: ...

    def all_table_names(self) -> list[str]: ...

    def all_column_names(self) -> set[str]: ...


class LLMPort(Protocol):
    async def generate(
        self,
        system_prompt: str,
        question: str,
        previous_attempt_feedback: str | None = None,
    ) -> SqlCandidate: ...


class JudgePort(Protocol):
    async def evaluate(
        self, question: str, intent_reformulation: str, sql: str
    ) -> JudgeVerdict: ...
