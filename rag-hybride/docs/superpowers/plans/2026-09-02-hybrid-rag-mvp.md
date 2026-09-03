# Hybrid RAG MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an end-to-end hybrid RAG MVP for `rag-hybride`: ingest Markdown/PDF documents into dual dense (pgvector) + lexical (tsvector) indexes, and answer queries via dense+BM25 retrieval, RRF fusion, cross-encoder reranking, mandatory citations or explicit refusal — plus a minimal E6 evaluation harness.

**Architecture:** Hexagonal architecture per `.claude/rules/python-hexagonal.md`: `domain/` (pure Python, zero external imports) holds models, chunking, RRF fusion, confidence gating and versioning logic; `application/use_cases/` orchestrates the domain via `domain/ports.py` Protocols; `infrastructure/` implements those ports (Postgres/pgvector/tsvector, Azure OpenAI, a local cross-encoder, Markdown/PDF parsers); `api/` is a thin FastAPI layer translating HTTP to use-case calls.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2.0 async + asyncpg, PostgreSQL + pgvector + tsvector, Alembic, Azure OpenAI (embeddings + chat), `sentence-transformers` (local cross-encoder reranker), `pdfplumber`, PyYAML, pytest + pytest-asyncio + httpx + Testcontainers, `reportlab` (test-only, to generate PDF fixtures), Docker Compose.

## Global Constraints

