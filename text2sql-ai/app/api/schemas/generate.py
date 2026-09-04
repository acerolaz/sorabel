"""Pydantic request/response DTOs for POST /api/v1/generate. Never reuse a domain
entity directly as an API schema — see ../../../../.claude/rules/python-hexagonal.md."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.models import GenerationOutcomeType, JudgeVerdictLabel


class GenerateRequest(BaseModel):
    question: str = Field(..., min_length=1)
    profile: str = Field(..., min_length=1)
    allowed_tables: list[str] = Field(..., min_length=1)


class GenerateResponse(BaseModel):
    """`outcome` and `judge_verdict` are typed with the domain's str enums so the
    generated OpenAPI advertises their closed set of values — two downstream consumers
    (mcp, and api-gateway through a generated C# client) branch on `outcome`. The wire
    values are unchanged: both enums are `str` enums serialized to their value."""

    outcome: GenerationOutcomeType
    sql: str | None = None
    intent_reformulation: str | None = None
    judge_verdict: JudgeVerdictLabel | None = None
    attempts: int
    message: str | None = None
