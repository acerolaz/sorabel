# Text-to-SQL AI MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `text2sql-ai` MVP: one FastAPI endpoint that turns a natural-language
question + a profile's allowed tables into a read-only SQL candidate, validated by
generation-side defense-in-depth (blocklist, AST, LLM-as-judge) with bounded
self-correction — never executing the SQL.

**Architecture:** Hexagonal (`domain/` → `application/` → `infrastructure/`/`api/`).
Domain holds pure logic (models, guardrails, prompt assembly) with zero framework
imports. `GenerateSqlUseCase` orchestrates via three ports (`SchemaRepositoryPort`,
`LLMPort`, `JudgePort`), implemented by a YAML-backed schema repository and two Azure
OpenAI adapters. FastAPI's `api/` layer is a thin translation to/from HTTP.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, `sqlglot` (SQL AST validation),
`openai` SDK (`AsyncAzureOpenAI`), PyYAML, pytest + pytest-asyncio + httpx.

**Spec:** `text2sql-ai/docs/superpowers/specs/2026-09-04-text2sql-ai-mvp-design.md`

## Global Constraints

- No response envelope; `snake_case` JSON fields; routes under `/api/v1/` (`../../.claude/rules/api-contracts.md`).
- No broad `except Exception` anywhere — catch specific exception types only.
- `domain/` has zero imports from FastAPI, SQLAlchemy, or any SDK.
- Every generation outcome (including rejections/refusals) is logged with: profile, `allowed_tables`, question, generated SQL (if any), outcome, attempt count — never the judge/guardrail raw LLM response beyond its structured verdict.
- Bounded self-correction retry budget is **shared** across guardrail and judge failures: max 3 total generation attempts, not 3 per check.
- Type hints (PEP 484) required on all functions.
- All commands in this plan run from the `text2sql-ai/` directory unless stated otherwise.

---

### Task 1: Domain models

**Files:**
- Create: `text2sql-ai/app/__init__.py` (empty)
- Create: `text2sql-ai/app/domain/__init__.py` (empty)
- Create: `text2sql-ai/app/domain/models.py`
- Test: `text2sql-ai/tests/__init__.py` (empty)
- Test: `text2sql-ai/tests/unit/__init__.py` (empty)
- Test: `text2sql-ai/tests/unit/test_models.py`

**Interfaces:**
- Produces: `SchemaColumn(name, type, comment, is_primary_key=False, is_foreign_key=False, enum_values=[])`, `SchemaTable(name, comment, columns)`, `GenerationRequest(question, profile, allowed_tables)`, `SqlCandidate(sql, intent_reformulation, is_ambiguous=False, clarification_needed=None)`, `JudgeVerdictLabel` (Enum: `ALIGNED`, `DRIFT`, `UNCERTAIN`), `JudgeVerdict(verdict, reason)`, `GuardrailViolation(rule, reason)`, `GenerationOutcomeType` (Enum: `generated`, `needs_clarification`, `refused_out_of_schema`, `rejected_guardrail`, `rejected_judge`), `GenerationOutcome(outcome, sql=None, intent_reformulation=None, judge_verdict=None, attempts=0, message=None)` — all in `app/domain/models.py`.

- [ ] **Step 1: Write the failing test**

Create `text2sql-ai/tests/unit/test_models.py`:

```python
from app.domain.models import (
    GenerationOutcome,
    GenerationOutcomeType,
    GenerationRequest,
    GuardrailViolation,
    JudgeVerdict,
    JudgeVerdictLabel,
    SchemaColumn,
    SchemaTable,
    SqlCandidate,
)


def test_schema_table_holds_columns():
    column = SchemaColumn(name="quantity", type="integer", comment="qty")
    table = SchemaTable(name="stock", comment="stock levels", columns=[column])

    assert table.name == "stock"
    assert table.columns == [column]


def test_schema_column_defaults():
    column = SchemaColumn(name="id", type="integer", comment="id")

    assert column.is_primary_key is False
    assert column.is_foreign_key is False
    assert column.enum_values == []


def test_generation_request_holds_allowed_tables():
    request = GenerationRequest(question="q", profile="support", allowed_tables=["stock"])

    assert request.allowed_tables == ["stock"]


def test_sql_candidate_defaults_to_not_ambiguous():
    candidate = SqlCandidate(sql="SELECT 1", intent_reformulation="one")

    assert candidate.is_ambiguous is False
    assert candidate.clarification_needed is None


def test_judge_verdict_label_values_match_api_contract():
    assert JudgeVerdictLabel.ALIGNED.value == "ALIGNED"
    assert JudgeVerdictLabel.DRIFT.value == "DRIFT"
    assert JudgeVerdictLabel.UNCERTAIN.value == "UNCERTAIN"


def test_generation_outcome_type_values_match_api_contract():
    assert GenerationOutcomeType.GENERATED.value == "generated"
    assert GenerationOutcomeType.NEEDS_CLARIFICATION.value == "needs_clarification"
    assert GenerationOutcomeType.REFUSED_OUT_OF_SCHEMA.value == "refused_out_of_schema"
    assert GenerationOutcomeType.REJECTED_GUARDRAIL.value == "rejected_guardrail"
    assert GenerationOutcomeType.REJECTED_JUDGE.value == "rejected_judge"


def test_generation_outcome_defaults():
    outcome = GenerationOutcome(outcome=GenerationOutcomeType.REFUSED_OUT_OF_SCHEMA)

    assert outcome.sql is None
    assert outcome.attempts == 0


def test_guardrail_violation_holds_rule_and_reason():
    violation = GuardrailViolation(rule="blocklist", reason="mot interdit")

    assert violation.rule == "blocklist"


def test_judge_verdict_holds_verdict_and_reason():
    verdict = JudgeVerdict(verdict=JudgeVerdictLabel.ALIGNED, reason="ok")

    assert verdict.verdict == JudgeVerdictLabel.ALIGNED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Write minimal implementation**

Create `text2sql-ai/app/__init__.py` and `text2sql-ai/app/domain/__init__.py` as empty
files. Create `text2sql-ai/tests/__init__.py` and `text2sql-ai/tests/unit/__init__.py` as
empty files.

Create `text2sql-ai/app/domain/models.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_models.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add app/__init__.py app/domain/__init__.py app/domain/models.py tests/__init__.py tests/unit/__init__.py tests/unit/test_models.py
git commit -m "feat(text2sql-ai): ajoute les modèles de domaine"
```

---

### Task 2: Domain guardrails (blocklist + AST)

**Files:**
- Modify: `/Volumes/CodeSource/myRepos/simplon/briefs/sorabel_v3/src/pyproject.toml` (add `sqlglot` dependency)
- Create: `text2sql-ai/app/domain/guardrails.py`
- Test: `text2sql-ai/tests/unit/test_guardrails.py`

**Interfaces:**
- Consumes: `SchemaTable`, `SchemaColumn`, `GuardrailViolation` from `app/domain/models.py` (Task 1).
- Produces: `check_blocklist(sql: str) -> GuardrailViolation | None`, `check_ast(sql: str, allowed_tables: list[SchemaTable]) -> GuardrailViolation | None`, `validate(sql: str, allowed_tables: list[SchemaTable]) -> GuardrailViolation | None` in `app/domain/guardrails.py` — consumed by the use case in Task 6.

- [ ] **Step 1: Add the `sqlglot` dependency**

Edit `/Volumes/CodeSource/myRepos/simplon/briefs/sorabel_v3/src/pyproject.toml`, in the
`[project] dependencies` list, add `"sqlglot>=25.0",` after `"pgvector>=0.3",`. Then run:

```bash
cd /Volumes/CodeSource/myRepos/simplon/briefs/sorabel_v3/src && pip install -e ".[dev]"
```

- [ ] **Step 2: Write the failing test**

Create `text2sql-ai/tests/unit/test_guardrails.py`:

```python
from app.domain.guardrails import check_ast, check_blocklist, validate
from app.domain.models import SchemaColumn, SchemaTable

