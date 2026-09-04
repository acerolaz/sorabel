"""Domain entities for the Text-to-SQL generation pipeline. No framework imports —
this module knows nothing about FastAPI, Azure OpenAI, or YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class SchemaColumn:
    name: str
    type: str
    comment: str
    is_primary_key: bool = False
    is_foreign_key: bool = False
    enum_values: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SchemaTable:
    name: str
    comment: str
    columns: list[SchemaColumn]


@dataclass(frozen=True)
class GenerationRequest:
    question: str
    profile: str
    allowed_tables: list[str]


@dataclass(frozen=True)
class SqlCandidate:
    sql: str
    intent_reformulation: str
    is_ambiguous: bool = False
    clarification_needed: str | None = None


class JudgeVerdictLabel(str, Enum):
    ALIGNED = "ALIGNED"
    DRIFT = "DRIFT"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class JudgeVerdict:
    verdict: JudgeVerdictLabel
    reason: str


@dataclass(frozen=True)
class GuardrailViolation:
    rule: str  # "blocklist" | "ast"
    reason: str


class GenerationOutcomeType(str, Enum):
    GENERATED = "generated"
    NEEDS_CLARIFICATION = "needs_clarification"
    REFUSED_OUT_OF_SCHEMA = "refused_out_of_schema"
    REJECTED_GUARDRAIL = "rejected_guardrail"
    REJECTED_JUDGE = "rejected_judge"


@dataclass(frozen=True)
class GenerationOutcome:
    outcome: GenerationOutcomeType
    sql: str | None = None
    intent_reformulation: str | None = None
    judge_verdict: JudgeVerdictLabel | None = None
    attempts: int = 0
    message: str | None = None
