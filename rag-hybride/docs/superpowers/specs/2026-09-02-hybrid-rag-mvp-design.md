# Hybrid RAG MVP — Design

**Date**: 2026-09-02
**Scope**: `rag-hybride` (Sorabel Data Gateway — module documentaire)
**Status**: Approved for planning

## Context

`rag-hybride` currently has no code — only `CLAUDE.md` and `README.md`. The README
already specifies the conceptual pipeline (hybrid dense + BM25 retrieval, RRF fusion,
cross-encoder reranking, mandatory citations, explicit refusal) mapped to requirements
E1 (citation/refusal), E2 (exact lookup + natural language), E6 (hybrid-vs-dense
evaluation). This spec turns that concept into a buildable end-to-end MVP, following the
project's mandated hexagonal architecture (`.claude/rules/python-hexagonal.md`,
`rag-architecture.md`).

## Goal

An end-to-end vertical slice: ingest documents (Markdown + PDF) into dual indexes
(pgvector + tsvector), and answer queries via dense+BM25+RRF+reranking with mandatory
citations or explicit refusal — plus a minimal E6 evaluation harness. Deferred:
`lookup_by_reference` / `get_document_metadata` / `check_answer_confidence` /
`list_document_types` as separate endpoints (folded into `/query` for now), and the full
30-question E6 benchmark (a 12–15 question starter set instead).

## Decisions