STOCK_TABLE = SchemaTable(
    name="stock",
    comment="stock",
    columns=[
        SchemaColumn(name="product_ref", type="varchar", comment="ref"),
        SchemaColumn(name="quantity", type="integer", comment="qty"),
    ],
)


def test_blocklist_catches_delete():
    violation = check_blocklist("DELETE FROM stock WHERE product_ref = 'REF-1'")

    assert violation is not None
    assert violation.rule == "blocklist"


def test_blocklist_catches_delete_inside_cte():
    sql = "WITH x AS (DELETE FROM stock RETURNING *) SELECT * FROM x"

    assert check_blocklist(sql) is not None


def test_blocklist_allows_plain_select():
    assert check_blocklist("SELECT quantity FROM stock") is None


def test_ast_rejects_multiple_statements():
    sql = "SELECT quantity FROM stock; SELECT quantity FROM stock;"

    violation = check_ast(sql, [STOCK_TABLE])

    assert violation is not None
    assert violation.rule == "ast"


def test_ast_rejects_unauthorized_table():
    sql = "SELECT product_ref FROM products"

    assert check_ast(sql, [STOCK_TABLE]) is not None


def test_ast_rejects_unauthorized_column():
    sql = "SELECT unknown_column FROM stock"

    assert check_ast(sql, [STOCK_TABLE]) is not None


def test_ast_accepts_valid_select():
    sql = "SELECT quantity FROM stock WHERE product_ref = 'REF-8842'"

    assert check_ast(sql, [STOCK_TABLE]) is None


def test_ast_rejects_non_select_statement():
    violation = check_ast("EXPLAIN SELECT quantity FROM stock", [STOCK_TABLE])

    assert violation is not None
    assert violation.rule == "ast"


def test_validate_runs_blocklist_before_ast():
    violation = validate("DROP TABLE stock", [STOCK_TABLE])

    assert violation is not None
    assert violation.rule == "blocklist"


def test_validate_returns_none_for_valid_sql():
    assert validate("SELECT quantity FROM stock", [STOCK_TABLE]) is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_guardrails.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.guardrails'`

- [ ] **Step 4: Write minimal implementation**

Create `text2sql-ai/app/domain/guardrails.py`:

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/test_guardrails.py -v`
Expected: PASS (10 tests)

- [ ] **Step 6: Commit**

```bash
git add app/domain/guardrails.py tests/unit/test_guardrails.py
cd .. && git add pyproject.toml && cd text2sql-ai
git commit -m "feat(text2sql-ai): ajoute les garde-fous de génération (blocklist + AST)"
```

---

### Task 3: Domain prompt builder

**Files:**
- Create: `text2sql-ai/app/domain/prompt.py`
- Test: `text2sql-ai/tests/unit/test_prompt.py`

**Interfaces:**
- Consumes: `SchemaTable`, `SchemaColumn` from `app/domain/models.py` (Task 1).
- Produces: `build_system_prompt(tables: list[SchemaTable], business_rules: dict[str, str], few_shot_examples: list[dict[str, str]]) -> str` in `app/domain/prompt.py` — consumed by the use case in Task 6.

- [ ] **Step 1: Write the failing test**

Create `text2sql-ai/tests/unit/test_prompt.py`:

```python
from app.domain.models import SchemaColumn, SchemaTable
from app.domain.prompt import build_system_prompt

STOCK_TABLE = SchemaTable(
    name="stock",
    comment="Niveaux de stock",
    columns=[
        SchemaColumn(
            name="status",
            type="varchar",
            comment="statut",
            enum_values=["pending", "shipped"],
        ),
    ],
)

PRODUCTS_TABLE = SchemaTable(name="products", comment="Catalogue", columns=[])


def test_prompt_includes_only_filtered_schema():
    prompt = build_system_prompt([STOCK_TABLE], {}, [])

    assert "stock" in prompt
    assert "products" not in prompt


def test_prompt_spells_out_enum_values():
    prompt = build_system_prompt([STOCK_TABLE], {}, [])

    assert "'pending'" in prompt
    assert "'shipped'" in prompt


def test_prompt_includes_critical_instruction():
    prompt = build_system_prompt([STOCK_TABLE], {}, [])

    assert "CRITICAL" in prompt


def test_prompt_includes_readonly_instruction():
    prompt = build_system_prompt([STOCK_TABLE], {}, [])

    assert "lecture seule" in prompt


def test_prompt_includes_business_rules():
    prompt = build_system_prompt(
        [STOCK_TABLE], {"CA du mois": "SUM(amount) WHERE status != 'cancelled'"}, []
    )

    assert "CA du mois" in prompt


def test_prompt_includes_few_shot_examples():
    prompt = build_system_prompt([STOCK_TABLE], {}, [{"question": "stock ?", "sql": "SELECT 1"}])

    assert "stock ?" in prompt
    assert "SELECT 1" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_prompt.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.prompt'`

- [ ] **Step 3: Write minimal implementation**

Create `text2sql-ai/app/domain/prompt.py`:

```python
"""Pure prompt-assembly logic (Text2SQL_Sorabel.md §4) — turns a filtered schema +
static prompt ingredients into the system prompt sent to the generator LLM. No I/O;
every ingredient is passed in already loaded by the caller."""

from __future__ import annotations

from app.domain.models import SchemaTable

CRITICAL_INSTRUCTION = (
    "CRITICAL: utilise uniquement les noms de tables et de colonnes exacts listés "
    "ci-dessus, tels quels. N'invente jamais un nom de table ou de colonne."
)

READONLY_INSTRUCTION = (
    "Tu es un agent Text-to-SQL en lecture seule strict. Tu ne génères que des "
    "requêtes SELECT. Si la question demande une modification de données (ajout, "
    "suppression, mise à jour), refuse et explique que tu ne fais que de la lecture."
)


def _format_table(table: SchemaTable) -> str:
    lines = [f"Table {table.name} -- {table.comment}"]
    for column in table.columns:
        flags = []
        if column.is_primary_key:
            flags.append("PK")
        if column.is_foreign_key:
            flags.append("FK")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        enum_str = ""
        if column.enum_values:
            values = ", ".join(f"'{v}'" for v in column.enum_values)
            enum_str = f" -- valeurs possibles : {values}"
        lines.append(
            f"  {table.name}.{column.name} ({column.type}){flag_str} -- {column.comment}{enum_str}"
        )
    return "\n".join(lines)


def build_system_prompt(
    tables: list[SchemaTable],
    business_rules: dict[str, str],
    few_shot_examples: list[dict[str, str]],
) -> str:
    schema_block = "\n\n".join(_format_table(t) for t in tables)

    rules_lines = [f"- {term} : {definition}" for term, definition in business_rules.items()]
    rules_block = "\n".join(rules_lines) if rules_lines else "(aucune règle métier spécifique)"

    example_lines = [
        f"Question : {example['question']}\nSQL : {example['sql']}" for example in few_shot_examples
    ]
    examples_block = "\n\n".join(example_lines) if example_lines else "(aucun exemple)"

    return (
        f"{READONLY_INSTRUCTION}\n\n"
        f"## Schéma disponible\n{schema_block}\n\n"
        f"## Règles métier\n{rules_block}\n\n"
        f"## Exemples\n{examples_block}\n\n"
        f"{CRITICAL_INSTRUCTION}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_prompt.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add app/domain/prompt.py tests/unit/test_prompt.py
git commit -m "feat(text2sql-ai): ajoute l'assemblage du prompt système"
```

---

### Task 4: Domain ports + YAML schema repository

