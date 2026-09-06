from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Identity:
    """Identité résolue depuis le JWT vérifié."""

    subject: str
    profile: str
    expires_at: datetime


@dataclass(frozen=True)
class Scope:
    """Périmètre de données autorisé pour un profil."""

    rag_collections: tuple[str, ...]
    sql_tables: tuple[str, ...]
    masked_columns: tuple[str, ...]


@dataclass(frozen=True)
class Allowed:
    scope: Scope
    rule: str


@dataclass(frozen=True)
class Denied:
    error_code: str
    rule: str


Decision = Allowed | Denied


@dataclass(frozen=True)
class AuditEntry:
    """Une ligne de journal par appel, autorisé comme refusé (E5).

    `arguments` porte la requête (question, SQL) : c'est elle qu'on audite.
    Le résultat n'y figure jamais — seul `row_count` le décrit.
    """

    timestamp: datetime
    correlation_id: str
    subject: str | None
    profile: str | None
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    decision: str = "deny"
    rule: str = ""
    backend: str | None = None
    row_count: int | None = None
    latency_ms: int | None = None
    error_code: str | None = None
