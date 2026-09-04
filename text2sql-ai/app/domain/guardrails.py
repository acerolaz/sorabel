"""Deterministic, generation-side defense-in-depth checks (barriers 1/3/4 of the
Text-to-SQL guardrail chain, per Text2SQL_Sorabel.md §5). Pure functions, no I/O, no
execution — the only inspection point text2sql-ai controls since it never connects to
a database."""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from app.domain.models import GuardrailViolation, SchemaTable

BLOCKED_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "TRUNCATE",
    "ALTER",
    "CREATE",
    "GRANT",
    "REVOKE",
}


def check_blocklist(sql: str) -> GuardrailViolation | None:
    """Reject SQL containing a destructive keyword as a standalone token, anywhere —
    including inside a CTE (`WITH x AS (DELETE FROM ...) ...`)."""
    tokens = {tok.text.upper() for tok in sqlglot.tokenize(sql)}
    hit = BLOCKED_KEYWORDS & tokens
    if hit:
        return GuardrailViolation(
            rule="blocklist",
            reason=f"Mot-clé interdit détecté : {', '.join(sorted(hit))}",
        )
    return None


def check_ast(sql: str, allowed_tables: list[SchemaTable]) -> GuardrailViolation | None:
    """Parse the SQL and reject anything but a single SELECT referencing only
    tables/columns present in the filtered schema.

    Heuristic: an unqualified column is checked against the union of all allowed
    tables' columns, not validated per-table — acceptable for MVP's single-table-heavy
    query shapes; a later iteration can tighten this with join-aware resolution.
    """
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
    except sqlglot.errors.ParseError as exc:
        return GuardrailViolation(rule="ast", reason=f"SQL invalide : {exc}")

    if len(statements) != 1:
        return GuardrailViolation(
            rule="ast",
            reason=f"Une seule requête SELECT est autorisée, {len(statements)} trouvée(s)",
        )

    statement = statements[0]
    if not isinstance(statement, exp.Select):
        return GuardrailViolation(
            rule="ast",
            reason=f"Seul SELECT est autorisé, type trouvé : {statement.key}",
        )

    allowed_table_names = {t.name.lower() for t in allowed_tables}
    allowed_columns = {(t.name.lower(), c.name.lower()) for t in allowed_tables for c in t.columns}
    allowed_column_names = {c.name.lower() for t in allowed_tables for c in t.columns}

    for table_expr in statement.find_all(exp.Table):
        if table_expr.name.lower() not in allowed_table_names:
            return GuardrailViolation(
                rule="ast",
                reason=f"Table non autorisée référencée : {table_expr.name}",
            )

    for column_expr in statement.find_all(exp.Column):
        column_name = column_expr.name.lower()
        table_hint = column_expr.table.lower() if column_expr.table else None
        if table_hint:
            if (table_hint, column_name) not in allowed_columns:
                return GuardrailViolation(
                    rule="ast",
                    reason=f"Colonne non autorisée référencée : {table_hint}.{column_expr.name}",
                )
        elif column_name not in allowed_column_names:
            return GuardrailViolation(
                rule="ast",
                reason=f"Colonne non autorisée référencée : {column_expr.name}",
            )

    return None


def validate(sql: str, allowed_tables: list[SchemaTable]) -> GuardrailViolation | None:
    """Run all deterministic guardrails in order; return the first violation, or None
    if the SQL passes every check."""
    violation = check_blocklist(sql)
    if violation is not None:
        return violation
    return check_ast(sql, allowed_tables)