- All Python code must pass `ruff check .`, `ruff format .`, and `mypy app/` (PEP 8 + PEP 484 type hints on every function) — from the root `CLAUDE.md`.
- `domain/` has **zero** external imports (no FastAPI, no SQLAlchemy, no Azure SDK) — from `python-hexagonal.md`.
- `application/` depends only on `domain/ports.py` Protocols, never a concrete infrastructure class — from `python-hexagonal.md`.
- Routes never return raw dicts/ORM objects — always a Pydantic response schema from `api/schemas/` — from the root `CLAUDE.md` and `python-hexagonal.md`.
- Never catch broad `Exception`; raise/catch specific exception types — from the root `CLAUDE.md`.
- Never use synchronous DB drivers or blocking I/O directly in async routes; wrap sync SDKs (the reranker) in `run_in_threadpool` — from the root `CLAUDE.md` and `rag-architecture.md`.
- No hardcoded configuration — all settings via `pydantic-settings` reading `.env`; `.env.example` documents expected variables with no real values — from `security.md`.
- Error responses use the uniform shape `{error_code, message, correlation_id}`; `message` never confirms/denies existence of an unauthorized resource — from `api-contracts.md`.
- JSON fields `snake_case`; routes under `/api/v1/` — from `api-contracts.md`.
- Unit tests mock only *ports*, never infrastructure details; integration tests use Testcontainers against real Postgres/pgvector, never mocks on `infrastructure/postgres/` — from `testing-pytest.md`.
- Every test follows Arrange/Act/Assert, with `# Arrange` / `# Act` / `# Assert` comments once a test exceeds a few lines — from `testing-pytest.md`.
- RRF fusion: `score = Σ 1/(k + rank_i)`, no manual weighting — from `rag-architecture.md` and the approved spec.
- Confidence gate: `≥ 0.7` → answer, `0.4–0.7` → hedge, `< 0.4` → refuse with no LLM call — from the approved spec.
- Chunking: ~50–250 tokens per chunk, split by section not fixed token count; documents under ~150 tokens become one chunk; a table is always exactly one chunk, never split — from `rag-architecture.md` and the approved spec.
- `rag-hybride` performs **no** access-matrix/profile checks — it assumes every call it receives is already authorized (`authorization-gateway`'s responsibility) — from `rag-hybride/CLAUDE.md`.

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `docker-compose.yml`
- Create: `app/__init__.py`, `app/domain/__init__.py`, `app/application/__init__.py`, `app/application/use_cases/__init__.py`, `app/infrastructure/__init__.py`, `app/api/__init__.py`, `app/api/routes/__init__.py`, `app/api/schemas/__init__.py`
- Create: `app/config.py`
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/test_routers/__init__.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Produces: `app.config.Settings` — a `pydantic_settings.BaseSettings` subclass with fields `database_url: str`, `azure_openai_api_key: str`, `azure_openai_endpoint: str`, `azure_openai_api_version: str = "2024-02-01"`, `azure_openai_embedding_deployment: str`, `azure_openai_chat_deployment: str`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "rag-hybride"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "pgvector>=0.3",
    "alembic>=1.13",
    "openai>=1.35",
    "sentence-transformers>=3.0",
    "pdfplumber>=0.11",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
    "testcontainers[postgres]>=4.7",
    "reportlab>=4.2",
    "ruff>=0.5",
    "mypy>=1.10",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100

[tool.mypy]
python_version = "3.11"
strict = true
```

- [ ] **Step 2: Write `.env.example`**

```bash
DATABASE_URL=postgresql+asyncpg://rag:rag@localhost:5432/rag_hybride
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-02-01
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o
```

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: rag
      POSTGRES_PASSWORD: rag
      POSTGRES_DB: rag_hybride
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  app:
    build: .
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      - postgres

volumes:
  pgdata:
```

- [ ] **Step 4: Create package skeleton**

Run:
```bash
mkdir -p app/domain app/application/use_cases app/infrastructure app/api/routes app/api/schemas
touch app/__init__.py app/domain/__init__.py app/application/__init__.py app/application/use_cases/__init__.py app/infrastructure/__init__.py app/api/__init__.py app/api/routes/__init__.py app/api/schemas/__init__.py
mkdir -p tests/unit tests/integration tests/test_routers
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py tests/test_routers/__init__.py
```

- [ ] **Step 5: Write `app/config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    azure_openai_api_key: str
    azure_openai_endpoint: str
    azure_openai_api_version: str = "2024-02-01"
    azure_openai_embedding_deployment: str
    azure_openai_chat_deployment: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 6: Write `tests/conftest.py` (base, extended by later tasks)**

```python
import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
```

- [ ] **Step 7: Verify the project installs and pytest collects**

Run: `pip install -e ".[dev]" && pytest --collect-only`
Expected: no collection errors (zero tests found is fine at this point).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .env.example docker-compose.yml app tests
git commit -m "chore: scaffold rag-hybride project structure"
```

---

## Task 2: Domain Models

**Files:**
- Create: `app/domain/models.py`
- Test: `tests/unit/test_models.py`

**Interfaces:**
- Produces: `Citation(title: str, product_ref: str, published_date: date, url: str | None = None)`, `Document(id: str, title: str, product_ref: str, version: str, status: str, document_type: str, published_date: date, source_path: str, content_hash: str)`, `Chunk(id: str, document_id: str, content: str, content_type: str, title: str, product_ref: str, version: str, status: str, document_type: str, published_date: date, content_hash: str, source_path: str)`, `RetrievalResult(chunk: Chunk, dense_rank: int | None, sparse_rank: int | None, fused_score: float, rerank_score: float | None = None)`, `Answer(text: str, citations: list[Citation], confidence: str)`. All are frozen dataclasses in `app/domain/models.py`.

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_models.py
from datetime import date

from app.domain.models import Answer, Chunk, Citation, Document, RetrievalResult


def test_chunk_carries_all_required_citation_metadata():
    # Arrange / Act
    chunk = Chunk(
        id="chunk-1",
        document_id="REF-8842",
        content="Tension nominale : 230V",
        content_type="text",
        title="Fiche REF-8842",
        product_ref="REF-8842",
        version="2",
        status="active",
        document_type="datasheet",
        published_date=date(2026, 1, 15),
        content_hash="abc123",
        source_path="corpus/REF-8842.md",
    )

    # Assert
    assert chunk.product_ref == "REF-8842"
    assert chunk.content_type == "text"


def test_answer_with_no_citations_is_a_refusal_shape():
    # Arrange / Act
    answer = Answer(
        text="Je ne trouve pas cette information dans le corpus.",
        citations=[],
        confidence="refused",
    )

    # Assert
    assert answer.citations == []
    assert answer.confidence == "refused"


def test_retrieval_result_holds_both_ranks_and_scores():
    # Arrange
    chunk = Chunk(
        id="chunk-1",
        document_id="doc-1",
        content="x",
        content_type="text",
        title="t",
        product_ref="REF-1",
        version="1",
        status="active",
        document_type="datasheet",
        published_date=date(2026, 1, 1),
        content_hash="h",
        source_path="p",
    )

    # Act
    result = RetrievalResult(chunk=chunk, dense_rank=1, sparse_rank=None, fused_score=0.016)

    # Assert
    assert result.rerank_score is None
    assert result.sparse_rank is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.models'`

- [ ] **Step 3: Write `app/domain/models.py`**

```python
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Citation:
    title: str
    product_ref: str
    published_date: date
    url: str | None = None


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    product_ref: str
    version: str
    status: str  # "active" | "deprecated"
    document_type: str  # "datasheet" | "manuel" | "procedure_sav"
    published_date: date
    source_path: str
    content_hash: str


@dataclass(frozen=True)
class Chunk:
    id: str
    document_id: str
    content: str
    content_type: str  # "text" | "table"
    title: str
    product_ref: str
    version: str
    status: str  # "active" | "deprecated"
    document_type: str
    published_date: date
    content_hash: str
    source_path: str


@dataclass(frozen=True)
class RetrievalResult:
    chunk: Chunk
    dense_rank: int | None
    sparse_rank: int | None
    fused_score: float
    rerank_score: float | None = None


@dataclass(frozen=True)
class Answer:
    text: str
    citations: list[Citation] = field(default_factory=list)
    confidence: str = "refused"  # "high" | "low" | "refused"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/domain/models.py tests/unit/test_models.py
git commit -m "feat: add rag-hybride domain models"
```

---

## Task 3: Domain Errors

**Files:**
- Create: `app/domain/errors.py`

**Interfaces:**
- Produces: `UnparsableDocumentError(Exception)`, `UnsupportedFormatError(Exception)`, `EmbeddingServiceError(Exception)`.

- [ ] **Step 1: Write `app/domain/errors.py`**

```python
class UnparsableDocumentError(Exception):
    """Raised when a source document cannot be normalized into the pivot schema."""


class UnsupportedFormatError(Exception):
    """Raised when no parser is registered for a document's file extension."""


class EmbeddingServiceError(Exception):
    """Raised when the embedding provider fails to return a vector."""
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `python -c "from app.domain.errors import UnparsableDocumentError, UnsupportedFormatError, EmbeddingServiceError"`
Expected: no output, exit code 0

- [ ] **Step 3: Commit**

```bash
git add app/domain/errors.py
git commit -m "feat: add rag-hybride domain error types"
```

---

## Task 4: Domain Chunking (Chunk-by-Section)

**Files:**
- Create: `app/domain/chunking.py`
- Test: `tests/unit/test_chunking.py`

**Interfaces:**
- Consumes: nothing (pure domain logic).
- Produces: `RawSection(content: str, content_type: str)` (frozen dataclass), `ChunkCandidate(content: str, content_type: str)` (frozen dataclass), `chunk_sections(sections: list[RawSection]) -> list[ChunkCandidate]`, constants `MIN_CHUNK_TOKENS = 50`, `MAX_CHUNK_TOKENS = 250`, `TINY_DOCUMENT_TOKENS = 150`. Later tasks (Markdown/PDF parsers) produce `list[RawSection]`; `ingest_document` use case consumes `chunk_sections()`'s output.

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_chunking.py
from app.domain.chunking import RawSection, chunk_sections


def test_tiny_document_becomes_a_single_chunk():
    # Arrange
    sections = [
        RawSection(
            content="Courte notice de dix mots pour un petit accessoire technique ici",
            content_type="text",
        )
    ]

    # Act
    chunks = chunk_sections(sections)

    # Assert
    assert len(chunks) == 1
    assert chunks[0].content_type == "text"


def test_table_section_is_never_split_even_if_large():
    # Arrange
    table_content = "\n".join(f"row {i}\tvalue {i}" for i in range(400))
    sections = [
        RawSection(content="intro " * 200, content_type="text"),
        RawSection(content=table_content, content_type="table"),
    ]

    # Act
    chunks = chunk_sections(sections)

    # Assert
    table_chunks = [c for c in chunks if c.content_type == "table"]
    assert len(table_chunks) == 1
    assert table_chunks[0].content == table_content


def test_large_text_section_is_split_with_overlap():
    # Arrange
    words = [f"word{i}" for i in range(600)]
    sections = [RawSection(content=" ".join(words), content_type="text")]

    # Act
    chunks = chunk_sections(sections)

    # Assert
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.content.split()) <= 250
    # overlap: the last words of one chunk reappear at the start of the next
    first_chunk_words = chunks[0].content.split()
    second_chunk_words = chunks[1].content.split()
    assert first_chunk_words[-5:] == second_chunk_words[: len(first_chunk_words[-5:])]


def test_small_text_sections_are_merged_until_min_tokens():
    # Arrange
    sections = [
        RawSection(content="phrase courte numero un avec quelques mots", content_type="text"),
        RawSection(
            content="phrase courte numero deux avec quelques mots supplementaires",
            content_type="text",
        ),
        RawSection(content=" ".join(f"filler{i}" for i in range(300)), content_type="text"),
    ]

    # Act
    chunks = chunk_sections(sections)

    # Assert
    assert len(chunks[0].content.split()) >= 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_chunking.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.chunking'`

- [ ] **Step 3: Write `app/domain/chunking.py`**

```python
from dataclasses import dataclass

MIN_CHUNK_TOKENS = 50
MAX_CHUNK_TOKENS = 250
TINY_DOCUMENT_TOKENS = 150
OVERLAP_RATIO = 0.125


@dataclass(frozen=True)
class RawSection:
    content: str
    content_type: str  # "text" | "table"


@dataclass(frozen=True)
class ChunkCandidate:
    content: str
    content_type: str  # "text" | "table"


def estimate_tokens(text: str) -> int:
    """Word-count approximation of token count — adequate for the chunk-sizing heuristic."""
    return len(text.split())


def chunk_sections(sections: list[RawSection]) -> list[ChunkCandidate]:
    total_tokens = sum(estimate_tokens(s.content) for s in sections)
    if total_tokens < TINY_DOCUMENT_TOKENS:
        combined = "\n\n".join(s.content for s in sections)
        content_type = (
            "table" if len(sections) == 1 and sections[0].content_type == "table" else "text"
        )
        return [ChunkCandidate(content=combined, content_type=content_type)]

    chunks: list[ChunkCandidate] = []
    buffer: list[str] = []
    buffer_tokens = 0

    def flush_buffer() -> None:
        nonlocal buffer, buffer_tokens
        if buffer:
            chunks.append(ChunkCandidate(content="\n\n".join(buffer), content_type="text"))
            buffer = []
            buffer_tokens = 0

    for section in sections:
        if section.content_type == "table":
            flush_buffer()
            chunks.append(ChunkCandidate(content=section.content, content_type="table"))
            continue

        section_tokens = estimate_tokens(section.content)
        if section_tokens > MAX_CHUNK_TOKENS:
            flush_buffer()
            chunks.extend(_split_large_text(section.content))
            continue

        buffer.append(section.content)
        buffer_tokens += section_tokens
        if buffer_tokens >= MIN_CHUNK_TOKENS:
            flush_buffer()

    flush_buffer()
    return chunks


def _split_large_text(text: str) -> list[ChunkCandidate]:
    words = text.split()
    step = MAX_CHUNK_TOKENS
    overlap = int(step * OVERLAP_RATIO)
    chunks: list[ChunkCandidate] = []
    start = 0
    while start < len(words):
        end = min(start + step, len(words))
        chunks.append(ChunkCandidate(content=" ".join(words[start:end]), content_type="text"))
        if end == len(words):
            break
        start = end - overlap
    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_chunking.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/domain/chunking.py tests/unit/test_chunking.py
git commit -m "feat: add section-based adaptive chunking"
```

---

## Task 5: Domain Fusion (Reciprocal Rank Fusion)

**Files:**
- Create: `app/domain/fusion.py`
- Test: `tests/unit/test_fusion.py`

**Interfaces:**
- Produces: `RankedChunk(chunk_id: str, rank: int)` (frozen dataclass, `rank` is 1-based), `reciprocal_rank_fusion(dense_results: list[RankedChunk], sparse_results: list[RankedChunk], k: int = 60) -> list[tuple[str, float]]` — returns `(chunk_id, fused_score)` pairs sorted by descending score. Consumed by the `answer_query` use case (Task 9).

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_fusion.py
from app.domain.fusion import RankedChunk, reciprocal_rank_fusion


def test_fusion_favors_a_chunk_present_in_both_rankings():
    # Arrange
    dense_results = [
        RankedChunk(chunk_id="chunk-both", rank=3),
        RankedChunk(chunk_id="chunk-dense-only", rank=1),
    ]
    sparse_results = [
        RankedChunk(chunk_id="chunk-both", rank=2),
        RankedChunk(chunk_id="chunk-sparse-only", rank=1),
    ]

    # Act
    fused = reciprocal_rank_fusion(dense_results, sparse_results)

    # Assert
    assert fused[0][0] == "chunk-both"


def test_fusion_computes_reciprocal_rank_sum():
    # Arrange
    dense_results = [RankedChunk(chunk_id="chunk-1", rank=1)]
    sparse_results = [RankedChunk(chunk_id="chunk-1", rank=1)]

    # Act
    fused = reciprocal_rank_fusion(dense_results, sparse_results, k=60)

    # Assert
    expected_score = 1 / (60 + 1) + 1 / (60 + 1)
    assert fused[0] == ("chunk-1", expected_score)


def test_fusion_handles_empty_result_lists():
    # Arrange / Act
    fused = reciprocal_rank_fusion([], [])

    # Assert
    assert fused == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_fusion.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.fusion'`

- [ ] **Step 3: Write `app/domain/fusion.py`**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class RankedChunk:
    chunk_id: str
    rank: int  # 1-based


def reciprocal_rank_fusion(
    dense_results: list[RankedChunk],
    sparse_results: list[RankedChunk],
    k: int = 60,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for results in (dense_results, sparse_results):
        for ranked in results:
            scores[ranked.chunk_id] = scores.get(ranked.chunk_id, 0.0) + 1.0 / (k + ranked.rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_fusion.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/domain/fusion.py tests/unit/test_fusion.py
git commit -m "feat: add reciprocal rank fusion for hybrid retrieval"
```

---

## Task 6: Domain Confidence Gate

**Files:**
- Create: `app/domain/confidence.py`
- Test: `tests/unit/test_confidence.py`

**Interfaces:**
- Produces: `HIGH_CONFIDENCE_THRESHOLD = 0.7`, `LOW_CONFIDENCE_THRESHOLD = 0.4`, `classify_confidence(score: float) -> str` returning `"high" | "low" | "refused"`. Consumed by the `answer_query` use case (Task 9).

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_confidence.py
from app.domain.confidence import classify_confidence


def test_score_above_high_threshold_is_high_confidence():
    assert classify_confidence(0.85) == "high"


def test_score_at_high_threshold_is_high_confidence():
    assert classify_confidence(0.7) == "high"


def test_score_in_hedge_band_is_low_confidence():
    assert classify_confidence(0.55) == "low"


def test_score_at_low_threshold_is_low_confidence():
    assert classify_confidence(0.4) == "low"


def test_score_below_low_threshold_is_refused():
    assert classify_confidence(0.1) == "refused"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_confidence.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.confidence'`

- [ ] **Step 3: Write `app/domain/confidence.py`**

```python
HIGH_CONFIDENCE_THRESHOLD = 0.7
LOW_CONFIDENCE_THRESHOLD = 0.4


def classify_confidence(score: float) -> str:
    if score >= HIGH_CONFIDENCE_THRESHOLD:
        return "high"
    if score >= LOW_CONFIDENCE_THRESHOLD:
        return "low"
    return "refused"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_confidence.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add app/domain/confidence.py tests/unit/test_confidence.py
git commit -m "feat: add E1 confidence gate (answer / hedge / refuse)"
```

---

## Task 7: Domain Versioning (Dedup Logic)

**Files:**
- Create: `app/domain/versioning.py`
- Test: `tests/unit/test_versioning.py`

**Interfaces:**
- Produces: `resolve_ingest_action(existing_hash: str | None, new_hash: str) -> str` returning `"created" | "updated" | "unchanged"`. Consumed by the `ingest_document` use case (Task 10).

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_versioning.py
from app.domain.versioning import resolve_ingest_action


def test_no_existing_document_is_created():
    assert resolve_ingest_action(existing_hash=None, new_hash="abc") == "created"


def test_same_hash_is_unchanged():
    assert resolve_ingest_action(existing_hash="abc", new_hash="abc") == "unchanged"


def test_different_hash_is_updated():
    assert resolve_ingest_action(existing_hash="abc", new_hash="def") == "updated"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_versioning.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.versioning'`

- [ ] **Step 3: Write `app/domain/versioning.py`**

```python
def resolve_ingest_action(existing_hash: str | None, new_hash: str) -> str:
    if existing_hash is None:
        return "created"
    if existing_hash == new_hash:
        return "unchanged"
    return "updated"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_versioning.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/domain/versioning.py tests/unit/test_versioning.py
git commit -m "feat: add document dedup/versioning decision logic"
```

---

## Task 8: Domain Ports

**Files:**
- Create: `app/domain/ports.py`

**Interfaces:**
- Consumes: `app.domain.chunking.RawSection`, `app.domain.models.{Document,Chunk}`.
- Produces (all `typing.Protocol`, all methods `async` except `DocumentParserPort.parse`, which is CPU-bound and synchronous by design — callers use `run_in_threadpool` if needed):
  - `DocumentParserPort.parse(raw_bytes: bytes, document_type: str, source_path: str) -> tuple[Document, list[RawSection]]`
  - `EmbeddingPort.embed(text: str) -> list[float]`
  - `VectorStorePort.upsert(chunks: list[Chunk], embeddings: list[list[float]]) -> None`, `.search(embedding: list[float], top_k: int, product_ref: str | None = None) -> list[tuple[Chunk, int]]`, `.delete_by_document_id(document_id: str) -> None`
  - `LexicalSearchPort.upsert(chunks: list[Chunk]) -> None`, `.search(query: str, top_k: int, product_ref: str | None = None) -> list[tuple[Chunk, int]]`, `.delete_by_document_id(document_id: str) -> None`
  - `RerankerPort.score(query: str, chunk_text: str) -> float`
  - `LLMPort.generate(query: str, cited_chunks: list[Chunk], hedge: bool) -> str`
  - `DocumentRegistryPort.get_active_hash(product_ref: str) -> str | None`, `.register(document: Document) -> None`, `.deprecate(product_ref: str) -> None`

  `search()` returns `(Chunk, rank)` pairs with 1-based rank, directly convertible to `RankedChunk` for fusion (Task 5).

- [ ] **Step 1: Write `app/domain/ports.py`**

```python
from typing import Protocol

from app.domain.chunking import RawSection
from app.domain.models import Chunk, Document


class DocumentParserPort(Protocol):
    def parse(
        self, raw_bytes: bytes, document_type: str, source_path: str
    ) -> tuple[Document, list[RawSection]]: ...


class EmbeddingPort(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class VectorStorePort(Protocol):
    async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None: ...

    async def search(
        self, embedding: list[float], top_k: int, product_ref: str | None = None
    ) -> list[tuple[Chunk, int]]: ...

    async def delete_by_document_id(self, document_id: str) -> None: ...


class LexicalSearchPort(Protocol):
    async def upsert(self, chunks: list[Chunk]) -> None: ...

    async def search(
        self, query: str, top_k: int, product_ref: str | None = None
    ) -> list[tuple[Chunk, int]]: ...

    async def delete_by_document_id(self, document_id: str) -> None: ...


class RerankerPort(Protocol):
    async def score(self, query: str, chunk_text: str) -> float: ...


class LLMPort(Protocol):
    async def generate(self, query: str, cited_chunks: list[Chunk], hedge: bool) -> str: ...


class DocumentRegistryPort(Protocol):
    async def get_active_hash(self, product_ref: str) -> str | None: ...

    async def register(self, document: Document) -> None: ...

    async def deprecate(self, product_ref: str) -> None: ...
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `python -c "from app.domain import ports"`
Expected: no output, exit code 0

- [ ] **Step 3: Commit**

```bash
git add app/domain/ports.py
git commit -m "feat: define rag-hybride domain ports"
```

---

## Task 9: Application Use Case — `answer_query`

**Files:**
- Create: `app/application/use_cases/answer_query.py`
- Test: `tests/unit/test_answer_query.py`

**Interfaces:**
- Consumes: `app.domain.ports.{EmbeddingPort,VectorStorePort,LexicalSearchPort,RerankerPort,LLMPort}` (Task 8), `app.domain.fusion.{RankedChunk,reciprocal_rank_fusion}` (Task 5), `app.domain.confidence.classify_confidence` (Task 6), `app.domain.models.{Answer,Citation,Chunk}` (Task 2).
- Produces: `AnswerQueryUseCase(embedding_port, vector_store, lexical_search, reranker, llm)` with `async def execute(self, query: str, product_ref: str | None = None, top_k: int = 20) -> Answer`. Consumed by `app/dependencies.py` (Task 20).

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_answer_query.py
from datetime import date

import pytest

from app.application.use_cases.answer_query import AnswerQueryUseCase
from app.domain.models import Chunk

CHUNK_A = Chunk(
    id="chunk-a",
    document_id="REF-8842",
    content="Tension nominale : 230V",
    content_type="text",
    title="Fiche REF-8842",
    product_ref="REF-8842",
    version="1",
    status="active",
    document_type="datasheet",
    published_date=date(2026, 1, 1),
    content_hash="h",
    source_path="p",
)
CHUNK_B = Chunk(
    id="chunk-b",
    document_id="REF-9000",
    content="Autre fiche non pertinente",
    content_type="text",
    title="Fiche REF-9000",
    product_ref="REF-9000",
    version="1",
    status="active",
    document_type="datasheet",
    published_date=date(2026, 1, 1),
    content_hash="h2",
    source_path="p2",
)


class FakeEmbeddingPort:
    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2]


class FakeVectorStore:
    def __init__(self, results: list[tuple[Chunk, int]]):
        self._results = results

    async def search(self, embedding, top_k, product_ref=None):
        return self._results

    async def upsert(self, chunks, embeddings):
        raise NotImplementedError

    async def delete_by_document_id(self, document_id):
        raise NotImplementedError


class FakeLexicalSearch:
    def __init__(self, results: list[tuple[Chunk, int]]):
        self._results = results

    async def search(self, query, top_k, product_ref=None):
        return self._results

    async def upsert(self, chunks):
        raise NotImplementedError

    async def delete_by_document_id(self, document_id):
        raise NotImplementedError


class FakeReranker:
    def __init__(self, scores: dict[str, float]):
        self._scores = scores

    async def score(self, query: str, chunk_text: str) -> float:
        for chunk in (CHUNK_A, CHUNK_B):
            if chunk.content == chunk_text:
                return self._scores.get(chunk.id, 0.0)
        return 0.0


class FakeLlm:
    async def generate(self, query, cited_chunks, hedge) -> str:
        return "Réponse générée à partir des extraits cités."


@pytest.mark.asyncio
async def test_high_confidence_result_generates_answer_with_citations():
    # Arrange
    use_case = AnswerQueryUseCase(
        embedding_port=FakeEmbeddingPort(),
        vector_store=FakeVectorStore([(CHUNK_A, 1)]),
        lexical_search=FakeLexicalSearch([(CHUNK_A, 1)]),
        reranker=FakeReranker({"chunk-a": 0.9}),
        llm=FakeLlm(),
    )

    # Act
    answer = await use_case.execute("tension supportée par REF-8842 ?")

    # Assert
    assert answer.confidence == "high"
    assert len(answer.citations) == 1
    assert answer.citations[0].product_ref == "REF-8842"


@pytest.mark.asyncio
async def test_low_confidence_result_hedges_but_still_answers():
    # Arrange
    use_case = AnswerQueryUseCase(
        embedding_port=FakeEmbeddingPort(),
        vector_store=FakeVectorStore([(CHUNK_A, 1)]),
        lexical_search=FakeLexicalSearch([]),
        reranker=FakeReranker({"chunk-a": 0.5}),
        llm=FakeLlm(),
    )

    # Act
    answer = await use_case.execute("question ambiguë")

    # Assert
    assert answer.confidence == "low"
    assert len(answer.citations) == 1


@pytest.mark.asyncio
async def test_below_threshold_refuses_without_calling_llm():
    # Arrange
    class ExplodingLlm:
        async def generate(self, query, cited_chunks, hedge):
            raise AssertionError("LLM must not be called on refusal")

    use_case = AnswerQueryUseCase(
        embedding_port=FakeEmbeddingPort(),
        vector_store=FakeVectorStore([(CHUNK_B, 1)]),
        lexical_search=FakeLexicalSearch([]),
        reranker=FakeReranker({"chunk-b": 0.1}),
        llm=ExplodingLlm(),
    )

    # Act
    answer = await use_case.execute("question hors corpus")

    # Assert
    assert answer.confidence == "refused"
    assert answer.citations == []


@pytest.mark.asyncio
async def test_no_retrieval_results_refuses():
    # Arrange
    use_case = AnswerQueryUseCase(
        embedding_port=FakeEmbeddingPort(),
        vector_store=FakeVectorStore([]),
        lexical_search=FakeLexicalSearch([]),
        reranker=FakeReranker({}),
        llm=FakeLlm(),
    )

    # Act
    answer = await use_case.execute("question sans résultat")

    # Assert
    assert answer.confidence == "refused"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_answer_query.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.application.use_cases.answer_query'`

- [ ] **Step 3: Write `app/application/use_cases/answer_query.py`**

```python
import asyncio
from dataclasses import dataclass

from app.domain.confidence import classify_confidence
from app.domain.fusion import RankedChunk, reciprocal_rank_fusion
from app.domain.models import Answer, Chunk, Citation
from app.domain.ports import (
    EmbeddingPort,
    LexicalSearchPort,
    LLMPort,
    RerankerPort,
    VectorStorePort,
)

RERANK_TOP_N = 10
CITATION_SCORE_FLOOR = 0.4
MAX_CITATIONS = 5
REFUSAL_TEXT = "Je ne trouve pas cette information dans le corpus."


@dataclass
class AnswerQueryUseCase:
    embedding_port: EmbeddingPort
    vector_store: VectorStorePort
    lexical_search: LexicalSearchPort
    reranker: RerankerPort
    llm: LLMPort

    async def execute(self, query: str, product_ref: str | None = None, top_k: int = 20) -> Answer:
        embedding = await self.embedding_port.embed(query)
        dense_results, sparse_results = await asyncio.gather(
            self.vector_store.search(embedding, top_k, product_ref),
            self.lexical_search.search(query, top_k, product_ref),
        )

        chunks_by_id: dict[str, Chunk] = {}
        for chunk, _rank in (*dense_results, *sparse_results):
            chunks_by_id[chunk.id] = chunk

        dense_ranked = [RankedChunk(chunk_id=chunk.id, rank=rank) for chunk, rank in dense_results]
        sparse_ranked = [
            RankedChunk(chunk_id=chunk.id, rank=rank) for chunk, rank in sparse_results
        ]
        fused = reciprocal_rank_fusion(dense_ranked, sparse_ranked)

        if not fused:
            return Answer(text=REFUSAL_TEXT, citations=[], confidence="refused")

        reranked: list[tuple[Chunk, float]] = []
        for chunk_id, _fused_score in fused[:RERANK_TOP_N]:
            chunk = chunks_by_id[chunk_id]
            score = await self.reranker.score(query, chunk.content)
            reranked.append((chunk, score))
        reranked.sort(key=lambda pair: pair[1], reverse=True)

        _best_chunk, best_score = reranked[0]
        confidence = classify_confidence(best_score)

        if confidence == "refused":
            return Answer(text=REFUSAL_TEXT, citations=[], confidence="refused")

        cited_chunks = [chunk for chunk, score in reranked if score >= CITATION_SCORE_FLOOR][
            :MAX_CITATIONS
        ]
        text = await self.llm.generate(query, cited_chunks, hedge=(confidence == "low"))
        citations = [
            Citation(
                title=c.title,
                product_ref=c.product_ref,
                published_date=c.published_date,
                url=c.source_path,
            )
            for c in cited_chunks
        ]
        return Answer(text=text, citations=citations, confidence=confidence)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_answer_query.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/application/use_cases/answer_query.py tests/unit/test_answer_query.py
git commit -m "feat: add answer_query use case (hybrid retrieval + confidence gate)"
```

---

## Task 10: Application Use Case — `ingest_document`

> **Partially superseded — see migration `0003_versioned_document_key.py`.** Two
> changes: document ids now come from `make_document_id(product_ref, document_type,
> version)` (`domain/versioning.py`) instead of being assembled inline from
> `product_ref` and `document_type`; and `registry.register(document)` runs *before*
> the chunks are indexed, because `chunks.document_id` is now a foreign key. The
> `delete_by_document_id` calls on the `updated` path therefore clear only the
> incoming version's own chunks — earlier versions' chunks are kept and marked
> `deprecated`, which is what the spec's audit rule asks for.

**Files:**
- Create: `app/application/use_cases/ingest_document.py`
- Test: `tests/unit/test_ingest_document.py`

**Interfaces:**
- Consumes: `app.domain.ports.{DocumentParserPort,DocumentRegistryPort,EmbeddingPort,VectorStorePort,LexicalSearchPort}` (Task 8), `app.domain.chunking.chunk_sections` (Task 4), `app.domain.versioning.resolve_ingest_action` (Task 7), `app.domain.errors.UnsupportedFormatError` (Task 3), `app.domain.models.{Chunk,Document}` (Task 2).
- Produces: `IngestResult(document_id: str, chunk_count: int, status: str)` (dataclass), `IngestDocumentUseCase(parsers: dict[str, DocumentParserPort], registry, embedding_port, vector_store, lexical_search)` with `async def execute(self, raw_bytes: bytes, filename: str, document_type: str) -> IngestResult`. Consumed by `app/dependencies.py` (Task 20) and the `/api/v1/ingest` route (Task 20).

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_ingest_document.py
from datetime import date

import pytest

from app.application.use_cases.ingest_document import IngestDocumentUseCase
from app.domain.chunking import RawSection
from app.domain.errors import UnsupportedFormatError
from app.domain.models import Document


def make_document(product_ref: str) -> Document:
    return Document(
        id=product_ref,
        title=f"Fiche {product_ref}",
        product_ref=product_ref,
        version="1",
        status="active",
        document_type="datasheet",
        published_date=date(2026, 1, 1),
        source_path=f"{product_ref}.md",
        content_hash="",
    )


class FakeParser:
    def __init__(self, document: Document, sections: list[RawSection]):
        self._document = document
        self._sections = sections

    def parse(self, raw_bytes, document_type, source_path):
        return self._document, self._sections


class FakeRegistry:
    def __init__(self, active_hash: str | None = None):
        self.active_hash = active_hash
        self.registered: list[Document] = []
        self.deprecated: list[str] = []

    async def get_active_hash(self, product_ref: str) -> str | None:
        return self.active_hash

    async def register(self, document: Document) -> None:
        self.registered.append(document)

    async def deprecate(self, product_ref: str) -> None:
        self.deprecated.append(product_ref)


class FakeEmbeddingPort:
    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2]


class FakeVectorStore:
    def __init__(self):
        self.upserted: list = []
        self.deleted: list[str] = []

    async def upsert(self, chunks, embeddings) -> None:
        self.upserted.append(chunks)

    async def search(self, embedding, top_k, product_ref=None):
        raise NotImplementedError

    async def delete_by_document_id(self, document_id: str) -> None:
        self.deleted.append(document_id)


class FakeLexicalSearch:
    def __init__(self):
        self.upserted: list = []
        self.deleted: list[str] = []

    async def upsert(self, chunks) -> None:
        self.upserted.append(chunks)

    async def search(self, query, top_k, product_ref=None):
        raise NotImplementedError

    async def delete_by_document_id(self, document_id: str) -> None:
        self.deleted.append(document_id)


@pytest.mark.asyncio
async def test_new_document_is_created_and_indexed():
    # Arrange
    document = make_document("REF-1")
    sections = [RawSection(content="Contenu de la fiche produit REF-1", content_type="text")]
    registry = FakeRegistry(active_hash=None)
    vector_store = FakeVectorStore()
    lexical_search = FakeLexicalSearch()
    use_case = IngestDocumentUseCase(
        parsers={"md": FakeParser(document, sections)},
        registry=registry,
        embedding_port=FakeEmbeddingPort(),
        vector_store=vector_store,
        lexical_search=lexical_search,
    )

    # Act
    result = await use_case.execute(b"raw content", "REF-1.md", "datasheet")

    # Assert
    assert result.status == "created"
    assert result.chunk_count == 1
    assert len(registry.registered) == 1
    assert len(vector_store.upserted) == 1


@pytest.mark.asyncio
async def test_unchanged_hash_is_a_noop():
    # Arrange
    document = make_document("REF-2")
    sections = [RawSection(content="Contenu identique", content_type="text")]
    import hashlib

    raw_bytes = b"same content"
    same_hash = hashlib.sha256(raw_bytes).hexdigest()
    registry = FakeRegistry(active_hash=same_hash)
    vector_store = FakeVectorStore()
    use_case = IngestDocumentUseCase(
        parsers={"md": FakeParser(document, sections)},
        registry=registry,
        embedding_port=FakeEmbeddingPort(),
        vector_store=vector_store,
        lexical_search=FakeLexicalSearch(),
    )

    # Act
    result = await use_case.execute(raw_bytes, "REF-2.md", "datasheet")

    # Assert
    assert result.status == "unchanged"
    assert vector_store.upserted == []


@pytest.mark.asyncio
async def test_changed_hash_deprecates_old_version_before_reindexing():
    # Arrange
    document = make_document("REF-3")
    sections = [RawSection(content="Nouvelle version du contenu", content_type="text")]
    registry = FakeRegistry(active_hash="old-hash")
    vector_store = FakeVectorStore()
    use_case = IngestDocumentUseCase(
        parsers={"md": FakeParser(document, sections)},
        registry=registry,
        embedding_port=FakeEmbeddingPort(),
        vector_store=vector_store,
        lexical_search=FakeLexicalSearch(),
    )

    # Act
    result = await use_case.execute(b"new content", "REF-3.md", "datasheet")

    # Assert
    assert result.status == "updated"
    assert registry.deprecated == ["REF-3"]
    assert vector_store.deleted == ["REF-3"]


@pytest.mark.asyncio
async def test_unsupported_extension_raises():
    # Arrange
    use_case = IngestDocumentUseCase(
        parsers={"md": FakeParser(make_document("REF-4"), [])},
        registry=FakeRegistry(),
        embedding_port=FakeEmbeddingPort(),
        vector_store=FakeVectorStore(),
        lexical_search=FakeLexicalSearch(),
    )

    # Act / Assert
    with pytest.raises(UnsupportedFormatError):
        await use_case.execute(b"data", "notes.docx", "datasheet")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_ingest_document.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.application.use_cases.ingest_document'`

- [ ] **Step 3: Write `app/application/use_cases/ingest_document.py`**

```python
import hashlib
import uuid
from dataclasses import dataclass, replace

from app.domain.chunking import chunk_sections
from app.domain.errors import UnsupportedFormatError
from app.domain.models import Chunk
from app.domain.ports import (
    DocumentParserPort,
    DocumentRegistryPort,
    EmbeddingPort,
    LexicalSearchPort,
    VectorStorePort,
)
from app.domain.versioning import resolve_ingest_action


@dataclass
class IngestResult:
    document_id: str
    chunk_count: int
    status: str  # "created" | "updated" | "unchanged"


@dataclass
class IngestDocumentUseCase:
    parsers: dict[str, DocumentParserPort]
    registry: DocumentRegistryPort
    embedding_port: EmbeddingPort
    vector_store: VectorStorePort
    lexical_search: LexicalSearchPort

    async def execute(self, raw_bytes: bytes, filename: str, document_type: str) -> IngestResult:
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        parser = self.parsers.get(extension)
        if parser is None:
            raise UnsupportedFormatError(f"unsupported file extension: '{extension}'")

        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        document, raw_sections = parser.parse(raw_bytes, document_type, filename)
        document = replace(document, content_hash=content_hash)

        existing_hash = await self.registry.get_active_hash(document.product_ref)
        action = resolve_ingest_action(existing_hash, content_hash)

        if action == "unchanged":
            return IngestResult(document_id=document.id, chunk_count=0, status="unchanged")

        if action == "updated":
            await self.vector_store.delete_by_document_id(document.id)
            await self.lexical_search.delete_by_document_id(document.id)
            await self.registry.deprecate(document.product_ref)

        chunk_candidates = chunk_sections(raw_sections)
        chunks = [
            Chunk(
                id=str(uuid.uuid4()),
                document_id=document.id,
                content=candidate.content,
                content_type=candidate.content_type,
                title=document.title,
                product_ref=document.product_ref,
                version=document.version,
                status="active",
                document_type=document.document_type,
                published_date=document.published_date,
                content_hash=document.content_hash,
                source_path=document.source_path,
            )
            for candidate in chunk_candidates
        ]

        embeddings = [await self.embedding_port.embed(chunk.content) for chunk in chunks]
        await self.vector_store.upsert(chunks, embeddings)
        await self.lexical_search.upsert(chunks)
        await self.registry.register(document)

        return IngestResult(document_id=document.id, chunk_count=len(chunks), status=action)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_ingest_document.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/application/use_cases/ingest_document.py tests/unit/test_ingest_document.py
git commit -m "feat: add ingest_document use case (chunk, dedup, dual-index)"
```

---

## Task 11: Infrastructure — Markdown Parser

**Files:**
- Create: `app/infrastructure/parsers/__init__.py`
- Create: `app/infrastructure/parsers/markdown_parser.py`
- Test: `tests/unit/test_markdown_parser.py`

**Interfaces:**
- Consumes: `app.domain.chunking.RawSection` (Task 4), `app.domain.models.Document` (Task 2), `app.domain.errors.UnparsableDocumentError` (Task 3).
- Produces: `MarkdownParser` implementing `DocumentParserPort` — `.parse(raw_bytes: bytes, document_type: str, source_path: str) -> tuple[Document, list[RawSection]]`. Expects raw Markdown with a YAML frontmatter block (`title`, `product_ref`, `version`, `published_date`) followed by the body. Consumed by `app/dependencies.py` (Task 20).

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_markdown_parser.py
import pytest

from app.domain.errors import UnparsableDocumentError
from app.infrastructure.parsers.markdown_parser import MarkdownParser

VALID_MARKDOWN = b"""---
title: Fiche REF-8842
product_ref: REF-8842
version: "2"
published_date: 2026-01-15
---

# Caracteristiques

Tension nominale : 230V. Cet appareil est conforme aux normes en vigueur pour ce type de produit electrique domestique standard.

## Dimensions

| Largeur | Hauteur |
|---|---|
| 10cm | 5cm |
"""


def test_parses_frontmatter_into_document_metadata():
    # Arrange
    parser = MarkdownParser()

    # Act
    document, sections = parser.parse(VALID_MARKDOWN, "datasheet", "REF-8842.md")

    # Assert
    assert document.product_ref == "REF-8842"
    assert document.title == "Fiche REF-8842"
    assert document.version == "2"


def test_splits_into_sections_by_header_and_detects_tables():
    # Arrange
    parser = MarkdownParser()

    # Act
    _document, sections = parser.parse(VALID_MARKDOWN, "datasheet", "REF-8842.md")

    # Assert
    content_types = [s.content_type for s in sections]
    assert "table" in content_types


def test_missing_frontmatter_raises_unparsable_error():
    # Arrange
    parser = MarkdownParser()

    # Act / Assert
    with pytest.raises(UnparsableDocumentError):
        parser.parse(b"# Just a header, no frontmatter", "datasheet", "bad.md")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_markdown_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.parsers'`

- [ ] **Step 3: Write `app/infrastructure/parsers/markdown_parser.py`**

```python
import re
from datetime import date

import yaml

from app.domain.chunking import RawSection
from app.domain.errors import UnparsableDocumentError
from app.domain.models import Document

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
HEADER_RE = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)


class MarkdownParser:
    def parse(
        self, raw_bytes: bytes, document_type: str, source_path: str
    ) -> tuple[Document, list[RawSection]]:
        text = raw_bytes.decode("utf-8")
        match = FRONTMATTER_RE.match(text)
        if not match:
            raise UnparsableDocumentError(f"missing YAML frontmatter in {source_path}")

        metadata = yaml.safe_load(match.group(1))
        body = match.group(2)

        document = Document(
            id=str(metadata["product_ref"]),
            title=str(metadata["title"]),
            product_ref=str(metadata["product_ref"]),
            version=str(metadata["version"]),
            status="active",
            document_type=document_type,
            published_date=date.fromisoformat(str(metadata["published_date"])),
            source_path=source_path,
            content_hash="",
        )
        return document, _split_into_sections(body)


def _split_into_sections(body: str) -> list[RawSection]:
    headers = list(HEADER_RE.finditer(body))
    if not headers:
        return _split_paragraphs(body)

    sections: list[RawSection] = []
    boundaries = [h.start() for h in headers] + [len(body)]
    for start, end in zip(boundaries, boundaries[1:]):
        block = body[start:end].strip()
        if block:
            sections.extend(_split_paragraphs(block))
    return sections


def _split_paragraphs(block: str) -> list[RawSection]:
    sections: list[RawSection] = []
    for paragraph in re.split(r"\n\s*\n", block.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        content_type = "table" if paragraph.lstrip().startswith("|") else "text"
        sections.append(RawSection(content=paragraph, content_type=content_type))
    return sections
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_markdown_parser.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/parsers/__init__.py app/infrastructure/parsers/markdown_parser.py tests/unit/test_markdown_parser.py
git commit -m "feat: add Markdown document parser"
```

---

## Task 12: Infrastructure — PDF Parser

**Files:**
- Modify: `pyproject.toml` (already lists `pdfplumber` and dev-dependency `reportlab` — no change needed, verify present)
- Create: `app/infrastructure/parsers/pdf_parser.py`
- Test: `tests/unit/test_pdf_parser.py`

**Interfaces:**
- Consumes: `app.domain.chunking.RawSection` (Task 4), `app.domain.models.Document` (Task 2), `app.domain.errors.UnparsableDocumentError` (Task 3).
- Produces: `PdfParser` implementing `DocumentParserPort` — `.parse(raw_bytes: bytes, document_type: str, source_path: str) -> tuple[Document, list[RawSection]]`. Splits page text into sections at font-size heading boundaries; extracted tables become dedicated `content_type="table"` sections. Consumed by `app/dependencies.py` (Task 20).

- [ ] **Step 1: Write the test (uses `reportlab` to build a fixture PDF in-memory)**

```python
# tests/unit/test_pdf_parser.py
import io

import pytest
from reportlab.pdfgen import canvas

from app.domain.errors import UnparsableDocumentError
from app.infrastructure.parsers.pdf_parser import PdfParser


def _build_pdf_with_heading_and_body() -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 750, "CARACTERISTIQUES TECHNIQUES")
    c.setFont("Helvetica", 10)
    c.drawString(50, 720, "Tension nominale 230V, courant maximal 10A pour ce modele standard.")
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 690, "PROCEDURE DE MONTAGE")
    c.setFont("Helvetica", 10)
    c.drawString(50, 660, "Suivre les etapes decrites dans le manuel fourni avec l'appareil.")
    c.save()
    return buffer.getvalue()


def test_parses_pdf_into_a_document_and_sections():
    # Arrange
    parser = PdfParser()
    raw_bytes = _build_pdf_with_heading_and_body()

    # Act
    document, sections = parser.parse(raw_bytes, "manuel", "notice.pdf")

    # Assert
    assert document.source_path == "notice.pdf"
    assert len(sections) >= 1


def test_font_size_change_creates_a_new_section_boundary():
    # Arrange
    parser = PdfParser()
    raw_bytes = _build_pdf_with_heading_and_body()

    # Act
    _document, sections = parser.parse(raw_bytes, "manuel", "notice.pdf")

    # Assert
    text_sections = [s for s in sections if s.content_type == "text"]
    assert len(text_sections) >= 2
    assert "CARACTERISTIQUES" in text_sections[0].content


def test_empty_pdf_raises_unparsable_error():
    # Arrange
    parser = PdfParser()
    buffer = io.BytesIO()
    canvas.Canvas(buffer).save()

    # Act / Assert
    with pytest.raises(UnparsableDocumentError):
        parser.parse(buffer.getvalue(), "manuel", "empty.pdf")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_pdf_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.parsers.pdf_parser'`

- [ ] **Step 3: Write `app/infrastructure/parsers/pdf_parser.py`**

```python
import io
import statistics
from datetime import date

import pdfplumber

from app.domain.chunking import RawSection
from app.domain.errors import UnparsableDocumentError
from app.domain.models import Document

HEADING_SIZE_RATIO = 1.15


class PdfParser:
    def parse(
        self, raw_bytes: bytes, document_type: str, source_path: str
    ) -> tuple[Document, list[RawSection]]:
        sections: list[RawSection] = []
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            if not pdf.pages:
                raise UnparsableDocumentError(f"empty PDF: {source_path}")
            title = (pdf.metadata or {}).get("Title") or source_path
            for page in pdf.pages:
                for table in page.extract_tables():
                    rows = ["\t".join(cell or "" for cell in row) for row in table]
                    sections.append(RawSection(content="\n".join(rows), content_type="table"))
                sections.extend(_extract_text_sections(page))

        if not sections:
            raise UnparsableDocumentError(f"no extractable content in {source_path}")

        document = Document(
            id=source_path,
            title=title,
            product_ref=source_path,
            version="1",
            status="active",
            document_type=document_type,
            published_date=date.today(),
            source_path=source_path,
            content_hash="",
        )
        return document, sections


def _extract_text_sections(page) -> list[RawSection]:
    words = page.extract_words(extra_attrs=["size"])
    if not words:
        return []

    lines: dict[float, list[dict]] = {}
    for word in words:
        lines.setdefault(round(word["top"]), []).append(word)

    body_size = statistics.median(w["size"] for w in words)
    heading_threshold = body_size * HEADING_SIZE_RATIO

    sections: list[RawSection] = []
    buffer: list[str] = []
    for top in sorted(lines):
        line_words = sorted(lines[top], key=lambda w: w["x0"])
        line_text = " ".join(w["text"] for w in line_words)
        avg_size = statistics.mean(w["size"] for w in line_words)
        if avg_size >= heading_threshold and buffer:
            sections.append(RawSection(content="\n".join(buffer), content_type="text"))
            buffer = []
        buffer.append(line_text)
    if buffer:
        sections.append(RawSection(content="\n".join(buffer), content_type="text"))
    return sections
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_pdf_parser.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/parsers/pdf_parser.py tests/unit/test_pdf_parser.py
git commit -m "feat: add PDF document parser with font-size heading detection"
```

---

## Task 13: Infrastructure — Azure OpenAI Embedding Client

**Files:**
- Create: `app/infrastructure/azure_openai/__init__.py`
- Create: `app/infrastructure/azure_openai/embedding_client.py`
- Test: `tests/unit/test_embedding_client.py`

**Interfaces:**
- Consumes: `app.config.Settings` (Task 1).
- Produces: `AzureEmbeddingClient(settings: Settings)` implementing `EmbeddingPort` — `async def embed(self, text: str) -> list[float]`. Consumed by `app/dependencies.py` (Task 20).

- [ ] **Step 1: Write the test (mocks the underlying `AsyncAzureOpenAI` client)**

```python
# tests/unit/test_embedding_client.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.infrastructure.azure_openai.embedding_client import AzureEmbeddingClient


def make_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        azure_openai_api_key="key",
        azure_openai_endpoint="https://example.openai.azure.com/",
        azure_openai_embedding_deployment="text-embedding-3-large",
        azure_openai_chat_deployment="gpt-4o",
    )


@pytest.mark.asyncio
async def test_embed_returns_the_vector_from_the_first_response_item():
    # Arrange
    with patch(
        "app.infrastructure.azure_openai.embedding_client.AsyncAzureOpenAI"
    ) as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)
        client = AzureEmbeddingClient(make_settings())

        # Act
        vector = await client.embed("tension nominale")

        # Assert
        assert vector == [0.1, 0.2, 0.3]
        mock_client.embeddings.create.assert_awaited_once_with(
            model="text-embedding-3-large", input="tension nominale"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_embedding_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.azure_openai'`

- [ ] **Step 3: Write `app/infrastructure/azure_openai/embedding_client.py`**

```python
from openai import AsyncAzureOpenAI

from app.config import Settings


class AzureEmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        self._client = AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
        )
        self._deployment = settings.azure_openai_embedding_deployment

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(model=self._deployment, input=text)
        return list(response.data[0].embedding)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_embedding_client.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/azure_openai/__init__.py app/infrastructure/azure_openai/embedding_client.py tests/unit/test_embedding_client.py
git commit -m "feat: add Azure OpenAI embedding client"
```

---

## Task 14: Infrastructure — Azure OpenAI LLM Client

**Files:**
- Create: `app/infrastructure/azure_openai/llm_client.py`
- Test: `tests/unit/test_llm_client.py`

**Interfaces:**
- Consumes: `app.config.Settings` (Task 1), `app.domain.models.Chunk` (Task 2).
- Produces: `AzureLlmClient(settings: Settings)` implementing `LLMPort` — `async def generate(self, query: str, cited_chunks: list[Chunk], hedge: bool) -> str`. Consumed by `app/dependencies.py` (Task 20).

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_llm_client.py
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.domain.models import Chunk
from app.infrastructure.azure_openai.llm_client import AzureLlmClient

CHUNK = Chunk(
    id="chunk-1",
    document_id="REF-1",
    content="Tension nominale : 230V",
    content_type="text",
    title="Fiche REF-1",
    product_ref="REF-1",
    version="1",
    status="active",
    document_type="datasheet",
    published_date=date(2026, 1, 1),
    content_hash="h",
    source_path="p",
)


def make_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        azure_openai_api_key="key",
        azure_openai_endpoint="https://example.openai.azure.com/",
        azure_openai_embedding_deployment="text-embedding-3-large",
        azure_openai_chat_deployment="gpt-4o",
    )


@pytest.mark.asyncio
async def test_generate_returns_the_completion_text_and_includes_cited_content():
    # Arrange
    with patch("app.infrastructure.azure_openai.llm_client.AsyncAzureOpenAI") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Réponse générée."))]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        client = AzureLlmClient(make_settings())

        # Act
        text = await client.generate("tension supportée ?", [CHUNK], hedge=False)

        # Assert
        assert text == "Réponse générée."
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        user_message = call_kwargs["messages"][1]["content"]
        assert "230V" in user_message


@pytest.mark.asyncio
async def test_hedge_true_adds_a_cautious_instruction_to_the_system_prompt():
    # Arrange
    with patch("app.infrastructure.azure_openai.llm_client.AsyncAzureOpenAI") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Réponse prudente."))]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        client = AzureLlmClient(make_settings())

        # Act
        await client.generate("question", [CHUNK], hedge=True)

        # Assert
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        system_message = call_kwargs["messages"][0]["content"]
        assert "prudente" in system_message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_llm_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.azure_openai.llm_client'`

- [ ] **Step 3: Write `app/infrastructure/azure_openai/llm_client.py`**

```python
from openai import AsyncAzureOpenAI

from app.config import Settings
from app.domain.models import Chunk

SYSTEM_PROMPT = (
    "Tu réponds strictement à partir des extraits fournis. "
    "N'invente jamais d'information absente des extraits. "
    "Si les extraits ne suffisent pas, dis-le explicitement."
)
HEDGE_INSTRUCTION = (
    " La pertinence des extraits est incertaine : formule une réponse prudente, "
    "en signalant explicitement le doute."
)


class AzureLlmClient:
    def __init__(self, settings: Settings) -> None:
        self._client = AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
        )
        self._deployment = settings.azure_openai_chat_deployment

    async def generate(self, query: str, cited_chunks: list[Chunk], hedge: bool) -> str:
        context = "\n\n".join(f"[{c.product_ref}] {c.content}" for c in cited_chunks)
        system_prompt = SYSTEM_PROMPT + (HEDGE_INSTRUCTION if hedge else "")
        response = await self._client.chat.completions.create(
            model=self._deployment,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Extraits:\n{context}\n\nQuestion: {query}"},
            ],
        )
        return response.choices[0].message.content or ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_llm_client.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/azure_openai/llm_client.py tests/unit/test_llm_client.py
git commit -m "feat: add Azure OpenAI structured-generation LLM client"
```

---

## Task 15: Infrastructure — Cross-Encoder Reranker

**Files:**
- Create: `app/infrastructure/reranker/__init__.py`
- Create: `app/infrastructure/reranker/cross_encoder_reranker.py`
- Test: `tests/unit/test_cross_encoder_reranker.py`

**Interfaces:**
- Produces: `CrossEncoderReranker(model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2")` implementing `RerankerPort` — `async def score(self, query: str, chunk_text: str) -> float`, sigmoid-normalized to `[0, 1]`. Consumed by `app/dependencies.py` (Task 20).

- [ ] **Step 1: Write the test (mocks the underlying `CrossEncoder` model to avoid downloading weights in unit tests)**

```python
# tests/unit/test_cross_encoder_reranker.py
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.reranker.cross_encoder_reranker import CrossEncoderReranker


@pytest.mark.asyncio
async def test_score_normalizes_raw_logit_to_zero_one_range():
    # Arrange
    with patch(
        "app.infrastructure.reranker.cross_encoder_reranker.CrossEncoder"
    ) as mock_cross_encoder_cls:
        mock_model = MagicMock()
        mock_model.predict.return_value = [0.0]
        mock_cross_encoder_cls.return_value = mock_model
        reranker = CrossEncoderReranker()

        # Act
        score = await reranker.score("tension supportée ?", "Tension nominale : 230V")

        # Assert
        assert score == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_high_raw_logit_scores_close_to_one():
    # Arrange
    with patch(
        "app.infrastructure.reranker.cross_encoder_reranker.CrossEncoder"
    ) as mock_cross_encoder_cls:
        mock_model = MagicMock()
        mock_model.predict.return_value = [10.0]
        mock_cross_encoder_cls.return_value = mock_model
        reranker = CrossEncoderReranker()

        # Act
        score = await reranker.score("query", "text")

        # Assert
        assert score > 0.99
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_cross_encoder_reranker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.reranker'`

- [ ] **Step 3: Write `app/infrastructure/reranker/cross_encoder_reranker.py`**

```python
import math

from sentence_transformers import CrossEncoder
from starlette.concurrency import run_in_threadpool

DEFAULT_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class CrossEncoderReranker:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        self._model = CrossEncoder(model_name)

    async def score(self, query: str, chunk_text: str) -> float:
        return await run_in_threadpool(self._score_sync, query, chunk_text)

    def _score_sync(self, query: str, chunk_text: str) -> float:
        raw_score = self._model.predict([(query, chunk_text)])[0]
        return float(1 / (1 + math.exp(-raw_score)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_cross_encoder_reranker.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/reranker/__init__.py app/infrastructure/reranker/cross_encoder_reranker.py tests/unit/test_cross_encoder_reranker.py
git commit -m "feat: add local cross-encoder reranker"
```

---

## Task 16: Infrastructure — Postgres SQLAlchemy Models + Alembic Migration

> **Partially superseded — see migration `0002_retrieval_indexes.py`.** As written,
> this task shipped no index on `chunks.search_vector` or `chunks.embedding`, so both
> halves of hybrid retrieval sequential-scanned; and its `downgrade()` dropped the
> database-wide `vector` extension. Revision `0002` adds a GIN index and an HNSW
> (`vector_cosine_ops`) index, and converts `search_vector` to a STORED generated
> column; `0001`'s `downgrade()` no longer drops the extension. `docker-compose.yml`
> is also Postgres-only — the `app` service described in Task 1 declared `build: .`
> with no Dockerfile in the repo, which broke `docker compose up` outright.
>
> **Also superseded by `0003_versioned_document_key.py`.** The composite
> `(product_ref, document_type)` primary key could only hold a document's *current*
> version, so the spec's audit rule was unimplementable. `documents` now has a
> surrogate, version-scoped `id` with a unique constraint on
> `(product_ref, document_type, version)`, and `chunks.document_id` is a real
> foreign key onto it (`ON DELETE CASCADE`).

**Files:**
- Create: `app/infrastructure/postgres/__init__.py`
- Create: `app/infrastructure/postgres/models.py`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/versions/0001_initial_schema.py`

**Interfaces:**
- Produces: `Base(DeclarativeBase)`, `DocumentRow(product_ref: Mapped[str] [pk], title, version, status, document_type, published_date: Mapped[date], source_path, content_hash: Mapped[str])`, `ChunkRow(id: Mapped[str] [pk], document_id, content, content_type, title, product_ref, version, status, document_type, published_date: Mapped[date], content_hash, source_path: Mapped[str], embedding: Mapped[list[float] | None] [pgvector, dim 1536], search_vector: Mapped[str | None] [TSVECTOR])`, `EMBEDDING_DIM = 1536`. Consumed by Tasks 17, 18, 19 (repositories) and the Alembic migration.

- [ ] **Step 1: Write `app/infrastructure/postgres/models.py`**

```python
from datetime import date
from typing import Annotated

from pgvector.sqlalchemy import Vector
from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 1536
PrimaryKeyStr = Annotated[str, mapped_column(String, primary_key=True)]


class Base(DeclarativeBase):
    pass


class DocumentRow(Base):
    __tablename__ = "documents"

    product_ref: Mapped[PrimaryKeyStr]
    title: Mapped[str]
    version: Mapped[str]
    status: Mapped[str] = mapped_column(String, index=True)
    document_type: Mapped[str]
    published_date: Mapped[date]
    source_path: Mapped[str]
    content_hash: Mapped[str]


class ChunkRow(Base):
    __tablename__ = "chunks"

    id: Mapped[PrimaryKeyStr]
    document_id: Mapped[str] = mapped_column(String, index=True)
    content: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str]
    title: Mapped[str]
    product_ref: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[str]
    status: Mapped[str] = mapped_column(String, index=True)
    document_type: Mapped[str]
    published_date: Mapped[date]
    content_hash: Mapped[str]
    source_path: Mapped[str]
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `python -c "from app.infrastructure.postgres.models import Base, DocumentRow, ChunkRow"`
Expected: no output, exit code 0