**Files:**
- Create: `text2sql-ai/app/domain/ports.py`
- Create: `text2sql-ai/app/infrastructure/__init__.py` (empty)
- Create: `text2sql-ai/app/infrastructure/schema/__init__.py` (empty)
- Create: `text2sql-ai/app/infrastructure/schema/repository.py`
- Create: `text2sql-ai/app/infrastructure/schema/stock.yaml`
- Create: `text2sql-ai/app/infrastructure/schema/products.yaml`
- Create: `text2sql-ai/app/infrastructure/schema/orders.yaml`
- Create: `text2sql-ai/app/infrastructure/schema/customers.yaml`
- Create: `text2sql-ai/app/infrastructure/schema/business_rules.yaml`
- Create: `text2sql-ai/app/infrastructure/schema/few_shot.yaml`
- Test: `text2sql-ai/tests/unit/test_schema_repository.py`

**Interfaces:**
- Consumes: `SchemaTable`, `SchemaColumn`, `SqlCandidate`, `JudgeVerdict` from `app/domain/models.py` (Task 1).
- Produces:
  - `SchemaRepositoryPort`, `LLMPort`, `JudgePort` (Protocols) in `app/domain/ports.py` — consumed by the use case in Task 6 and adapters in Tasks 7–8.
  - `YamlSchemaRepository(schema_dir: Path = SCHEMA_DIR)` with `.get_tables(allowed_tables: list[str]) -> list[SchemaTable]`, `.all_table_names() -> list[str]`, `.all_column_names() -> set[str]` in `app/infrastructure/schema/repository.py`.
  - `SCHEMA_DIR: Path`, `load_business_rules(schema_dir: Path) -> dict[str, str]`, `load_few_shot_examples(schema_dir: Path) -> list[dict[str, str]]` in the same module — consumed by `app/dependencies.py` in Task 9 and `tests/eval/run_eval.py` in Task 11.

- [ ] **Step 1: Write the failing test**

Create `text2sql-ai/tests/unit/test_schema_repository.py`:

```python
from pathlib import Path

from app.infrastructure.schema.repository import (
    YamlSchemaRepository,
    load_business_rules,
    load_few_shot_examples,
)


def _write_table(dir_path: Path, name: str) -> None:
    (dir_path / f"{name}.yaml").write_text(
        f"name: {name}\n"
        f"comment: table {name}\n"
        "columns:\n"
        "  - name: id\n"
        "    type: integer\n"
        "    comment: identifiant\n"
        "    is_primary_key: true\n"
    )


def test_get_tables_filters_by_allowed_list(tmp_path):
    _write_table(tmp_path, "stock")
    _write_table(tmp_path, "products")
    repo = YamlSchemaRepository(schema_dir=tmp_path)

    result = repo.get_tables(["stock"])

    assert [t.name for t in result] == ["stock"]


def test_get_tables_silently_drops_unknown_table(tmp_path):
    _write_table(tmp_path, "stock")
    repo = YamlSchemaRepository(schema_dir=tmp_path)

    result = repo.get_tables(["stock", "does_not_exist"])

    assert [t.name for t in result] == ["stock"]


def test_get_tables_loads_column_flags(tmp_path):
    _write_table(tmp_path, "stock")
    repo = YamlSchemaRepository(schema_dir=tmp_path)

    table = repo.get_tables(["stock"])[0]

    assert table.columns[0].is_primary_key is True


def test_all_table_names_lists_everything_unfiltered(tmp_path):
    _write_table(tmp_path, "stock")
    _write_table(tmp_path, "products")
    repo = YamlSchemaRepository(schema_dir=tmp_path)

    assert set(repo.all_table_names()) == {"stock", "products"}


def test_reserved_files_are_not_loaded_as_tables(tmp_path):
    _write_table(tmp_path, "stock")
    (tmp_path / "business_rules.yaml").write_text('"CA du mois": "definition"\n')
    (tmp_path / "few_shot.yaml").write_text("- question: q\n  sql: s\n")

    repo = YamlSchemaRepository(schema_dir=tmp_path)

    assert set(repo.all_table_names()) == {"stock"}


def test_load_business_rules_reads_yaml_dict(tmp_path):
    (tmp_path / "business_rules.yaml").write_text('"CA du mois": "definition"\n')

    rules = load_business_rules(tmp_path)

    assert rules == {"CA du mois": "definition"}


def test_load_few_shot_examples_reads_yaml_list(tmp_path):
    (tmp_path / "few_shot.yaml").write_text("- question: q\n  sql: s\n")

    examples = load_few_shot_examples(tmp_path)

    assert examples == [{"question": "q", "sql": "s"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_schema_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure'`

- [ ] **Step 3: Write minimal implementation**

Create `text2sql-ai/app/domain/ports.py`:

```python
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
```

Create `text2sql-ai/app/infrastructure/__init__.py` and
`text2sql-ai/app/infrastructure/schema/__init__.py` as empty files.

Create `text2sql-ai/app/infrastructure/schema/repository.py`:

```python
"""Loads the static commented schema (one YAML file per table, per
Text2SQL_Sorabel.md §4) once, at construction time, and serves filtered subsets of
it. Implements SchemaRepositoryPort. Also loads the two sibling ingredient files
(business_rules.yaml, few_shot.yaml) used by domain/prompt.py."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.domain.models import SchemaColumn, SchemaTable

SCHEMA_DIR = Path(__file__).parent

_RESERVED_FILES = {"business_rules.yaml", "few_shot.yaml"}


def _load_table(path: Path) -> SchemaTable:
    data = yaml.safe_load(path.read_text())
    columns = [
        SchemaColumn(
            name=col["name"],
            type=col["type"],
            comment=col["comment"],
            is_primary_key=col.get("is_primary_key", False),
            is_foreign_key=col.get("is_foreign_key", False),
            enum_values=col.get("enum_values", []),
        )
        for col in data["columns"]
    ]
    return SchemaTable(name=data["name"], comment=data["comment"], columns=columns)


def load_business_rules(schema_dir: Path) -> dict[str, str]:
    path = schema_dir / "business_rules.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def load_few_shot_examples(schema_dir: Path) -> list[dict[str, str]]:
    path = schema_dir / "few_shot.yaml"
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text()) or []


class YamlSchemaRepository:
    """Implements SchemaRepositoryPort by loading every *.yaml file (excluding the
    reserved ingredient files) in a directory once, at construction time."""

    def __init__(self, schema_dir: Path = SCHEMA_DIR) -> None:
        self._tables: dict[str, SchemaTable] = {}
        for path in sorted(schema_dir.glob("*.yaml")):
            if path.name in _RESERVED_FILES:
                continue
            table = _load_table(path)
            self._tables[table.name] = table

    def get_tables(self, allowed_tables: list[str]) -> list[SchemaTable]:
        return [self._tables[name] for name in allowed_tables if name in self._tables]

    def all_table_names(self) -> list[str]:
        return list(self._tables.keys())

    def all_column_names(self) -> set[str]:
        return {c.name for t in self._tables.values() for c in t.columns}
```

Create `text2sql-ai/app/infrastructure/schema/stock.yaml`:

```yaml
name: stock
comment: "Niveaux de stock par référence produit"
columns:
  - name: product_ref
    type: varchar
    comment: "Clé pivot vers le catalogue produit (products.product_ref)"
    is_foreign_key: true
  - name: quantity
    type: integer
    comment: "Quantité actuellement en stock"
```

Create `text2sql-ai/app/infrastructure/schema/products.yaml`:

```yaml
name: products
comment: "Catalogue produit"
columns:
  - name: product_ref
    type: varchar
    comment: "Référence produit, clé pivot du catalogue"
    is_primary_key: true
  - name: name
    type: varchar
    comment: "Nom commercial du produit"
  - name: purchase_price
    type: numeric
    comment: "Prix d'achat (jamais visible du profil support)"
  - name: margin
    type: numeric
    comment: "Marge (jamais visible du profil support)"
```

