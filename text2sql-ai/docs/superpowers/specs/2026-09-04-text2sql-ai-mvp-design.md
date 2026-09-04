# Text-to-SQL AI MVP — Design

**Date**: 2026-09-04
**Scope**: `text2sql-ai` (Sorabel Data Gateway — Text-to-SQL generation module)
**Status**: Approved for planning

## Context

`text2sql-ai` currently has no code — only `CLAUDE.md`, `README.md`, `Makefile`, and a
stub rule (`.claude/rules/sql-generation-readonly.md`). The README and root `CLAUDE.md`
already specify its role: generate a read-only SQL candidate from a natural-language
question and a profile's authorized schema subset — **never execute it**. Execution and
its own defense-in-depth (DB role, `LIMIT`/timeout, replica) belong to `sorabelsql-api`.
This spec turns that concept into a buildable end-to-end MVP, following the solution's
mandated hexagonal architecture (`../../.claude/rules/python-hexagonal.md`) and the
detailed framing in `Text2SQL_Sorabel.md` (§1–§10), mirroring the process and style
`rag-hybride` used for its own MVP spec.

## Goal

An end-to-end vertical slice: one generation endpoint that takes a question + a
profile-resolved list of allowed tables, assembles a static commented schema context,
generates a SQL candidate via Azure OpenAI, validates it through generation-side
defense-in-depth (blocklist, AST validation, LLM-as-judge intent check) with bounded
self-correction, and returns the candidate (or a refusal/clarification) — never
executing it. Plus a minimal Golden Dataset eval harness (§2).

Deferred: fixed/parameterized tools (§7), execution-error-driven auto-correction (§8,
requires a round trip through `sorabelsql-api`), a Guardrails-AI/NeMo Guardrails
framework, a wired CI/Evals gate (§3), and multi-domain schema splitting (§4's
beyond-15-tables concern).

## Decisions