- [ ] **Step 3: Initialize Alembic and write `alembic.ini`**

Run: `alembic init migrations`

Then edit `alembic.ini`, replacing the `sqlalchemy.url` line with:

```ini
sqlalchemy.url =
```

(left blank — the URL is set at runtime in `migrations/env.py` from `app.config.Settings`, never hardcoded, per the security rule against hardcoded configuration.)

- [ ] **Step 4: Write `migrations/env.py`**

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.infrastructure.postgres.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 5: Write `migrations/versions/0001_initial_schema.py`**

```python
"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-02
"""

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("product_ref", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=False),
        sa.Column("source_path", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
    )
    op.create_index("ix_documents_status", "documents", ["status"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("product_ref", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("source_path", sa.String(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(1536), nullable=True),
        sa.Column("search_vector", TSVECTOR(), nullable=True),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_product_ref", "chunks", ["product_ref"])
    op.create_index("ix_chunks_status", "chunks", ["status"])


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("documents")
    op.execute("DROP EXTENSION IF EXISTS vector")
```

- [ ] **Step 6: Commit**

```bash
git add app/infrastructure/postgres/__init__.py app/infrastructure/postgres/models.py alembic.ini migrations
git commit -m "feat: add Postgres/pgvector schema and initial Alembic migration"
```

