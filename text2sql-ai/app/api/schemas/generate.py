"""Pydantic request/response DTOs for POST /api/v1/generate. Never reuse a domain
entity directly as an API schema — see ../../../../.claude/rules/python-hexagonal.md."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    question: str = Field(..., min_length=1)
    profile: str = Field(..., min_length=1)
    allowed_tables: list[str] = Field(..., min_length=1)


class GenerateResponse(BaseModel):
    outcome: str
    sql: str | None = None
    intent_reformulation: str | None = None
    judge_verdict: str | None = None
    attempts: int
    message: str | None = None