Create `text2sql-ai/app/infrastructure/schema/orders.yaml`:

```yaml
name: orders
comment: "Commandes clients"
columns:
  - name: id
    type: integer
    comment: "Identifiant de la commande"
    is_primary_key: true
  - name: customer_id
    type: integer
    comment: "Client ayant passé la commande (customers.id)"
    is_foreign_key: true
  - name: status
    type: varchar
    comment: "Statut de la commande"
    enum_values: ["pending", "shipped", "delivered", "cancelled"]
  - name: amount
    type: numeric
    comment: "Montant total de la commande"
  - name: created_at
    type: timestamp
    comment: "Date de création de la commande"
```

Create `text2sql-ai/app/infrastructure/schema/customers.yaml`:

```yaml
name: customers
comment: "Clients"
columns:
  - name: id
    type: integer
    comment: "Identifiant du client"
    is_primary_key: true
  - name: name
    type: varchar
    comment: "Nom du client"
```

Create `text2sql-ai/app/infrastructure/schema/business_rules.yaml`:

```yaml
"CA du mois": "SUM(orders.amount) WHERE orders.status != 'cancelled' AND orders.created_at est dans le mois calendaire en cours"
"commande active": "orders.status IN ('pending', 'shipped')"
```

Create `text2sql-ai/app/infrastructure/schema/few_shot.yaml`:

```yaml
- question: "Quel est le stock actuel de la référence REF-8842 ?"
  sql: "SELECT quantity FROM stock WHERE product_ref = 'REF-8842'"
- question: "Quel est le statut de la commande 12345 ?"
  sql: "SELECT status FROM orders WHERE id = 12345"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_schema_repository.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add app/domain/ports.py app/infrastructure/ tests/unit/test_schema_repository.py
git commit -m "feat(text2sql-ai): ajoute les ports et le référentiel de schéma YAML"
```

---

### Task 5: Application use case — `generate_sql`

**Files:**
- Create: `text2sql-ai/app/application/__init__.py` (empty)
- Create: `text2sql-ai/app/application/use_cases/__init__.py` (empty)
- Create: `text2sql-ai/app/application/use_cases/generate_sql.py`
- Test: `text2sql-ai/tests/unit/test_generate_sql.py`

**Interfaces:**
- Consumes: `validate` from `app/domain/guardrails.py` (Task 2); `build_system_prompt` from `app/domain/prompt.py` (Task 3); `GenerationOutcome`, `GenerationOutcomeType`, `GenerationRequest`, `JudgeVerdictLabel`, `SqlCandidate`, `JudgeVerdict` from `app/domain/models.py` (Task 1); `SchemaRepositoryPort`, `LLMPort`, `JudgePort` from `app/domain/ports.py` (Task 4).
- Produces: `GenerateSqlUseCase(schema_repository, llm, judge, business_rules, few_shot_examples)` with `async .execute(request: GenerationRequest) -> GenerationOutcome` — consumed by `app/dependencies.py` in Task 9.

- [ ] **Step 1: Write the failing test**

Create `text2sql-ai/tests/unit/test_generate_sql.py`:

```python
import logging

from app.application.use_cases.generate_sql import GenerateSqlUseCase
from app.domain.models import (
    GenerationOutcomeType,
    GenerationRequest,
    JudgeVerdict,
    JudgeVerdictLabel,
    SchemaColumn,
    SchemaTable,
    SqlCandidate,
)

STOCK_TABLE = SchemaTable(
    name="stock",
    comment="stock",
    columns=[
        SchemaColumn(name="product_ref", type="varchar", comment="ref"),
        SchemaColumn(name="quantity", type="integer", comment="qty"),
    ],
)


class FakeSchemaRepository:
    def __init__(self, tables):
        self._tables = {t.name: t for t in tables}

    def get_tables(self, allowed_tables):
        return [self._tables[name] for name in allowed_tables if name in self._tables]

    def all_table_names(self):
        return list(self._tables.keys())

    def all_column_names(self):
        return {c.name for t in self._tables.values() for c in t.columns}


class FakeLlm:
    def __init__(self, candidates):
        self._candidates = list(candidates)
        self.calls: list[str | None] = []

    async def generate(self, system_prompt, question, previous_attempt_feedback=None):
        self.calls.append(previous_attempt_feedback)
        return self._candidates.pop(0)


class FakeJudge:
    def __init__(self, verdicts):
        self._verdicts = list(verdicts)

    async def evaluate(self, question, intent_reformulation, sql):
        return self._verdicts.pop(0)


def make_use_case(tables, llm, judge):
    return GenerateSqlUseCase(
        schema_repository=FakeSchemaRepository(tables),
        llm=llm,
        judge=judge,
        business_rules={},
        few_shot_examples=[],
    )


async def test_happy_path_returns_generated():
    llm = FakeLlm([SqlCandidate(sql="SELECT quantity FROM stock", intent_reformulation="stock")])
    judge = FakeJudge([JudgeVerdict(verdict=JudgeVerdictLabel.ALIGNED, reason="ok")])
    use_case = make_use_case([STOCK_TABLE], llm, judge)

    outcome = await use_case.execute(
        GenerationRequest(
            question="stock de la REF-8842", profile="support", allowed_tables=["stock"]
        )
    )

    assert outcome.outcome == GenerationOutcomeType.GENERATED
    assert outcome.sql == "SELECT quantity FROM stock"
    assert outcome.attempts == 1


async def test_empty_allowed_tables_refuses_out_of_schema():
    use_case = make_use_case([STOCK_TABLE], FakeLlm([]), FakeJudge([]))

    outcome = await use_case.execute(
        GenerationRequest(question="stock ?", profile="support", allowed_tables=[])
    )

    assert outcome.outcome == GenerationOutcomeType.REFUSED_OUT_OF_SCHEMA


async def test_question_matching_no_known_term_refuses_out_of_schema():
    use_case = make_use_case([STOCK_TABLE], FakeLlm([]), FakeJudge([]))

    outcome = await use_case.execute(
        GenerationRequest(
            question="quel est le NPS de nos clients ?", profile="support", allowed_tables=["stock"]
        )
    )

    assert outcome.outcome == GenerationOutcomeType.REFUSED_OUT_OF_SCHEMA


async def test_ambiguous_candidate_needs_clarification():
    llm = FakeLlm(
        [
            SqlCandidate(
                sql="",
                intent_reformulation="",
                is_ambiguous=True,
                clarification_needed="CA en montant ou en volume ?",
            )
        ]
    )
    use_case = make_use_case([STOCK_TABLE], llm, FakeJudge([]))

    outcome = await use_case.execute(
        GenerationRequest(
            question="quel est le meilleur produit en stock",
            profile="support",
            allowed_tables=["stock"],
        )
    )

    assert outcome.outcome == GenerationOutcomeType.NEEDS_CLARIFICATION
    assert outcome.message == "CA en montant ou en volume ?"


async def test_guardrail_violation_retries_then_rejects():
    candidate = SqlCandidate(sql="DROP TABLE stock", intent_reformulation="x")
    llm = FakeLlm([candidate, candidate, candidate])
    use_case = make_use_case([STOCK_TABLE], llm, FakeJudge([]))

    outcome = await use_case.execute(
        GenerationRequest(question="stock ?", profile="support", allowed_tables=["stock"])
    )

    assert outcome.outcome == GenerationOutcomeType.REJECTED_GUARDRAIL
    assert outcome.attempts == 3
    assert llm.calls[0] is None
    assert llm.calls[1] is not None


async def test_judge_drift_retries_then_rejects():
    candidate = SqlCandidate(sql="SELECT quantity FROM stock", intent_reformulation="x")
    llm = FakeLlm([candidate, candidate, candidate])
    drift = JudgeVerdict(verdict=JudgeVerdictLabel.DRIFT, reason="mauvaise période")
    judge = FakeJudge([drift, drift, drift])
    use_case = make_use_case([STOCK_TABLE], llm, judge)

    outcome = await use_case.execute(
        GenerationRequest(question="stock ?", profile="support", allowed_tables=["stock"])
    )

    assert outcome.outcome == GenerationOutcomeType.REJECTED_JUDGE
    assert outcome.attempts == 3


async def test_judge_uncertain_needs_clarification():
    llm = FakeLlm([SqlCandidate(sql="SELECT quantity FROM stock", intent_reformulation="x")])
    judge = FakeJudge([JudgeVerdict(verdict=JudgeVerdictLabel.UNCERTAIN, reason="ambigu")])
    use_case = make_use_case([STOCK_TABLE], llm, judge)

    outcome = await use_case.execute(
        GenerationRequest(question="stock ?", profile="support", allowed_tables=["stock"])
    )

    assert outcome.outcome == GenerationOutcomeType.NEEDS_CLARIFICATION
    assert outcome.judge_verdict == JudgeVerdictLabel.UNCERTAIN


async def test_execute_logs_outcome(caplog):
    llm = FakeLlm([SqlCandidate(sql="SELECT quantity FROM stock", intent_reformulation="stock")])
    judge = FakeJudge([JudgeVerdict(verdict=JudgeVerdictLabel.ALIGNED, reason="ok")])
    use_case = make_use_case([STOCK_TABLE], llm, judge)

    with caplog.at_level(logging.INFO):
        await use_case.execute(
            GenerationRequest(question="stock ?", profile="support", allowed_tables=["stock"])
        )

    assert any(record.message == "text2sql_generation" for record in caplog.records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_generate_sql.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.application'`