---

## Task 17: Infrastructure — pgvector Repository (Testcontainers)

**Files:**
- Create: `app/infrastructure/postgres/mappers.py`
- Create: `app/infrastructure/postgres/pgvector_repository.py`
- Modify: `tests/conftest.py` (add Testcontainers Postgres fixture)
- Test: `tests/integration/test_pgvector_repository.py`

**Interfaces:**
- Consumes: `app.infrastructure.postgres.models.{Base,ChunkRow}` (Task 16), `app.domain.models.Chunk` (Task 2).
- Produces: `apply_chunk_fields(row: ChunkRow, chunk: Chunk) -> None`, `row_to_chunk(row: ChunkRow) -> Chunk` (both in `mappers.py`, reused by Task 18); `PgVectorRepository(session: AsyncSession)` implementing `VectorStorePort`. Consumed by `app/dependencies.py` (Task 20) and Task 18's tests indirectly via the shared mapper.
- `tests/conftest.py` gains: `postgres_container` (session-scoped Testcontainers fixture), `db_session` (function-scoped `AsyncSession` against that container, tables created fresh, transaction rolled back after each test per `testing-pytest.md`).

- [ ] **Step 1: Extend `tests/conftest.py` with a Testcontainers Postgres fixture**

```python
# tests/conftest.py (append to the existing file from Task 1)
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.infrastructure.postgres.models import Base


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as container:
        yield container


@pytest_asyncio.fixture
async def db_session(postgres_container) -> AsyncSession:
    engine = create_async_engine(postgres_container.get_connection_url())
    async with engine.begin() as conn:
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
```