| Question | Decision |
|---|---|
| Schema filtering | Caller (via `mcp`'s access matrix, forwarded through the API Gateway) passes `allowed_tables` explicitly in the request; text2sql-ai only filters its own static schema against that list — it never owns or re-derives the access matrix |
| Schema storage | One YAML file per table under `app/infrastructure/schema/`, loaded once at startup and cached in memory — `/new-schema-mapping` scaffolds new ones |
| Guardrail scope | Blocklist + AST (`sqlglot`) validation + §9's LLM-as-judge (intent understanding + SQL fidelity, one structured call) — the full slice of defense-in-depth that is generation-side, not execution-side |
| Fixed tools (§7) | Out of scope — belong to `sorabelsql-api`/`mcp` |
| Eval harness | Minimal Golden Dataset (~15-20 entries) + a manual `run_eval.py`, mirroring `rag-hybride`'s E6 harness — not a CI gate yet |
| LLM backend | Azure OpenAI, same adapter pattern as `rag-hybride`'s `app/infrastructure/azure_openai/` |
| Deployment | Own `Dockerfile` + `docker-build`/`docker-up`/`docker-down` — a documented exception to the shared Python no-Docker convention (see below) |

### Why text2sql-ai gets its own Dockerfile

`.claude/rules/makefile-conventions.md` documents a shared-tooling exception for the 3
Python projects (`mcp`, `text2sql-ai`, `rag-hybride`): one root `pyproject.toml`, one
root `docker-compose.yml`, no per-project Dockerfile, each running via `uvicorn --reload`
from its own working directory as a co-located dev process. `text2sql-ai` breaks from
this: it's called exclusively via the API Gateway, from environments that are not
co-located dev processes alongside `mcp`/`rag-hybride` — it needs an independently
deployable/scalable container. The convention doc is amended accordingly (separate diff,
see below); `mcp` and `rag-hybride` are unaffected.

## Architecture

```
text2sql-ai/
├── app/
│   ├── domain/
│   │   ├── models.py       # SchemaTable, SchemaColumn, GenerationRequest, SqlCandidate,
│   │   │                   # JudgeVerdict, GuardrailViolation, GenerationOutcome
│   │   ├── prompt.py        # build_system_prompt() — assembles filtered schema + enums +
│   │   │                   # few-shot + business rules + CRITICAL instruction (pure function)
│   │   ├── guardrails.py    # blocklist check + AST validation (sqlglot) — pure functions,
│   │   │                   # no I/O: "does this SQL touch only allowed tables/columns?"
│   │   └── ports.py         # SchemaRepositoryPort, LLMPort, JudgePort
│   ├── application/
│   │   └── use_cases/
│   │       └── generate_sql.py   # orchestrates: filter schema → prompt → generate →
│   │                              # guardrails → judge → bounded self-correction retry
│   ├── infrastructure/
│   │   ├── schema/
│   │   │   ├── stock.yaml, products.yaml, orders.yaml, customers.yaml  # one file/table
│   │   │   ├── business_rules.yaml   # glossary of ambiguous-term definitions ("CA du mois", ...)
│   │   │   ├── few_shot.yaml          # curated question→SQL examples for the prompt (subset of golden_dataset)
│   │   │   └── repository.py     # implements SchemaRepositoryPort: loads YAML once at
│   │   │                          # startup, caches in memory, filters by allowed-tables list
│   │   └── azure_openai/
│   │       ├── llm_client.py      # implements LLMPort (generator)
│   │       └── judge_client.py    # implements JudgePort (separate lightweight call)
│   └── api/
│       ├── routes/
│       │   ├── generate.py    # POST /api/v1/generate
│       │   └── health.py      # GET /api/v1/health — container healthcheck
│       └── schemas/generate.py    # GenerateRequest, GenerateResponse
├── Dockerfile
├── docker-compose.yml        # project-local; distinct from the solution-root one (Postgres)
└── tests/
    ├── unit/            # guardrails, prompt assembly, schema filtering — no I/O
    ├── test_routers/    # acceptance, httpx.AsyncClient
    └── eval/
        ├── golden_dataset.jsonl   # ~15-20 entries: question, allowed_tables, target_sql, expected_result
        └── run_eval.py            # replays dataset, reports exact/near-match rate
```

### Domain models

- `SchemaTable` / `SchemaColumn`: name, business-language comment, type, PK/FK flags,
  enum values (spelled out in full, not just the column type) — the in-memory
  representation of one YAML file.
- `GenerationRequest`: `question`, `profile`, `allowed_tables: list[str]`.
- `SqlCandidate`: `sql`, `intent_reformulation`.
- `JudgeVerdict`: `verdict` (`ALIGNED`/`DRIFT`/`UNCERTAIN`), `reason`.
- `GuardrailViolation`: `rule` (`blocklist`/`ast`), `reason`.
- `GenerationOutcome`: the discriminated result of the whole use case — one of
  `generated`, `needs_clarification`, `refused_out_of_schema`, `rejected_guardrail`,
  `rejected_judge`, each carrying its relevant payload.

### Ports (Protocols)

- `SchemaRepositoryPort.get_tables(allowed_tables: list[str]) -> list[SchemaTable]`
- `LLMPort.generate(system_prompt: str, question: str) -> SqlCandidate` (also detects and
  signals ambiguity via a reserved field on the raw LLM response)
- `JudgePort.evaluate(question: str, intent_reformulation: str, sql: str) -> JudgeVerdict`

## Generation pipeline (`generate_sql` use case)

**Input** (`POST /api/v1/generate`):
```json
{
  "question": "Quel est le stock actuel de la référence REF-8842 ?",
  "profile": "support",
  "allowed_tables": ["stock", "v_products_support"]
}
```
`allowed_tables` is resolved upstream by `mcp`'s access matrix and passed in as-is.

1. **Schema filtering**: `SchemaRepositoryPort.get_tables(allowed_tables)` returns only
   the YAML blocks for those tables. Unknown/unauthorized table names in the list are
   silently dropped, not errored — the caller's list is trusted but the schema is the
   ground truth of what exists.
2. **Refusal pre-check**: if the filtered schema set is empty, or the question clearly
   asks for a concept absent from the *entire* static schema (checked against the
   unfiltered table/column names, to distinguish "doesn't exist" from "not authorized"),
   return `outcome: "refused_out_of_schema"` — no LLM call.

   > **Amendement (2026-09-04)** — cette étape a été remplacée à l'implémentation. Le
   > contrôle lexical comparait la question à des identifiants de schéma anglais alors
   > que les questions sont françaises : 13 des 16 entrées du golden dataset étaient
   > refusées avant tout appel au LLM, dont 11 à tort (les 2 entrées `hors_schema`
   > l'étaient légitimement, mais par accident plutôt que par jugement). Seul le cas déterministe subsiste (schéma filtré
   > vide) ; le refus sémantique est désormais signalé par le modèle lui-même, via un
   > champ `is_out_of_schema` du JSON structuré, exactement comme l'ambiguïté l'est via
   > `is_ambiguous`. Coût assumé : une question hors-schéma consomme un appel LLM.
3. **Prompt assembly** (`build_system_prompt`): filtered schema + enum values spelled out
   + a handful of static few-shot examples from `few_shot.yaml` (curated, not the full
   golden dataset) + the business-rule glossary from `business_rules.yaml` (e.g. "CA du
   mois" definition) + the
   `CRITICAL: use only the exact column names listed above, never invent one`
   instruction + explicit read-only framing (barrier 1 of §5).
4. **Generation**: `LLMPort.generate(system_prompt, question) -> SqlCandidate` — the model
   returns both the candidate SQL and a one-line intent reformulation, used by the judge.
   Steps 4–7 share a single bounded retry budget (max 3 *total* generation attempts, not
   3 per check) — a guardrail violation and a judge `DRIFT` both count against the same
   counter; exhausting it on either check ends the loop with that check's rejection
   outcome.
5. **Ambiguity check**: if the model signals ambiguity instead of committing to an
   interpretation, skip straight to `outcome: "needs_clarification"` — no
   guardrails/judge needed on a query that was never produced.
6. **Guardrails** (`domain/guardrails.py`, deterministic, in order):
   - Blocklist: reject if any of `INSERT/UPDATE/DELETE/DROP/TRUNCATE/ALTER/CREATE/GRANT/
     REVOKE` appears as a token anywhere, including inside CTEs.
   - AST (`sqlglot.parse(sql, dialect="postgres")`): must parse to exactly one `SELECT`
     statement; every table/column reference must exist in the filtered schema.
   - On failure: re-invoke generation with the violation reason appended to context
     (counts against the shared retry budget). Exhausted → `outcome: "rejected_guardrail"`,
     logged, no SQL returned.
7. **LLM-as-judge** (§9, one structured call): given `question`, `intent_reformulation`,
   and `sql`, returns `{"verdict": "ALIGNED"|"DRIFT"|"UNCERTAIN", "reason": "..."}`.
   - `DRIFT` → re-invoke generation with the judge's reason appended (same shared
     budget), then `outcome: "rejected_judge"` if exhausted.
   - `UNCERTAIN` → `outcome: "needs_clarification"`, judge's reason surfaced.
   - `ALIGNED` → proceed.
8. **Response**: the candidate SQL is returned **as-is, never executed**.

**Output shape:**
```json
{
  "outcome": "generated",
  "sql": "SELECT quantity FROM stock WHERE product_ref = 'REF-8842'",
  "intent_reformulation": "stock actuel de la référence REF-8842",
  "judge_verdict": "ALIGNED",
  "attempts": 1
}
```
On refusal/clarification/rejection, `sql` is `null` and a `message`/`reason` field
explains why (never confirming/denying unauthorized-table existence).

## API contracts & error handling

- Follows `../../.claude/rules/api-contracts.md`: single endpoint `POST /api/v1/generate`
  (plus `GET /api/v1/health`), no response envelope, `snake_case` fields.
- `outcome` is the primary discriminant (`generated | needs_clarification |
  refused_out_of_schema | rejected_guardrail | rejected_judge`) — clients branch on this,
  not HTTP status; all of these are successful completions of the generation contract
  (200), not errors.
- `422` — Pydantic validation errors on `GenerateRequest` (missing `question`, empty
  `allowed_tables`, etc.).
- True `HTTPException` errors reserved for infrastructure failures: Azure OpenAI
  unreachable/timeout → `502`, `error_code: "LLM_UNAVAILABLE"`; malformed YAML schema
  file at startup → fails fast at boot, not per-request.
- Uniform error format `{error_code, message, correlation_id}` via a `main.py` exception
  handler, same as `rag-hybride`.
- Avoid broad try/except in the pipeline: `sqlglot.ParseError` and Azure OpenAI SDK exceptions
  are caught specifically; a catch-all FastAPI exception handler is used only to preserve the uniform error format.
- Every terminal outcome (including rejections/refusals) is logged with: timestamp,
  profile, `allowed_tables`, the question, the generated SQL (if any), outcome, and
  attempt count — per E3 ("chaque requête générée... doit être journalisée") and
  `../../.claude/rules/security.md` (this is generation-event metadata, not a business
  *result* payload, so it's in scope for logging); judge/guardrail raw LLM responses are
  not logged beyond their structured verdict.

## Testing strategy

- **Unit** (`tests/unit/`, all ports mocked, no I/O):
  - `guardrails.py`: blocklist catches destructive verbs including inside a CTE; AST
    check rejects multi-statement SQL and a reference outside the filtered schema;
    accepts a valid single `SELECT`.
  - `prompt.py`: filtered schema only includes `allowed_tables`; enum values spelled out
    verbatim; `CRITICAL` instruction always present.
  - `schema/repository.py` filtering: unauthorized/unknown table names silently dropped;
    full schema never leaks past the filter.
  - `generate_sql` orchestration with mocked `LLMPort`/`JudgePort`: each outcome branch
    (ambiguous → `needs_clarification`; judge `DRIFT` → bounded retry then
    `rejected_judge`; guardrail failure → retry with reason injected; empty
    `allowed_tables` → `refused_out_of_schema`).
- **Acceptance** (`tests/test_routers/`, `httpx.AsyncClient`, mocked Azure OpenAI adapter):
  - Happy path → `outcome: "generated"` with valid SQL.
  - Out-of-schema question → `outcome: "refused_out_of_schema"`, `sql: null`.
  - Ambiguous question ("meilleur client") → `outcome: "needs_clarification"`.
  - Guardrail-triggering mocked LLM response (e.g. `DROP TABLE`) → `outcome:
    "rejected_guardrail"`, verify retry count.
- **Eval harness** (`tests/eval/`, manual tool, not a CI gate for MVP):
  - `golden_dataset.jsonl`: ~15-20 entries per §2's four-column shape (question,
    context/allowed_tables, target SQL, expected result), covering recurring cases, a
    couple of deliberate ambiguities, and one or two out-of-schema questions.
  - `run_eval.py`: replays the dataset against the real pipeline (real Azure OpenAI call,
    no execution), compares generated SQL to target via `sqlglot`-normalized AST
    equality, reports a pass rate table by category — a starting point for the LLMOps
    CI/Evals loop (§3), not wired into CI yet.

## Deployment

- **Own `Dockerfile`** and `docker-build`/`docker-up`/`docker-down` Makefile targets —
  see rationale above. Image builds from the shared root `pyproject.toml`
  (`pip install -e ".[dev]"`, run with the solution root as build context), then copies
  `text2sql-ai/app` in. `sqlglot` is a new dependency this spec adds to the shared
  `pyproject.toml` (not currently listed).
- No database — the only external dependency is Azure OpenAI, reached via
  `AZURE_OPENAI_*` env vars injected at container runtime (`.env` for local `docker
  compose up`; real secrets from Azure Key Vault in the target deployment, per
  `../../.claude/rules/security.md`).
- Static YAML schema files (`app/infrastructure/schema/*.yaml`) are baked into the image
  at build time — no volume mount; editing them is a code change/redeploy, not a runtime
  update.
- `docker-compose.yml` (project-local, distinct from the solution-root one used for
  Postgres): a single `text2sql-ai` service with a healthcheck on `GET
  /api/v1/health`.

## Deferred (explicitly out of scope for this spec)

- Fixed/parameterized tools (`get_stock`, `get_order_status`, etc., §7) — belong to
  `sorabelsql-api`/`mcp`.
- Execution-error-driven auto-correction (§8's Postgres-error retry loop) — requires a
  round trip through `sorabelsql-api`; this spec only covers self-correction against
  text2sql-ai's own guardrail/judge rejections.
- Guardrails-AI/NeMo Guardrails framework adoption — hand-rolled blocklist + AST + judge
  is enough for MVP; a framework is a later swap behind the same `guardrails.py`/
  `JudgePort` interfaces.
- Full CI/Evals gate (§3's pipeline blocking merges on eval score) — the harness runs
  manually for now.
- Multi-domain schema splitting (§4's "beyond ~15 tables, split by domain") — not a
  concern at MVP table count.