- [ ] **Step 3: Write minimal implementation**

Create `text2sql-ai/app/application/__init__.py` and
`text2sql-ai/app/application/use_cases/__init__.py` as empty files.

Create `text2sql-ai/app/application/use_cases/generate_sql.py`:

```python
"""Orchestrates the generation pipeline (Text2SQL_Sorabel.md §4-§9): filter schema
→ build prompt → generate → guardrails → judge → bounded self-correction retry.
Never executes SQL — that is sorabelsql-api's responsibility."""

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

        if not tables or not self._question_covered_by_schema(request.question):
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
                    f"{violation.reason}. Corrige-la."
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

    def _question_covered_by_schema(self, question: str) -> bool:
        """Cheap keyword check: does the question reference at least one known
        table/column name anywhere in the (unfiltered) schema? Distinguishes
        'doesn't exist' from 'not authorized' at the pre-check step."""
        question_lower = question.lower()
        known_terms = set(self._schema_repository.all_table_names()) | set(
            self._schema_repository.all_column_names()
        )
        return any(term.lower() in question_lower for term in known_terms)

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_generate_sql.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add app/application/ tests/unit/test_generate_sql.py
git commit -m "feat(text2sql-ai): ajoute l'orchestration du cas d'usage generate_sql"
```

---

### Task 6: Azure OpenAI LLM client (generator)

**Files:**
- Create: `text2sql-ai/app/infrastructure/azure_openai/__init__.py` (empty)
- Create: `text2sql-ai/app/infrastructure/azure_openai/llm_client.py`
- Test: `text2sql-ai/tests/unit/test_llm_client.py`

**Interfaces:**
- Consumes: `SqlCandidate` from `app/domain/models.py` (Task 1); implements `LLMPort` from `app/domain/ports.py` (Task 4).
- Produces: `AzureOpenAiLlmClient(client: AsyncAzureOpenAI, deployment: str)` with `async .generate(system_prompt, question, previous_attempt_feedback=None) -> SqlCandidate` in `app/infrastructure/azure_openai/llm_client.py` — consumed by `app/dependencies.py` in Task 9.

- [ ] **Step 1: Write the failing test**

Create `text2sql-ai/tests/unit/test_llm_client.py`:

```python
import json
from unittest.mock import AsyncMock, MagicMock

from app.infrastructure.azure_openai.llm_client import AzureOpenAiLlmClient


def _make_response(payload: dict) -> MagicMock:
    message = MagicMock()
    message.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


async def test_generate_returns_sql_candidate():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=_make_response(
            {
                "is_ambiguous": False,
                "clarification_needed": None,
                "sql": "SELECT quantity FROM stock",
                "intent_reformulation": "stock",
            }
        )
    )
    client = AzureOpenAiLlmClient(fake_client, "gen-deployment")

    candidate = await client.generate("system prompt", "quel est le stock ?")

    assert candidate.sql == "SELECT quantity FROM stock"
    assert candidate.intent_reformulation == "stock"
    assert candidate.is_ambiguous is False
    fake_client.chat.completions.create.assert_awaited_once()


async def test_generate_includes_feedback_message_when_retrying():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=_make_response(
            {
                "is_ambiguous": False,
                "clarification_needed": None,
                "sql": "SELECT quantity FROM stock",
                "intent_reformulation": "stock",
            }
        )
    )
    client = AzureOpenAiLlmClient(fake_client, "gen-deployment")

    await client.generate("system prompt", "question", previous_attempt_feedback="corrige X")

    _, kwargs = fake_client.chat.completions.create.call_args
    messages = kwargs["messages"]
    assert any("corrige X" in m["content"] for m in messages)


async def test_generate_detects_ambiguity():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=_make_response(
            {
                "is_ambiguous": True,
                "clarification_needed": "CA en montant ou en volume ?",
                "sql": None,
                "intent_reformulation": None,
            }
        )
    )
    client = AzureOpenAiLlmClient(fake_client, "gen-deployment")

    candidate = await client.generate("system prompt", "quel est le meilleur produit ?")

    assert candidate.is_ambiguous is True
    assert candidate.clarification_needed == "CA en montant ou en volume ?"
    assert candidate.sql == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_llm_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.azure_openai'`

- [ ] **Step 3: Write minimal implementation**

Create `text2sql-ai/app/infrastructure/azure_openai/__init__.py` as an empty file.

Create `text2sql-ai/app/infrastructure/azure_openai/llm_client.py`:

```python
"""Azure OpenAI adapter implementing LLMPort — the SQL generator. Structured JSON
output avoids parsing free-text SQL out of prose."""

from __future__ import annotations

import json

from openai import AsyncAzureOpenAI

from app.domain.models import SqlCandidate

GENERATION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_ambiguous": {"type": "boolean"},
        "clarification_needed": {"type": ["string", "null"]},
        "sql": {"type": ["string", "null"]},
        "intent_reformulation": {"type": ["string", "null"]},
    },
    "required": ["is_ambiguous", "clarification_needed", "sql", "intent_reformulation"],
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

        response = await self._client.chat.completions.create(
            model=self._deployment,
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "sql_generation", "schema": GENERATION_RESPONSE_SCHEMA},
            },
        )
        payload = json.loads(response.choices[0].message.content)

        return SqlCandidate(
            sql=payload["sql"] or "",
            intent_reformulation=payload["intent_reformulation"] or "",
            is_ambiguous=payload["is_ambiguous"],
            clarification_needed=payload["clarification_needed"],
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_llm_client.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/azure_openai/__init__.py app/infrastructure/azure_openai/llm_client.py tests/unit/test_llm_client.py
git commit -m "feat(text2sql-ai): ajoute l'adaptateur Azure OpenAI générateur"
```

---

### Task 7: Azure OpenAI judge client