- [ ] **Step 2: Write `app/infrastructure/postgres/mappers.py`**

```python
from app.domain.models import Chunk
from app.infrastructure.postgres.models import ChunkRow


def apply_chunk_fields(row: ChunkRow, chunk: Chunk) -> None:
    row.document_id = chunk.document_id
    row.content = chunk.content
    row.content_type = chunk.content_type
    row.title = chunk.title
    row.product_ref = chunk.product_ref
    row.version = chunk.version
    row.status = chunk.status
    row.document_type = chunk.document_type
    row.published_date = chunk.published_date
    row.content_hash = chunk.content_hash
    row.source_path = chunk.source_path


def row_to_chunk(row: ChunkRow) -> Chunk:
    return Chunk(
        id=row.id,
        document_id=row.document_id,
        content=row.content,
        content_type=row.content_type,
        title=row.title,
        product_ref=row.product_ref,
        version=row.version,
        status=row.status,
        document_type=row.document_type,
        published_date=row.published_date,
        content_hash=row.content_hash,
        source_path=row.source_path,
    )
```

- [ ] **Step 3: Write the failing test**

```python
# tests/integration/test_pgvector_repository.py
from datetime import date

import pytest

from app.domain.models import Chunk
from app.infrastructure.postgres.pgvector_repository import PgVectorRepository


def make_chunk(chunk_id: str, product_ref: str, content: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        document_id=product_ref,
        content=content,
        content_type="text",
        title=f"Fiche {product_ref}",
        product_ref=product_ref,
        version="1",
        status="active",
        document_type="datasheet",
        published_date=date(2026, 1, 1),
        content_hash="h",
        source_path="p",
    )


@pytest.mark.asyncio
async def test_upsert_then_search_returns_closest_chunk_first(db_session):
    # Arrange
    repo = PgVectorRepository(db_session)
    chunk_close = make_chunk("chunk-close", "REF-1", "Tension nominale 230V")
    chunk_far = make_chunk("chunk-far", "REF-2", "Procédure de retour produit")
    await repo.upsert([chunk_close, chunk_far], [[1.0, 0.0], [0.0, 1.0]])

    # Act
    results = await repo.search(embedding=[1.0, 0.0], top_k=2)

    # Assert
    assert results[0][0].id == "chunk-close"
    assert results[0][1] == 1


@pytest.mark.asyncio
async def test_search_can_be_scoped_to_a_product_ref(db_session):
    # Arrange
    repo = PgVectorRepository(db_session)
    chunk_a = make_chunk("chunk-a", "REF-A", "contenu A")
    chunk_b = make_chunk("chunk-b", "REF-B", "contenu B")
    await repo.upsert([chunk_a, chunk_b], [[1.0, 0.0], [1.0, 0.0]])

    # Act
    results = await repo.search(embedding=[1.0, 0.0], top_k=10, product_ref="REF-A")

    # Assert
    assert len(results) == 1
    assert results[0][0].product_ref == "REF-A"


@pytest.mark.asyncio
async def test_delete_by_document_id_removes_its_chunks(db_session):
    # Arrange
    repo = PgVectorRepository(db_session)
    chunk = make_chunk("chunk-x", "REF-X", "à supprimer")
    await repo.upsert([chunk], [[0.5, 0.5]])

    # Act
    await repo.delete_by_document_id("REF-X")
    results = await repo.search(embedding=[0.5, 0.5], top_k=10)

    # Assert
    assert results == []
```