| Question | Decision |
|---|---|
| First buildable slice | End-to-end MVP: ingestion + hybrid query |
| REST surface | Two endpoints: `POST /api/v1/query`, `POST /api/v1/ingest` |
| Source formats | Markdown + PDF (parser port open for more later) |
| Reranker | Local cross-encoder via `sentence-transformers` (e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2`), in-process via `run_in_threadpool` |
| E6 harness | Minimal version included now (not deferred) |
| RRF fusion location | Application/domain layer (pure Python function), not SQL — keeps fusion unit-testable without a DB, per the testing rule prioritizing fusion-logic tests |

## Architecture

```
app/
├── domain/
│   ├── models.py       # Document, Chunk, RetrievalResult, Answer, Citation
│   ├── fusion.py        # reciprocal_rank_fusion() — pure function, no I/O
│   └── ports.py          # DocumentParserPort, VectorStorePort, LexicalSearchPort,
│                         # EmbeddingPort, RerankerPort, LLMPort
├── application/
│   └── use_cases/
│       ├── ingest_document.py
│       └── answer_query.py
├── infrastructure/
│   ├── postgres/
│   │   ├── pgvector_repository.py   # implements VectorStorePort
│   │   └── bm25_repository.py       # implements LexicalSearchPort (tsvector)
│   ├── parsers/
│   │   ├── markdown_parser.py       # implements DocumentParserPort
│   │   └── pdf_parser.py            # implements DocumentParserPort
│   ├── azure_openai/
│   │   ├── embedding_client.py      # implements EmbeddingPort
│   │   └── llm_client.py            # implements LLMPort
│   └── reranker/
│       └── cross_encoder_reranker.py  # implements RerankerPort
└── api/
    ├── routes/
    │   ├── query.py    # POST /api/v1/query
    │   └── ingest.py   # POST /api/v1/ingest
    └── schemas/
        ├── query.py    # QueryRequest, QueryResponse
        └── ingest.py    # IngestRequest, IngestResponse
```

### Domain models

- `Document`: `id`, `title`, `product_ref`, `version`, `status` (`active`/`deprecated`),
  `document_type` (`datasheet`/`manuel`/`procedure_sav`), `published_date`,
  `source_path`/`url`, `content_hash`. `id` identifies one *version* —
  `make_document_id(product_ref, document_type, version)` in `domain/versioning.py`
  is its single source of truth. A version-less id cannot satisfy the audit rule
  below: re-ingesting would overwrite the previous document row.
- `Chunk`: `id`, `document_id`, `content`, `content_type` (`text`/`table`), and all of the
  above document metadata denormalized onto the chunk (required, not optional — every
  chunk must be self-describing for citation).
- `RetrievalResult`: `chunk`, `dense_rank`, `sparse_rank`, `fused_score`, `rerank_score`.
- `Answer`: `text`, `citations: list[Citation]`, `confidence` (`high`/`low`/`refused`).
- `Citation`: `title`, `product_ref`, `published_date`, `url`.

### Ports (Protocols)

- `DocumentParserPort.parse(raw_bytes, document_type) -> tuple[Document, list[RawSection]]`
- `VectorStorePort.upsert(chunks_with_embeddings)`, `.search(embedding, top_k, filters)`,
  `.delete_by_document_id(document_id)`
- `LexicalSearchPort` — same shape, tsvector-backed
- `EmbeddingPort.embed(text) -> Vector`
- `RerankerPort.score(query, chunk_text) -> float`
- `LLMPort.generate(query, cited_chunks) -> Answer`

## Ingestion pipeline (`ingest_document` use case)

1. **Input**: raw file bytes + `document_type` + `source_path`/`url` via `POST /api/v1/ingest`.
2. **Parse**: dispatch to `MarkdownParser` or `PdfParser` by extension/MIME → normalized
   `Document` + a list of raw sections, each tagged `content_type` (`text`/`table`).
3. **Chunk by section**:
   - Markdown: split on headers (`#`, `##`, ...); a GFM table stays one chunk, never split.
   - PDF: split on detected headings (font-size/style heuristics, e.g. via `pdfplumber`),
     falling back to paragraph grouping when no heading structure is detected; extracted
     tables stay one chunk.
   - Sizing: merge/re-split so each chunk lands in ~50–250 tokens. A document under ~150
     tokens becomes exactly one chunk. ~10–15% overlap applied only above 50 tokens.
4. **Dedup/versioning**: compute `content_hash` (SHA-256) per document.
   - Same `product_ref`/`doc_id`, different hash → previous version marked `deprecated`
     (soft — kept for audit), new version inserted `active`.
   - Same hash → no-op (idempotent re-ingest).
5. **Metadata stamping**: every chunk carries `document_id`, `document_type`, `title`,
   `version`, `date`, `product_ref`, `content_hash`, `status`, `content_type`,
   `source_path`/`url` — enforced fields on the `Chunk` model, not optional.
6. **Dual indexing**: `EmbeddingPort.embed()` per chunk → `VectorStorePort.upsert()`; same
   chunk text → `LexicalSearchPort.upsert()`. Both keyed by the same `chunk_id`, written in
   one DB transaction (delete-then-insert both) so neither index can drift ahead of the
   other on partial failure.
7. **Response**: `IngestResponse { document_id, chunk_count, status: created|updated|unchanged }`.

## Query pipeline (`answer_query` use case)

1. **Input**: `POST /api/v1/query` with `query` (str), optional `product_ref`, optional `top_k`.
2. **Exact-ref pre-filter**: if `product_ref` is given, it filters both searches to that
   `product_ref`'s active chunks before scoring — this is how E2's exact-lookup case is
   served, without a separate code path from natural-language search.
3. **Parallel retrieval**: `VectorStorePort.search()` and `LexicalSearchPort.search()` run
   concurrently (`asyncio.gather`), both scoped to `status = active`.
4. **Fusion**: `reciprocal_rank_fusion(dense_results, sparse_results, k=60)` — pure domain
   function, `score = Σ 1/(k + rank_i)`, no manual weighting — yields one ranked list.
5. **Reranking**: top-N (default 10) fused candidates scored by `RerankerPort.score()`
   (cross-encoder, `run_in_threadpool`), reordered by rerank score.
6. **Confidence gate** on the top rerank score, thresholds as named constants in
   `application/`:
   - `≥ 0.7` → generate normally.
   - `0.4–0.7` → generate, but `LLMPort` is instructed to hedge; response marks
     `confidence: "low"`.
   - `< 0.4` → **no LLM call** — return the fixed refusal string, `citations: []`,
     `confidence: "refused"`.
7. **Generation**: `LLMPort.generate()` receives only the cited chunk texts + query and
   returns structured output. Citations are assembled by the use case from the chunks
   actually sent to the LLM — never parsed out of free-text LLM output — eliminating
   hallucinated citations by construction.
8. **Response**: `QueryResponse { answer, citations: [{title, product_ref, published_date}], confidence, refused: bool }`.

## API contracts & error handling

- Follows `.claude/rules/api-contracts.md`: no response envelope, `snake_case` fields,
  routes under `/api/v1/`.
- Errors: uniform `{error_code, message, correlation_id}` via a `main.py` exception
  handler mapping domain exceptions to HTTP status codes.
- `422` for Pydantic validation errors (malformed `IngestRequest`/`QueryRequest`).
- Domain exceptions (`UnparsableDocumentError`, `EmbeddingServiceError`, ...) map to
  specific `4xx`/`5xx` with a stable `error_code`; `message` never leaks corpus content
  or confirms/denies existence of an unauthorized resource.
- No broad `except Exception` anywhere.

## Testing strategy

- **Unit** (`tests/unit/`, all ports mocked, no I/O):
  - `reciprocal_rank_fusion`: a chunk present in both dense and sparse rankings is
    favored over one present in only one.
  - Chunking by section: markdown header split, table-never-split, tiny-document →
    single-chunk.
  - Confidence gate: correct branch (generate / hedge / refuse) at each threshold band,
    with mocked `RerankerPort`/`LLMPort`.
  - Dedup/versioning: same hash → no-op; different hash → old version deprecated, new
    version active.
- **Integration** (`tests/integration/`, Testcontainers Postgres+pgvector, no mocks on
  infrastructure):
  - `pgvector_repository` / `bm25_repository` round-trip: upsert → search → version
    supersede.
  - Full ingest → query flow against the real database.
- **Acceptance** (`tests/test_routers/`, `httpx.AsyncClient`):
  - Ingest a fixture document, then query it — assert citations are present.
  - Query an out-of-corpus question — assert explicit refusal, no citations.

## Evaluation harness (E6, minimal)

- `tests/eval/questions_rag.jsonl`: ~12–15 questions across the three categories
  (`reference_exacte`, `couverte`, `hors_corpus`) — a starter set, not the full 30.
- `tests/eval/run_eval.py`: loads a fixture corpus, runs **Pipeline A** (dense-only —
  skip sparse search, fusion, and reranking) vs **Pipeline B** (full hybrid), computes
  Hit Rate@1 (`reference_exacte`), Recall@5 + MRR (`couverte`), refusal accuracy
  (`hors_corpus`) per category, and prints a comparison table.
- Not wired into CI by default — a manual benchmarking tool (candidate for a future
  `/eval-retrieval` command), not a correctness gate.

## Deployment

- `docker-compose.yml` for local dev: Postgres with the `pgvector` extension enabled,
  behind a `pg_isready` healthcheck so dependents can wait on `condition:
  service_healthy`. Postgres only — the app runs on the host until there is a
  Dockerfile to build. Credentials come from `POSTGRES_*` in `.env`, never inline.
- Schema is created and evolved exclusively through Alembic (`alembic upgrade head`).
  Migrations resolve their target from `sqlalchemy.url`, then `DATABASE_URL`, then
  `Settings` — so initializing a database needs a connection string and nothing else.
- `chunks.search_vector` is a Postgres STORED generated column, indexed with GIN;
  `chunks.embedding` is indexed with HNSW using `vector_cosine_ops`, matching the
  cosine ordering the dense repository queries with.
- `documents` is keyed by the surrogate, version-scoped `id`, under a unique
  constraint on `(product_ref, document_type, version)` — one row per version, so a
  superseded version survives as its own `deprecated` row. `chunks.document_id` is a
  foreign key onto it (`ON DELETE CASCADE`), which is why `ingest_document` registers
  the document before indexing its chunks.
- Azure OpenAI reached via environment variables (`AZURE_OPENAI_*`), loaded through
  `pydantic-settings`; `.env` is gitignored, `.env.example` documents the expected keys
  (`AZURE_OPENAI_*`, `DATABASE_URL`) with no real values.
- The cross-encoder reranker model is downloaded and cached into the image at build
  time, so reranking has no runtime network dependency.

## Deferred (explicitly out of scope for this spec)

- Separate REST endpoints for `lookup_by_reference`, `get_document_metadata`,
  `check_answer_confidence`, `list_document_types` (folded into `/query` behavior for now).
- The full 30-question E6 benchmark and any automated regression gate on it.
- HTML source format support (parser port is open for it; no adapter built yet).
- Any access-matrix/profile filtering — per `rag-hybride/CLAUDE.md`, that is
  `authorization-gateway`'s responsibility; this project assumes every call it receives
  is already authorized.