**Files:**
- Create: `text2sql-ai/app/infrastructure/azure_openai/judge_client.py`
- Test: `text2sql-ai/tests/unit/test_judge_client.py`

**Interfaces:**
- Consumes: `JudgeVerdict`, `JudgeVerdictLabel` from `app/domain/models.py` (Task 1); implements `JudgePort` from `app/domain/ports.py` (Task 4).
- Produces: `AzureOpenAiJudgeClient(client: AsyncAzureOpenAI, deployment: str)` with `async .evaluate(question, intent_reformulation, sql) -> JudgeVerdict` in `app/infrastructure/azure_openai/judge_client.py` — consumed by `app/dependencies.py` in Task 9.

- [ ] **Step 1: Write the failing test**

Create `text2sql-ai/tests/unit/test_judge_client.py`:

```python
import json
from unittest.mock import AsyncMock, MagicMock

from app.domain.models import JudgeVerdictLabel
from app.infrastructure.azure_openai.judge_client import AzureOpenAiJudgeClient


def _make_response(payload: dict) -> MagicMock:
    message = MagicMock()
    message.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


async def test_evaluate_returns_aligned_verdict():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=_make_response({"verdict": "ALIGNED", "reason": "correspond à la question"})
    )
    judge = AzureOpenAiJudgeClient(fake_client, "judge-deployment")

    verdict = await judge.evaluate(
        "stock de REF-8842", "stock actuel de REF-8842", "SELECT quantity FROM stock"
    )

    assert verdict.verdict == JudgeVerdictLabel.ALIGNED
    assert verdict.reason == "correspond à la question"


async def test_evaluate_returns_drift_verdict():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=_make_response({"verdict": "DRIFT", "reason": "mauvaise période"})
    )
    judge = AzureOpenAiJudgeClient(fake_client, "judge-deployment")

    verdict = await judge.evaluate("q", "reformulation", "SELECT 1")

    assert verdict.verdict == JudgeVerdictLabel.DRIFT


async def test_evaluate_sends_question_reformulation_and_sql():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=_make_response({"verdict": "ALIGNED", "reason": "ok"})
    )
    judge = AzureOpenAiJudgeClient(fake_client, "judge-deployment")

    await judge.evaluate("ma question", "ma reformulation", "SELECT 1")

    _, kwargs = fake_client.chat.completions.create.call_args
    user_message = kwargs["messages"][-1]["content"]
    assert "ma question" in user_message
    assert "ma reformulation" in user_message
    assert "SELECT 1" in user_message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_judge_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.azure_openai.judge_client'`

- [ ] **Step 3: Write minimal implementation**

Create `text2sql-ai/app/infrastructure/azure_openai/judge_client.py`:

```python
"""Azure OpenAI adapter implementing JudgePort (Text2SQL_Sorabel.md §9) — a second,
separate LLM call whose only role is to judge alignment between the question and the
generated SQL. Never generates SQL itself."""

from __future__ import annotations

import json

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
        payload = json.loads(response.choices[0].message.content)
        return JudgeVerdict(verdict=JudgeVerdictLabel(payload["verdict"]), reason=payload["reason"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_judge_client.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/azure_openai/judge_client.py tests/unit/test_judge_client.py
git commit -m "feat(text2sql-ai): ajoute l'adaptateur Azure OpenAI juge d'intention"
```

---

### Task 8: FastAPI wiring — schemas, routes, config, main

**Files:**
- Create: `text2sql-ai/app/config.py`
- Create: `text2sql-ai/app/dependencies.py`
- Create: `text2sql-ai/app/api/__init__.py` (empty)
- Create: `text2sql-ai/app/api/routes/__init__.py` (empty)
- Create: `text2sql-ai/app/api/routes/generate.py`
- Create: `text2sql-ai/app/api/routes/health.py`
- Create: `text2sql-ai/app/api/schemas/__init__.py` (empty)
- Create: `text2sql-ai/app/api/schemas/generate.py`
- Create: `text2sql-ai/app/main.py`
- Create: `text2sql-ai/.env.example`
- Create: `text2sql-ai/tests/conftest.py`
- Create: `text2sql-ai/tests/test_routers/__init__.py` (empty)
- Test: `text2sql-ai/tests/test_routers/test_generate.py`

**Interfaces:**
- Consumes: `GenerateSqlUseCase` from `app/application/use_cases/generate_sql.py` (Task 5); `GenerationRequest`, `GenerationOutcomeType` from `app/domain/models.py` (Task 1); `YamlSchemaRepository`, `SCHEMA_DIR`, `load_business_rules`, `load_few_shot_examples` from `app/infrastructure/schema/repository.py` (Task 4); `AzureOpenAiLlmClient` (Task 6); `AzureOpenAiJudgeClient` (Task 7).
- Produces: `Settings` (pydantic-settings) in `app/config.py`; `get_settings()`, `get_schema_repository()`, `get_business_rules()`, `get_few_shot_examples()`, `get_azure_client()`, `get_generate_sql_use_case(...)` in `app/dependencies.py` — `get_azure_client`, `get_business_rules`, `get_schema_repository`, `get_few_shot_examples` are consumed by `tests/eval/run_eval.py` in Task 10; `GenerateRequest`, `GenerateResponse` in `app/api/schemas/generate.py`; `app` (the FastAPI instance) in `app/main.py`, exposing `POST /api/v1/generate` and `GET /api/v1/health`.

- [ ] **Step 1: Write the failing test**

Create `text2sql-ai/tests/conftest.py`:

```python
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
```

Create `text2sql-ai/tests/test_routers/__init__.py` as an empty file.

Create `text2sql-ai/tests/test_routers/test_generate.py`:

```python
from app.dependencies import get_generate_sql_use_case
from app.domain.models import GenerationOutcome, GenerationOutcomeType, JudgeVerdictLabel
from app.main import app


class StubUseCase:
    def __init__(self, outcome: GenerationOutcome) -> None:
        self._outcome = outcome

    async def execute(self, request):
        return self._outcome


def _override(outcome: GenerationOutcome) -> None:
    app.dependency_overrides[get_generate_sql_use_case] = lambda: StubUseCase(outcome)


async def test_generate_happy_path(client):
    outcome = GenerationOutcome(
        outcome=GenerationOutcomeType.GENERATED,
        sql="SELECT quantity FROM stock WHERE product_ref = 'REF-8842'",
        intent_reformulation="stock de REF-8842",
        judge_verdict=JudgeVerdictLabel.ALIGNED,
        attempts=1,
    )
    _override(outcome)

    response = await client.post(
        "/api/v1/generate",
        json={
            "question": "stock de la REF-8842 ?",
            "profile": "support",
            "allowed_tables": ["stock"],
        },
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "generated"
    assert data["sql"] == "SELECT quantity FROM stock WHERE product_ref = 'REF-8842'"
    assert data["judge_verdict"] == "ALIGNED"


async def test_generate_out_of_schema_refusal(client):
    outcome = GenerationOutcome(
        outcome=GenerationOutcomeType.REFUSED_OUT_OF_SCHEMA,
        message="La question ne correspond à aucune donnée disponible pour ce profil.",
    )
    _override(outcome)

    response = await client.post(
        "/api/v1/generate",
        json={"question": "quel est le NPS ?", "profile": "support", "allowed_tables": ["stock"]},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "refused_out_of_schema"
    assert data["sql"] is None


async def test_generate_rejects_empty_allowed_tables_with_422(client):
    response = await client.post(
        "/api/v1/generate",
        json={"question": "stock ?", "profile": "support", "allowed_tables": []},
    )

    assert response.status_code == 422


async def test_health_endpoint_returns_ok(client):
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_routers/test_generate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Write minimal implementation**

Create `text2sql-ai/app/config.py`:

```python
"""Application settings, loaded from environment variables / .env via
pydantic-settings. Never hardcode credentials — see ../../.claude/rules/security.md."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_api_version: str = "2024-08-01-preview"
    azure_openai_deployment_generator: str
    azure_openai_deployment_judge: str
```

Create `text2sql-ai/app/dependencies.py`:

```python
"""Shared FastAPI dependencies: builds the GenerateSqlUseCase with its concrete
Azure OpenAI + YAML-schema adapters. This is the composition root — the only place
that imports both the application layer and infrastructure adapters together."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends
from openai import AsyncAzureOpenAI