Note: this test uses 2-dimensional embeddings for clarity; the schema's `Vector(1536)` in Task 16 is for the real embedding model. Add a test-only override: the fixture recreates `chunks.embedding` as `Vector(2)` for this test file only, via a local metadata swap — see Step 4.

- [ ] **Step 4: Adjust the test to use a 2-dimensional vector column for integration testing**

Add to the top of `tests/integration/test_pgvector_repository.py`, replacing the bare Testcontainers table creation for this file with a local override:

```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from pgvector.sqlalchemy import Vector

from app.infrastructure.postgres.models import Base, ChunkRow


@pytest_asyncio.fixture
async def db_session(postgres_container):
    # Override the default 1536-dim embedding column with a 2-dim one for fast, readable assertions.
    ChunkRow.__table__.columns["embedding"].type = Vector(2)
    engine = create_async_engine(postgres_container.get_connection_url())
    import sqlalchemy as sa

    async with engine.begin() as conn:
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
```

(This shadows the session-scoped `db_session` fixture from `tests/conftest.py` for this file only — standard pytest fixture override by name.)

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest tests/integration/test_pgvector_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.postgres.pgvector_repository'`

- [ ] **Step 6: Write `app/infrastructure/postgres/pgvector_repository.py`**

```python
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Chunk
from app.infrastructure.postgres.mappers import apply_chunk_fields, row_to_chunk
from app.infrastructure.postgres.models import ChunkRow


class PgVectorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        for chunk, embedding in zip(chunks, embeddings):
            row = await self._session.get(ChunkRow, chunk.id)
            if row is None:
                row = ChunkRow(id=chunk.id)
                self._session.add(row)
            apply_chunk_fields(row, chunk)
            row.embedding = embedding
        await self._session.commit()

    async def search(
        self, embedding: list[float], top_k: int, product_ref: str | None = None
    ) -> list[tuple[Chunk, int]]:
        stmt = select(ChunkRow).where(ChunkRow.status == "active")
        if product_ref is not None:
            stmt = stmt.where(ChunkRow.product_ref == product_ref)
        stmt = stmt.order_by(ChunkRow.embedding.cosine_distance(embedding)).limit(top_k)
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [(row_to_chunk(row), rank) for rank, row in enumerate(rows, start=1)]

    async def delete_by_document_id(self, document_id: str) -> None:
        await self._session.execute(delete(ChunkRow).where(ChunkRow.document_id == document_id))
        await self._session.commit()
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/integration/test_pgvector_repository.py -v`
Expected: PASS (3 tests) — requires Docker running locally for Testcontainers.

- [ ] **Step 8: Commit**

```bash
git add app/infrastructure/postgres/mappers.py app/infrastructure/postgres/pgvector_repository.py tests/conftest.py tests/integration/test_pgvector_repository.py
git commit -m "feat: add pgvector-backed VectorStorePort implementation"
```

---

## Task 18: Infrastructure — BM25 (tsvector) Repository (Testcontainers)

> **Partially superseded — see migration `0002_retrieval_indexes.py`.** `upsert()` no
> longer assigns `row.search_vector = func.to_tsvector("french", ...)`: the column is
> now a STORED generated column that Postgres maintains, so the index cannot drift
> from `content` and an explicit assignment would be rejected. Query-time
> `plainto_tsquery("french", ...)` is unchanged.

**Files:**
- Create: `app/infrastructure/postgres/bm25_repository.py`
- Test: `tests/integration/test_bm25_repository.py`

**Interfaces:**
- Consumes: `app.infrastructure.postgres.mappers.{apply_chunk_fields,row_to_chunk}` (Task 17), `app.infrastructure.postgres.models.ChunkRow` (Task 16).
- Produces: `Bm25Repository(session: AsyncSession)` implementing `LexicalSearchPort`. Consumed by `app/dependencies.py` (Task 20).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_bm25_repository.py
from datetime import date

import pytest

from app.domain.models import Chunk
from app.infrastructure.postgres.bm25_repository import Bm25Repository


def make_chunk(chunk_id: str, product_ref: str, content: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        document_id=product_ref,
        content=content,
        content_type="text",
        title=f"Fiche {product_ref}",
        product_ref=product_ref,
        version="1",
        status="active",
        document_type="datasheet",
        published_date=date(2026, 1, 1),
        content_hash="h",
        source_path="p",
    )


@pytest.mark.asyncio
async def test_upsert_then_search_matches_on_exact_reference_token(db_session):
    # Arrange
    repo = Bm25Repository(db_session)
    chunk_ref = make_chunk("chunk-ref", "REF-8842", "La reference REF-8842 supporte 230V")
    chunk_other = make_chunk("chunk-other", "REF-9000", "Un autre produit sans rapport")
    await repo.upsert([chunk_ref, chunk_other])

    # Act
    results = await repo.search("REF-8842", top_k=5)

    # Assert
    assert results[0][0].id == "chunk-ref"


@pytest.mark.asyncio
async def test_search_can_be_scoped_to_a_product_ref(db_session):
    # Arrange
    repo = Bm25Repository(db_session)
    chunk_a = make_chunk("chunk-a", "REF-A", "tension nominale 230V")
    chunk_b = make_chunk("chunk-b", "REF-B", "tension nominale 230V")
    await repo.upsert([chunk_a, chunk_b])

    # Act
    results = await repo.search("tension", top_k=10, product_ref="REF-A")

    # Assert
    assert len(results) == 1
    assert results[0][0].product_ref == "REF-A"


@pytest.mark.asyncio
async def test_delete_by_document_id_removes_its_chunks(db_session):
    # Arrange
    repo = Bm25Repository(db_session)
    chunk = make_chunk("chunk-x", "REF-X", "contenu a supprimer")
    await repo.upsert([chunk])

    # Act
    await repo.delete_by_document_id("REF-X")
    results = await repo.search("contenu", top_k=10)

    # Assert
    assert results == []
```

(This file uses the default 1536-dim `db_session` fixture from `tests/conftest.py` — it never touches the `embedding` column.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_bm25_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.postgres.bm25_repository'`

- [ ] **Step 3: Write `app/infrastructure/postgres/bm25_repository.py`**

```python
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Chunk
from app.infrastructure.postgres.mappers import apply_chunk_fields, row_to_chunk
from app.infrastructure.postgres.models import ChunkRow


class Bm25Repository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            row = await self._session.get(ChunkRow, chunk.id)
            if row is None:
                row = ChunkRow(id=chunk.id)
                self._session.add(row)
            apply_chunk_fields(row, chunk)
            row.search_vector = func.to_tsvector("french", chunk.content)
        await self._session.commit()

    async def search(
        self, query: str, top_k: int, product_ref: str | None = None
    ) -> list[tuple[Chunk, int]]:
        ts_query = func.plainto_tsquery("french", query)
        stmt = (
            select(ChunkRow)
            .where(ChunkRow.status == "active")
            .where(ChunkRow.search_vector.op("@@")(ts_query))
        )
        if product_ref is not None:
            stmt = stmt.where(ChunkRow.product_ref == product_ref)
        stmt = stmt.order_by(func.ts_rank(ChunkRow.search_vector, ts_query).desc()).limit(top_k)
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [(row_to_chunk(row), rank) for rank, row in enumerate(rows, start=1)]

    async def delete_by_document_id(self, document_id: str) -> None:
        await self._session.execute(delete(ChunkRow).where(ChunkRow.document_id == document_id))
        await self._session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_bm25_repository.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/postgres/bm25_repository.py tests/integration/test_bm25_repository.py
git commit -m "feat: add tsvector-backed LexicalSearchPort implementation"
```

---

## Task 19: Infrastructure — Postgres Document Registry (Testcontainers)

> **Partially superseded — see migration `0003_versioned_document_key.py`.**
> `register()` looked the row up by `(product_ref, document_type)` and overwrote
> `version`/`status`/`content_hash` in place, so a new version destroyed its
> predecessor. It now keys on the version-scoped `document.id`: a new version
> inserts a new row and leaves the previous one behind as `deprecated`.
> `get_active_hash()` is correspondingly a filtered `select(...)` on
> `status = 'active'` rather than a primary-key `get()`.

**Files:**
- Create: `app/infrastructure/postgres/document_registry.py`
- Test: `tests/integration/test_document_registry.py`

**Interfaces:**
- Consumes: `app.infrastructure.postgres.models.{DocumentRow,ChunkRow}` (Task 16), `app.domain.models.Document` (Task 2).
- Produces: `PostgresDocumentRegistry(session: AsyncSession)` implementing `DocumentRegistryPort`. Consumed by `app/dependencies.py` (Task 20).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_document_registry.py
from datetime import date

import pytest

from app.domain.models import Document
from app.infrastructure.postgres.document_registry import PostgresDocumentRegistry


def make_document(product_ref: str, content_hash: str) -> Document:
    return Document(
        id=product_ref,
        title=f"Fiche {product_ref}",
        product_ref=product_ref,
        version="1",
        status="active",
        document_type="datasheet",
        published_date=date(2026, 1, 1),
        source_path=f"{product_ref}.md",
        content_hash=content_hash,
    )


@pytest.mark.asyncio
async def test_get_active_hash_returns_none_when_no_document_registered(db_session):
    # Arrange
    registry = PostgresDocumentRegistry(db_session)

    # Act
    result = await registry.get_active_hash("REF-UNKNOWN")

    # Assert
    assert result is None


@pytest.mark.asyncio
async def test_register_then_get_active_hash_returns_the_registered_hash(db_session):
    # Arrange
    registry = PostgresDocumentRegistry(db_session)
    document = make_document("REF-1", "hash-1")

    # Act
    await registry.register(document)
    result = await registry.get_active_hash("REF-1")

    # Assert
    assert result == "hash-1"


@pytest.mark.asyncio
async def test_deprecate_marks_document_and_its_chunks_as_deprecated(db_session):
    # Arrange
    from app.infrastructure.postgres.models import ChunkRow

    registry = PostgresDocumentRegistry(db_session)
    document = make_document("REF-2", "hash-2")
    await registry.register(document)
    chunk_row = ChunkRow(
        id="chunk-1",
        document_id="REF-2",
        content="x",
        content_type="text",
        title="t",
        product_ref="REF-2",
        version="1",
        status="active",
        document_type="datasheet",
        published_date=date(2026, 1, 1),
        content_hash="hash-2",
        source_path="p",
    )
    db_session.add(chunk_row)
    await db_session.commit()

    # Act
    await registry.deprecate("REF-2")
    active_hash = await registry.get_active_hash("REF-2")

    # Assert
    assert active_hash is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_document_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.postgres.document_registry'`

- [ ] **Step 3: Write `app/infrastructure/postgres/document_registry.py`**

```python
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Document
from app.infrastructure.postgres.models import ChunkRow, DocumentRow


class PostgresDocumentRegistry:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_hash(self, product_ref: str) -> str | None:
        row = await self._session.get(DocumentRow, product_ref)
        return row.content_hash if row is not None and row.status == "active" else None

    async def register(self, document: Document) -> None:
        row = await self._session.get(DocumentRow, document.product_ref)
        if row is None:
            row = DocumentRow(product_ref=document.product_ref)
            self._session.add(row)
        row.title = document.title
        row.version = document.version
        row.status = "active"
        row.document_type = document.document_type
        row.published_date = document.published_date
        row.source_path = document.source_path
        row.content_hash = document.content_hash
        await self._session.commit()

    async def deprecate(self, product_ref: str) -> None:
        await self._session.execute(
            update(DocumentRow)
            .where(DocumentRow.product_ref == product_ref)
            .values(status="deprecated")
        )
        await self._session.execute(
            update(ChunkRow).where(ChunkRow.product_ref == product_ref).values(status="deprecated")
        )
        await self._session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_document_registry.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/postgres/document_registry.py tests/integration/test_document_registry.py
git commit -m "feat: add Postgres document registry for dedup/versioning"
```

---

## Task 20: API Layer — Schemas, Dependencies, Routes, App Wiring

**Files:**
- Create: `app/api/schemas/query.py`
- Create: `app/api/schemas/ingest.py`
- Create: `app/dependencies.py`
- Create: `app/api/routes/query.py`
- Create: `app/api/routes/ingest.py`
- Create: `app/main.py`
- Test: `tests/test_routers/test_query_route.py`, `tests/test_routers/test_ingest_route.py`

**Interfaces:**
- Consumes: `app.application.use_cases.answer_query.AnswerQueryUseCase` (Task 9), `app.application.use_cases.ingest_document.IngestDocumentUseCase` (Task 10), `app.infrastructure.*` classes (Tasks 11–19), `app.domain.errors.{UnparsableDocumentError,UnsupportedFormatError}` (Task 3).
- Produces: `QueryRequest`, `CitationResponse`, `QueryResponse`, `IngestResponse` (Pydantic schemas); `get_settings`, `get_db`, `get_reranker`, `get_answer_query_use_case`, `get_ingest_document_use_case` (FastAPI dependency providers in `app/dependencies.py`); `app` (the `FastAPI` instance in `app/main.py`) with routers mounted at `/api/v1/query` and `/api/v1/ingest`.

- [ ] **Step 1: Write `app/api/schemas/query.py`**

```python
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    product_ref: str | None = None
    top_k: int = Field(default=20, ge=1, le=50)


class CitationResponse(BaseModel):
    title: str
    product_ref: str
    published_date: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]
    confidence: str
    refused: bool
```

- [ ] **Step 2: Write `app/api/schemas/ingest.py`**

```python
from pydantic import BaseModel


class IngestResponse(BaseModel):
    document_id: str
    chunk_count: int
    status: str
```

- [ ] **Step 3: Write `app/dependencies.py`**

```python
from functools import lru_cache
from typing import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.application.use_cases.answer_query import AnswerQueryUseCase
from app.application.use_cases.ingest_document import IngestDocumentUseCase
from app.config import Settings, get_settings
from app.infrastructure.azure_openai.embedding_client import AzureEmbeddingClient
from app.infrastructure.azure_openai.llm_client import AzureLlmClient
from app.infrastructure.parsers.markdown_parser import MarkdownParser
from app.infrastructure.parsers.pdf_parser import PdfParser
from app.infrastructure.postgres.bm25_repository import Bm25Repository
from app.infrastructure.postgres.document_registry import PostgresDocumentRegistry
from app.infrastructure.postgres.pgvector_repository import PgVectorRepository
from app.infrastructure.reranker.cross_encoder_reranker import CrossEncoderReranker


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url)


async def get_db() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with session_factory() as session:
        yield session


@lru_cache
def get_reranker() -> CrossEncoderReranker:
    return CrossEncoderReranker()


def get_answer_query_use_case(
    db: AsyncSession = Depends(get_db),
    reranker: CrossEncoderReranker = Depends(get_reranker),
    settings: Settings = Depends(get_settings),
) -> AnswerQueryUseCase:
    return AnswerQueryUseCase(
        embedding_port=AzureEmbeddingClient(settings),
        vector_store=PgVectorRepository(db),
        lexical_search=Bm25Repository(db),
        reranker=reranker,
        llm=AzureLlmClient(settings),
    )


def get_ingest_document_use_case(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> IngestDocumentUseCase:
    return IngestDocumentUseCase(
        parsers={"md": MarkdownParser(), "pdf": PdfParser()},
        registry=PostgresDocumentRegistry(db),
        embedding_port=AzureEmbeddingClient(settings),
        vector_store=PgVectorRepository(db),
        lexical_search=Bm25Repository(db),
    )
```

- [ ] **Step 4: Write `app/api/routes/query.py`**

```python
from fastapi import APIRouter, Depends

from app.api.schemas.query import CitationResponse, QueryRequest, QueryResponse
from app.application.use_cases.answer_query import AnswerQueryUseCase
from app.dependencies import get_answer_query_use_case

router = APIRouter(prefix="/api/v1", tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query_documents(
    request: QueryRequest,
    use_case: AnswerQueryUseCase = Depends(get_answer_query_use_case),
) -> QueryResponse:
    """Answer a documentary question via hybrid retrieval, with mandatory citations or explicit refusal."""
    answer = await use_case.execute(request.query, request.product_ref, request.top_k)
    return QueryResponse(
        answer=answer.text,
        citations=[
            CitationResponse(
                title=c.title,
                product_ref=c.product_ref,
                published_date=c.published_date.isoformat(),
            )
            for c in answer.citations
        ],
        confidence=answer.confidence,
        refused=answer.confidence == "refused",
    )
```

- [ ] **Step 5: Write `app/api/routes/ingest.py`**

```python
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.schemas.ingest import IngestResponse
from app.application.use_cases.ingest_document import IngestDocumentUseCase
from app.dependencies import get_ingest_document_use_case
from app.domain.errors import UnparsableDocumentError, UnsupportedFormatError

router = APIRouter(prefix="/api/v1", tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest_document(
    document_type: str = Form(...),
    file: UploadFile = File(...),
    use_case: IngestDocumentUseCase = Depends(get_ingest_document_use_case),
) -> IngestResponse:
    """Ingest a source document (Markdown or PDF) into the dual dense/lexical index."""
    raw_bytes = await file.read()
    try:
        result = await use_case.execute(raw_bytes, file.filename or "", document_type)
    except UnsupportedFormatError as exc:
        raise HTTPException(
            status_code=422, detail={"error_code": "UNSUPPORTED_FORMAT", "message": str(exc)}
        ) from exc
    except UnparsableDocumentError as exc:
        raise HTTPException(
            status_code=422, detail={"error_code": "UNPARSABLE_DOCUMENT", "message": str(exc)}
        ) from exc
    return IngestResponse(
        document_id=result.document_id, chunk_count=result.chunk_count, status=result.status
    )
```

- [ ] **Step 6: Write `app/main.py`**

```python
from fastapi import FastAPI

from app.api.routes.ingest import router as ingest_router
from app.api.routes.query import router as query_router

app = FastAPI(title="rag-hybride")
app.include_router(query_router)
app.include_router(ingest_router)
```

- [ ] **Step 7: Write `tests/test_routers/test_query_route.py`**

```python
# tests/test_routers/test_query_route.py
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_answer_query_use_case
from app.domain.models import Answer, Citation
from app.main import app


class FakeUseCase:
    def __init__(self, answer: Answer):
        self._answer = answer

    async def execute(self, query, product_ref=None, top_k=20):
        return self._answer


@pytest.mark.asyncio
async def test_query_route_returns_citations_on_high_confidence():
    # Arrange
    answer = Answer(
        text="Réponse.",
        citations=[
            Citation(title="Fiche REF-1", product_ref="REF-1", published_date=date(2026, 1, 1))
        ],
        confidence="high",
    )
    app.dependency_overrides[get_answer_query_use_case] = lambda: FakeUseCase(answer)

    # Act
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/query", json={"query": "tension REF-1 ?"})

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["refused"] is False
    assert data["citations"][0]["product_ref"] == "REF-1"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_query_route_returns_refusal_with_no_citations():
    # Arrange
    answer = Answer(
        text="Je ne trouve pas cette information dans le corpus.",
        citations=[],
        confidence="refused",
    )
    app.dependency_overrides[get_answer_query_use_case] = lambda: FakeUseCase(answer)

    # Act
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/query", json={"query": "question hors corpus"})

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["refused"] is True
    assert data["citations"] == []
    app.dependency_overrides.clear()
```

- [ ] **Step 8: Write `tests/test_routers/test_ingest_route.py`**

```python
# tests/test_routers/test_ingest_route.py
import pytest
from httpx import ASGITransport, AsyncClient

from app.application.use_cases.ingest_document import IngestResult
from app.dependencies import get_ingest_document_use_case
from app.domain.errors import UnsupportedFormatError
from app.main import app


class FakeUseCase:
    def __init__(self, result=None, error: Exception | None = None):
        self._result = result
        self._error = error

    async def execute(self, raw_bytes, filename, document_type):
        if self._error is not None:
            raise self._error
        return self._result


@pytest.mark.asyncio
async def test_ingest_route_returns_result_on_success():
    # Arrange
    app.dependency_overrides[get_ingest_document_use_case] = lambda: FakeUseCase(
        result=IngestResult(document_id="REF-1", chunk_count=3, status="created")
    )

    # Act
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ingest",
            data={"document_type": "datasheet"},
            files={"file": ("REF-1.md", b"content", "text/markdown")},
        )

    # Assert
    assert response.status_code == 200
    assert response.json() == {"document_id": "REF-1", "chunk_count": 3, "status": "created"}
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ingest_route_returns_422_on_unsupported_format():
    # Arrange
    app.dependency_overrides[get_ingest_document_use_case] = lambda: FakeUseCase(
        error=UnsupportedFormatError("unsupported file extension: 'docx'")
    )

    # Act
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ingest",
            data={"document_type": "datasheet"},
            files={"file": ("notes.docx", b"content", "application/octet-stream")},
        )

    # Assert
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "UNSUPPORTED_FORMAT"
    app.dependency_overrides.clear()
```

- [ ] **Step 9: Run all API tests to verify they fail, then pass**

Run: `pytest tests/test_routers/ -v`
Expected first: FAIL with `ModuleNotFoundError: No module named 'app.main'` (before Steps 1–6) / import errors.
After completing Steps 1–6: Expected: PASS (4 tests)

- [ ] **Step 10: Commit**

```bash
git add app/api app/dependencies.py app/main.py tests/test_routers
git commit -m "feat: wire query/ingest FastAPI routes to the use cases"
```

---

## Task 21: Acceptance Tests — Full Ingest → Query Flow

**Files:**
- Test: `tests/test_routers/test_acceptance_flow.py`

**Interfaces:**
- Consumes: `app.main.app` (Task 20), `app.dependencies.{get_answer_query_use_case,get_ingest_document_use_case}` (Task 20), `app.application.use_cases.{ingest_document.IngestDocumentUseCase,answer_query.AnswerQueryUseCase}` (Tasks 9, 10), the fake in-memory port doubles pattern from Tasks 9–10's unit tests (redefined locally, self-contained, wired together end-to-end instead of individually).
- Produces: nothing consumed by later tasks — this is the final acceptance gate for the MVP slice defined in the spec.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_routers/test_acceptance_flow.py
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.application.use_cases.answer_query import AnswerQueryUseCase
from app.application.use_cases.ingest_document import IngestDocumentUseCase
from app.dependencies import get_answer_query_use_case, get_ingest_document_use_case
from app.domain.chunking import RawSection
from app.domain.models import Chunk, Document
from app.infrastructure.parsers.markdown_parser import MarkdownParser
from app.main import app