from app.application.use_cases.generate_sql import GenerateSqlUseCase
from app.config import Settings
from app.infrastructure.azure_openai.judge_client import AzureOpenAiJudgeClient
from app.infrastructure.azure_openai.llm_client import AzureOpenAiLlmClient
from app.infrastructure.schema.repository import (
    SCHEMA_DIR,
    YamlSchemaRepository,
    load_business_rules,
    load_few_shot_examples,
)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_schema_repository() -> YamlSchemaRepository:
    return YamlSchemaRepository()


@lru_cache
def get_business_rules() -> dict[str, str]:
    return load_business_rules(SCHEMA_DIR)


@lru_cache
def get_few_shot_examples() -> list[dict[str, str]]:
    return load_few_shot_examples(SCHEMA_DIR)


@lru_cache
def get_azure_client() -> AsyncAzureOpenAI:
    settings = get_settings()
    return AsyncAzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


def get_generate_sql_use_case(
    settings: Settings = Depends(get_settings),
    schema_repository: YamlSchemaRepository = Depends(get_schema_repository),
) -> GenerateSqlUseCase:
    client = get_azure_client()
    return GenerateSqlUseCase(
        schema_repository=schema_repository,
        llm=AzureOpenAiLlmClient(client, settings.azure_openai_deployment_generator),
        judge=AzureOpenAiJudgeClient(client, settings.azure_openai_deployment_judge),
        business_rules=get_business_rules(),
        few_shot_examples=get_few_shot_examples(),
    )
```

Create `text2sql-ai/app/api/__init__.py` and `text2sql-ai/app/api/routes/__init__.py`
as empty files.

Create `text2sql-ai/app/api/schemas/__init__.py` as an empty file.

Create `text2sql-ai/app/api/schemas/generate.py`:

```python
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
```

Create `text2sql-ai/app/api/routes/generate.py`:

```python
"""POST /api/v1/generate — the sole Text-to-SQL generation endpoint. Thin: only
translates HTTP <-> the use case, no business logic here."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.schemas.generate import GenerateRequest, GenerateResponse
from app.application.use_cases.generate_sql import GenerateSqlUseCase
from app.dependencies import get_generate_sql_use_case
from app.domain.models import GenerationRequest

router = APIRouter(prefix="/api/v1", tags=["generate"])


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    request: GenerateRequest,
    use_case: GenerateSqlUseCase = Depends(get_generate_sql_use_case),
) -> GenerateResponse:
    outcome = await use_case.execute(
        GenerationRequest(
            question=request.question,
            profile=request.profile,
            allowed_tables=request.allowed_tables,
        )
    )
    return GenerateResponse(
        outcome=outcome.outcome.value,
        sql=outcome.sql,
        intent_reformulation=outcome.intent_reformulation,
        judge_verdict=outcome.judge_verdict.value if outcome.judge_verdict else None,
        attempts=outcome.attempts,
        message=outcome.message,
    )
```

Create `text2sql-ai/app/api/routes/health.py`:

```python
"""GET /api/v1/health — container healthcheck. No dependencies to probe (this
service has no database)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

Create `text2sql-ai/app/main.py`:

```python
"""FastAPI app factory for text2sql-ai."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.routes.generate import router as generate_router
from app.api.routes.health import router as health_router

app = FastAPI(title="text2sql-ai")
app.include_router(generate_router)
app.include_router(health_router)
```

Create `text2sql-ai/.env.example`:

```
AZURE_OPENAI_ENDPOINT=https://<votre-ressource>.openai.azure.com/
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_OPENAI_DEPLOYMENT_GENERATOR=
AZURE_OPENAI_DEPLOYMENT_JUDGE=
```

Since `Settings` requires `azure_openai_endpoint`/`azure_openai_api_key`/the two
deployment names with no defaults, and the acceptance tests override
`get_generate_sql_use_case` entirely (never touching `Settings`), create a local
`text2sql-ai/.env` for running the test suite (gitignored — copy `.env.example` and
fill in placeholder values, real or dummy, since these tests never call Azure OpenAI):

```bash
cp .env.example .env
```

Edit `.env` to set dummy values (e.g. `AZURE_OPENAI_ENDPOINT=https://dummy.openai.azure.com/`,
`AZURE_OPENAI_API_KEY=dummy`, `AZURE_OPENAI_DEPLOYMENT_GENERATOR=dummy`,
`AZURE_OPENAI_DEPLOYMENT_JUDGE=dummy`) so `Settings()` can construct without error if
anything imports `app.main` at collection time.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_routers/test_generate.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full unit + acceptance suite**

Run: `pytest -v`
Expected: PASS (all tests from Tasks 1-8)

- [ ] **Step 6: Commit**

```bash
git add app/config.py app/dependencies.py app/api/ app/main.py .env.example tests/conftest.py tests/test_routers/
git commit -m "feat(text2sql-ai): expose l'API FastAPI (generate + health)"
```

---

### Task 9: Deployment — Dockerfile, docker-compose, Makefile

**Files:**
- Create: `text2sql-ai/Dockerfile`
- Create: `text2sql-ai/docker-compose.yml`
- Modify: `text2sql-ai/Makefile`

**Interfaces:**
- Consumes: nothing from earlier tasks' code — packages the app built in Tasks 1-8.
- Produces: a buildable image and `make build|test|lint|docker-build|docker-up|docker-down|clean` targets — no other task depends on this one.

- [ ] **Step 1: Write the Dockerfile**

Create `text2sql-ai/Dockerfile`:

```dockerfile
FROM python:3.12-slim AS base

WORKDIR /solution

COPY pyproject.toml ./
COPY text2sql-ai ./text2sql-ai

RUN pip install --no-cache-dir -e ".[dev]"

WORKDIR /solution/text2sql-ai

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write docker-compose.yml**

Create `text2sql-ai/docker-compose.yml`:

```yaml
services:
  text2sql-ai:
    build:
      context: ..
      dockerfile: text2sql-ai/Dockerfile
    ports:
      - "8000:8000"
    env_file:
      - .env
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"]
      interval: 10s
      timeout: 3s
      retries: 5
```

- [ ] **Step 3: Update the Makefile**

Replace the full contents of `text2sql-ai/Makefile` with:

```makefile
# Cibles standard — voir ../.claude/rules/makefile-conventions.md
#
# Exception locale : text2sql-ai a son propre Dockerfile (déploiement indépendant
# via l'API Gateway), contrairement à mcp/rag-hybride. Il continue de builder
# depuis le pyproject.toml partagé à la racine de la solution.

.PHONY: build test lint docker-build docker-up docker-down clean

build:
	cd .. && pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

docker-build:
	cd .. && docker build -f text2sql-ai/Dockerfile -t text2sql-ai .

docker-up:
	docker compose up

docker-down:
	docker compose down

clean:
	find . -type d -name '__pycache__' -exec rm -rf {} +
```

- [ ] **Step 4: Verify the image builds**

Run: `cd /Volumes/CodeSource/myRepos/simplon/briefs/sorabel_v3/src/text2sql-ai && make docker-build`
Expected: image builds successfully (`Successfully tagged text2sql-ai:latest` or
equivalent BuildKit success output)

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml Makefile
git commit -m "feat(text2sql-ai): ajoute le Dockerfile et les cibles Makefile Docker"
```

---

### Task 10: Golden Dataset + eval harness

**Files:**
- Create: `text2sql-ai/tests/eval/__init__.py` (empty)
- Create: `text2sql-ai/tests/eval/golden_dataset.jsonl`
- Create: `text2sql-ai/tests/eval/run_eval.py`

**Interfaces:**
- Consumes: `get_settings`, `get_schema_repository`, `get_business_rules`, `get_few_shot_examples`, `get_azure_client` from `app/dependencies.py` (Task 8); `GenerateSqlUseCase` from `app/application/use_cases/generate_sql.py` (Task 5); `AzureOpenAiLlmClient` (Task 6); `AzureOpenAiJudgeClient` (Task 7); `GenerationRequest`, `GenerationOutcomeType` from `app/domain/models.py` (Task 1).
- Produces: a standalone script, `tests/eval/run_eval.py`, run manually (not part of `pytest`/CI) — no other task depends on this one.

- [ ] **Step 1: Write the golden dataset**

Create `text2sql-ai/tests/eval/__init__.py` as an empty file.

Create `text2sql-ai/tests/eval/golden_dataset.jsonl` (one JSON object per line):

```jsonl
{"question": "Quel est le stock actuel de la référence REF-8842 ?", "allowed_tables": ["stock"], "target_sql": "SELECT quantity FROM stock WHERE product_ref = 'REF-8842'", "expected_result": {"quantity": 42}, "category": "recurrent"}
{"question": "Quel est le statut de la commande numéro 12345 ?", "allowed_tables": ["orders"], "target_sql": "SELECT status FROM orders WHERE id = 12345", "expected_result": {"status": "shipped"}, "category": "recurrent"}
{"question": "Combien de commandes sont annulées ?", "allowed_tables": ["orders"], "target_sql": "SELECT COUNT(*) FROM orders WHERE status = 'cancelled'", "expected_result": {"count": 7}, "category": "recurrent"}
{"question": "Quel est le montant total des commandes du client 42 ?", "allowed_tables": ["orders"], "target_sql": "SELECT SUM(amount) FROM orders WHERE customer_id = 42", "expected_result": {"sum": 1230.50}, "category": "recurrent"}
{"question": "Combien de clients sont enregistrés ?", "allowed_tables": ["customers"], "target_sql": "SELECT COUNT(*) FROM customers", "expected_result": {"count": 318}, "category": "recurrent"}
{"question": "Quel est le nom du produit associé à la référence REF-8842 ?", "allowed_tables": ["products"], "target_sql": "SELECT name FROM products WHERE product_ref = 'REF-8842'", "expected_result": {"name": "Câble HDMI 2m"}, "category": "recurrent"}
{"question": "Combien de commandes sont actuellement en attente ?", "allowed_tables": ["orders"], "target_sql": "SELECT COUNT(*) FROM orders WHERE status = 'pending'", "expected_result": {"count": 14}, "category": "recurrent"}
{"question": "Quel est le stock de la référence REF-1000 ?", "allowed_tables": ["stock"], "target_sql": "SELECT quantity FROM stock WHERE product_ref = 'REF-1000'", "expected_result": {"quantity": 0}, "category": "recurrent"}
{"question": "Quelle est la date de création de la commande 999 ?", "allowed_tables": ["orders"], "target_sql": "SELECT created_at FROM orders WHERE id = 999", "expected_result": {"created_at": "2026-08-01T10:00:00"}, "category": "recurrent"}
{"question": "Combien de commandes ont un montant supérieur à 100 ?", "allowed_tables": ["orders"], "target_sql": "SELECT COUNT(*) FROM orders WHERE amount > 100", "expected_result": {"count": 56}, "category": "recurrent"}
{"question": "Quel est le nom du client ayant l'identifiant 7 ?", "allowed_tables": ["customers"], "target_sql": "SELECT name FROM customers WHERE id = 7", "expected_result": {"name": "Atelier Dubois"}, "category": "recurrent"}
{"question": "Quel est le meilleur client ?", "allowed_tables": ["orders", "customers"], "target_sql": null, "expected_result": null, "category": "ambigu"}
{"question": "Quelle est la commande la plus importante ?", "allowed_tables": ["orders"], "target_sql": null, "expected_result": null, "category": "ambigu"}
{"question": "Quels sont nos produits les plus populaires ?", "allowed_tables": ["products", "orders"], "target_sql": null, "expected_result": null, "category": "ambigu"}
{"question": "Quel est le NPS de nos clients ?", "allowed_tables": ["customers"], "target_sql": null, "expected_result": null, "category": "hors_schema"}
{"question": "Quels sont les avis laissés par les clients sur nos produits ?", "allowed_tables": ["products"], "target_sql": null, "expected_result": null, "category": "hors_schema"}
```

- [ ] **Step 2: Write the eval runner**

Create `text2sql-ai/tests/eval/run_eval.py`:

```python
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
from app.infrastructure.azure_openai.judge_client import AzureOpenAiJudgeClient
from app.infrastructure.azure_openai.llm_client import AzureOpenAiLlmClient

DATASET_PATH = Path(__file__).parent / "golden_dataset.jsonl"


def _normalize(sql: str) -> str:
    return sqlglot.parse_one(sql, dialect="postgres").sql(dialect="postgres", normalize=True)


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

    entries = [json.loads(line) for line in DATASET_PATH.read_text().splitlines() if line.strip()]

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
        else:
            passed = outcome.outcome == GenerationOutcomeType.GENERATED and _sql_matches(
                outcome.sql or "", entry["target_sql"]
            )

        results_by_category[category].append(passed)
        print(f"[{'PASS' if passed else 'FAIL'}] ({category}) {entry['question']}")

    print("\n--- Résumé ---")
    for category, results in results_by_category.items():
        rate = sum(results) / len(results) * 100
        print(f"{category}: {sum(results)}/{len(results)} ({rate:.0f}%)")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Verify the script runs against a real Azure OpenAI deployment**

Fill in real `AZURE_OPENAI_*` values in `text2sql-ai/.env` (see Task 8), then run:

`python tests/eval/run_eval.py`

Expected: a `[PASS]`/`[FAIL]` line per question plus a summary table by category — no
crash. This step requires real Azure OpenAI credentials; if unavailable at
implementation time, confirm the script at least parses the dataset and reaches the
first `use_case.execute()` call without a `NameError`/`ImportError` (a
`401`/connection error from Azure OpenAI at that point is an acceptable stopping
point, not a plan failure).

- [ ] **Step 4: Commit**

```bash
git add tests/eval/
git commit -m "feat(text2sql-ai): ajoute le golden dataset et le harnais d'évaluation"
```

---

## Self-Review Notes

- **Spec coverage**: schema filtering (Task 4), YAML schema storage (Task 4), guardrail scope — blocklist + AST + judge (Tasks 2, 5, 7), fixed tools explicitly out of scope (no task creates them), eval harness (Task 10), Azure OpenAI backend (Tasks 6-7), Dockerfile deployment exception (Task 9), logging of every outcome (Task 5), API contract shape and `422` validation (Task 8) — all covered.
- **Type consistency checked**: `GenerationOutcomeType`/`JudgeVerdictLabel` enum values match the API's `outcome.value` calls in `app/api/routes/generate.py`; `SchemaRepositoryPort.get_tables/all_table_names/all_column_names` signatures match `YamlSchemaRepository` (Task 4) and `FakeSchemaRepository` (Task 5's test); `LLMPort.generate` and `JudgePort.evaluate` signatures match both the Azure adapters (Tasks 6-7) and the use case's calls (Task 5).
- **No placeholders**: every step contains full runnable code; no "TBD" or "add appropriate X" phrasing.