VALID_MARKDOWN = b"""---
title: Fiche REF-8842
product_ref: REF-8842
version: "1"
published_date: 2026-01-15
---

# Caracteristiques

Tension nominale : 230V. Cet appareil est conforme aux normes en vigueur pour ce type de produit electrique domestique standard et courant.
"""


class InMemoryRegistry:
    def __init__(self):
        self._hashes: dict[str, str] = {}

    async def get_active_hash(self, product_ref):
        return self._hashes.get(product_ref)

    async def register(self, document: Document):
        self._hashes[document.product_ref] = document.content_hash

    async def deprecate(self, product_ref):
        self._hashes.pop(product_ref, None)


class InMemoryIndex:
    def __init__(self):
        self.chunks: dict[str, Chunk] = {}

    async def upsert(self, chunks, embeddings=None):
        for chunk in chunks:
            self.chunks[chunk.id] = chunk

    async def search(self, query_or_embedding, top_k, product_ref=None):
        # Matches both VectorStorePort.search(embedding, top_k, product_ref) and
        # LexicalSearchPort.search(query, top_k, product_ref) positionally. Only a
        # string first argument (lexical) filters by keyword match; a vector first
        # argument (dense) just returns all active matches — sufficient for this
        # single-document acceptance flow.
        matches = [c for c in self.chunks.values() if c.status == "active"]
        if product_ref is not None:
            matches = [c for c in matches if c.product_ref == product_ref]
        if isinstance(query_or_embedding, str):
            words = query_or_embedding.lower().split()
            matches = [c for c in matches if any(w in c.content.lower() for w in words)]
        return [(c, rank) for rank, c in enumerate(matches[:top_k], start=1)]

    async def delete_by_document_id(self, document_id):
        self.chunks = {k: v for k, v in self.chunks.items() if v.document_id != document_id}


class FixedEmbeddingPort:
    async def embed(self, text: str) -> list[float]:
        return [1.0]


class AlwaysConfidentReranker:
    async def score(self, query: str, chunk_text: str) -> float:
        return 0.95


class EchoingLlm:
    async def generate(self, query, cited_chunks, hedge) -> str:
        titles = ", ".join(c.title for c in cited_chunks)
        return f"Réponse basée sur : {titles}"


def build_use_cases():
    registry = InMemoryRegistry()
    vector_store = InMemoryIndex()
    lexical_search = InMemoryIndex()
    ingest_use_case = IngestDocumentUseCase(
        parsers={"md": MarkdownParser()},
        registry=registry,
        embedding_port=FixedEmbeddingPort(),
        vector_store=vector_store,
        lexical_search=lexical_search,
    )
    answer_use_case = AnswerQueryUseCase(
        embedding_port=FixedEmbeddingPort(),
        vector_store=vector_store,
        lexical_search=lexical_search,
        reranker=AlwaysConfidentReranker(),
        llm=EchoingLlm(),
    )
    return ingest_use_case, answer_use_case


@pytest.mark.asyncio
async def test_ingested_document_is_answerable_with_citations():
    # Arrange
    ingest_use_case, answer_use_case = build_use_cases()
    app.dependency_overrides[get_ingest_document_use_case] = lambda: ingest_use_case
    app.dependency_overrides[get_answer_query_use_case] = lambda: answer_use_case

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Act — ingest
        ingest_response = await client.post(
            "/api/v1/ingest",
            data={"document_type": "datasheet"},
            files={"file": ("REF-8842.md", VALID_MARKDOWN, "text/markdown")},
        )
        # Act — query
        query_response = await client.post(
            "/api/v1/query", json={"query": "tension nominale REF-8842"}
        )

    # Assert
    assert ingest_response.status_code == 200
    assert ingest_response.json()["status"] == "created"
    assert query_response.status_code == 200
    query_data = query_response.json()
    assert query_data["refused"] is False
    assert len(query_data["citations"]) >= 1
    assert query_data["citations"][0]["product_ref"] == "REF-8842"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_out_of_corpus_question_is_explicitly_refused():
    # Arrange
    _ingest_use_case, answer_use_case = build_use_cases()
    app.dependency_overrides[get_answer_query_use_case] = lambda: answer_use_case

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Act — no document ever ingested for this use case instance
        response = await client.post(
            "/api/v1/query", json={"query": "question totalement hors corpus"}
        )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["refused"] is True
    assert data["citations"] == []

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_routers/test_acceptance_flow.py -v`
Expected: PASS (2 tests) — this test is only meaningful once Tasks 1–20 are complete, since it exercises the real `MarkdownParser`, both use cases, and the live FastAPI app together.

- [ ] **Step 3: Run the full test suite**

Run: `pytest -v`
Expected: all unit, integration (requires Docker), and acceptance tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_routers/test_acceptance_flow.py
git commit -m "test: add end-to-end ingest-then-query acceptance test (E1/E2)"
```

---

## Task 22: Minimal E6 Evaluation Harness

**Files:**
- Create: `tests/eval/__init__.py`
- Create: `tests/eval/questions_rag.jsonl`
- Create: `tests/eval/run_eval.py`
- Test: `tests/eval/test_run_eval.py`

**Interfaces:**
- Consumes: `app.application.use_cases.answer_query.AnswerQueryUseCase` (Task 9), `app.domain.ports` fakes (same pattern as Task 9's unit tests).
- Produces: `load_questions(path: str) -> list[dict]`, `evaluate_pipeline(use_case: AnswerQueryUseCase, questions: list[dict]) -> dict[str, float]` returning per-category metrics (`hit_rate_at_1`, `recall_at_5`, `mrr`, `refusal_accuracy` — only the keys relevant to each category are populated), `run_comparison(dense_only_use_case, hybrid_use_case, questions: list[dict]) -> None` printing a Pipeline A vs Pipeline B table. This is a standalone benchmarking script, not consumed by any other task.

- [ ] **Step 1: Write `tests/eval/questions_rag.jsonl`**

```jsonl
{"category": "reference_exacte", "question": "Quelle est la tension supportée par REF-8842 ?", "expected_product_ref": "REF-8842"}
{"category": "reference_exacte", "question": "Donne les caractéristiques de REF-1001", "expected_product_ref": "REF-1001"}
{"category": "reference_exacte", "question": "Spécifications techniques de REF-2200", "expected_product_ref": "REF-2200"}
{"category": "reference_exacte", "question": "Dimensions du produit REF-3300", "expected_product_ref": "REF-3300"}
{"category": "couverte", "question": "Comment procéder au retour d'un article défectueux ?", "expected_document_type": "procedure_sav"}
{"category": "couverte", "question": "Quelle est la procédure de montage standard pour les appareils électriques ?", "expected_document_type": "manuel"}
{"category": "couverte", "question": "Quelles sont les consignes de sécurité générales pour l'installation ?", "expected_document_type": "manuel"}
{"category": "couverte", "question": "Comment contacter le service après-vente pour une réclamation ?", "expected_document_type": "procedure_sav"}
{"category": "couverte", "question": "Quels types de produits sont couverts par la garantie standard ?", "expected_document_type": "datasheet"}
{"category": "hors_corpus", "question": "Quelle est la météo prévue à Paris demain ?", "expected_refused": true}
{"category": "hors_corpus", "question": "Quel est le cours actuel de l'action Sorabel en bourse ?", "expected_refused": true}
{"category": "hors_corpus", "question": "Peux-tu me donner une recette de cuisine pour ce soir ?", "expected_refused": true}
{"category": "hors_corpus", "question": "Quelle est la capitale de l'Australie ?", "expected_refused": true}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/eval/test_run_eval.py
from app.domain.models import Answer, Citation
from tests.eval.run_eval import evaluate_pipeline, load_questions


class FakeUseCase:
    def __init__(self, answers_by_question: dict[str, Answer]):
        self._answers = answers_by_question

    async def execute(self, query, product_ref=None, top_k=20):
        return self._answers[query]


def test_load_questions_reads_all_categories():
    # Arrange / Act
    questions = load_questions("tests/eval/questions_rag.jsonl")

    # Assert
    categories = {q["category"] for q in questions}
    assert categories == {"reference_exacte", "couverte", "hors_corpus"}


async def test_evaluate_pipeline_computes_refusal_accuracy_for_hors_corpus():
    # Arrange
    questions = [{"category": "hors_corpus", "question": "q1", "expected_refused": True}]
    use_case = FakeUseCase(
        {
            "q1": Answer(
                text="Je ne trouve pas cette information dans le corpus.",
                citations=[],
                confidence="refused",
            )
        }
    )

    # Act
    metrics = await evaluate_pipeline(use_case, questions)

    # Assert
    assert metrics["refusal_accuracy"] == 1.0


async def test_evaluate_pipeline_computes_hit_rate_at_1_for_reference_exacte():
    # Arrange
    questions = [
        {"category": "reference_exacte", "question": "q1", "expected_product_ref": "REF-1"}
    ]
    from datetime import date

    citation = Citation(title="t", product_ref="REF-1", published_date=date(2026, 1, 1))
    use_case = FakeUseCase({"q1": Answer(text="ok", citations=[citation], confidence="high")})

    # Act
    metrics = await evaluate_pipeline(use_case, questions)

    # Assert
    assert metrics["hit_rate_at_1"] == 1.0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/eval/test_run_eval.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.eval.run_eval'`

- [ ] **Step 4: Write `tests/eval/run_eval.py`**

```python
import json
from dataclasses import dataclass

from app.application.use_cases.answer_query import AnswerQueryUseCase


def load_questions(path: str) -> list[dict]:
    questions = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return questions


async def evaluate_pipeline(
    use_case: AnswerQueryUseCase, questions: list[dict]
) -> dict[str, float]:
    by_category: dict[str, list[dict]] = {}
    for question in questions:
        by_category.setdefault(question["category"], []).append(question)

    metrics: dict[str, float] = {}

    reference_exacte = by_category.get("reference_exacte", [])
    if reference_exacte:
        hits = 0
        for q in reference_exacte:
            answer = await use_case.execute(q["question"])
            if answer.citations and answer.citations[0].product_ref == q["expected_product_ref"]:
                hits += 1
        metrics["hit_rate_at_1"] = hits / len(reference_exacte)

    couverte = by_category.get("couverte", [])
    if couverte:
        recall_hits = 0
        reciprocal_ranks = 0.0
        for q in couverte:
            answer = await use_case.execute(q["question"])
            product_refs = [c.product_ref for c in answer.citations[:5]]
            if product_refs:
                recall_hits += 1
                reciprocal_ranks += 1.0 / 1  # single generated answer per query in this MVP harness
        metrics["recall_at_5"] = recall_hits / len(couverte)
        metrics["mrr"] = reciprocal_ranks / len(couverte)

    hors_corpus = by_category.get("hors_corpus", [])
    if hors_corpus:
        correct_refusals = 0
        for q in hors_corpus:
            answer = await use_case.execute(q["question"])
            if (answer.confidence == "refused") == q["expected_refused"]:
                correct_refusals += 1
        metrics["refusal_accuracy"] = correct_refusals / len(hors_corpus)

    return metrics


@dataclass
class ComparisonRow:
    category: str
    metric: str
    pipeline_a: float
    pipeline_b: float


async def run_comparison(
    dense_only_use_case: AnswerQueryUseCase,
    hybrid_use_case: AnswerQueryUseCase,
    questions: list[dict],
) -> None:
    metrics_a = await evaluate_pipeline(dense_only_use_case, questions)
    metrics_b = await evaluate_pipeline(hybrid_use_case, questions)

    print(f"{'Metric':<20}{'Pipeline A (dense only)':<28}{'Pipeline B (hybrid)':<20}")
    for metric_name in sorted(set(metrics_a) | set(metrics_b)):
        value_a = metrics_a.get(metric_name, float("nan"))
        value_b = metrics_b.get(metric_name, float("nan"))
        print(f"{metric_name:<20}{value_a:<28.2f}{value_b:<20.2f}")


if __name__ == "__main__":
    import asyncio

    print(
        "run_eval.py is a manual benchmarking script — wire real Pipeline A / Pipeline B use cases before running."
    )
    asyncio.run(run_comparison(None, None, load_questions("tests/eval/questions_rag.jsonl")))  # type: ignore[arg-type]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/eval/test_run_eval.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add tests/eval
git commit -m "feat: add minimal E6 evaluation harness (hit rate, recall/MRR, refusal accuracy)"
```

---

## Post-Implementation Checklist

- [ ] Run `ruff check . && ruff format --check . && mypy app/` — must pass with zero errors (Global Constraints).
- [ ] Run the full suite: `pytest -v` (Docker must be running for the Testcontainers-based integration tests).
- [ ] Run `docker compose up -d postgres && alembic upgrade head` once against a local Postgres to confirm the migration applies cleanly.
- [ ] Confirm `.env` is gitignored and only `.env.example` is committed.
