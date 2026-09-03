"""Migrations are exercised as migrations here.

The shared `db_session` fixture builds the schema with
`Base.metadata.create_all`, which never runs Alembic — so nothing else in the
suite would notice a broken revision. These tests drive `alembic upgrade head`
against a real pgvector container instead.
"""

import asyncio
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DOCUMENT_ID = "REF-8842::datasheet::1"

# chunks.document_id is a foreign key, so the parent document comes first.
INSERT_DOCUMENT = sa.text(
    f"""
    INSERT INTO documents (
        id, product_ref, document_type, title, version,
        status, published_date, source_path, content_hash
    ) VALUES (
        '{DOCUMENT_ID}', 'REF-8842', 'datasheet', 'Fiche REF-8842', '1',
        'active', DATE '2026-01-01', '/corpus/ref-8842.md', 'hash-1'
    )
    """
)

INSERT_CHUNK = sa.text(
    f"""
    INSERT INTO chunks (
        id, document_id, content, content_type, title, product_ref,
        version, status, document_type, published_date, content_hash, source_path
    ) VALUES (
        'chunk-1', '{DOCUMENT_ID}', 'La pompe REF-8842 nécessite un joint torique.',
        'text', 'Fiche REF-8842', 'REF-8842', '1', 'active', 'datasheet',
        DATE '2026-01-01', 'hash-1', '/corpus/ref-8842.md'
    )
    """
)


def _alembic_config(url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


async def _fetch_all(url: str, statements: list[sa.TextClause]) -> list[list[Any]]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return [list(await connection.execute(stmt)) for stmt in statements]
    finally:
        await engine.dispose()


async def _execute(url: str, statement: sa.TextClause) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(statement)
    finally:
        await engine.dispose()


@pytest.fixture
def migration_db_url(postgres_container: Any) -> Iterator[str]:
    """A dedicated, empty database per test, on the shared container.

    Migrations must not run against the database the ORM-based fixtures use,
    or the two schema-creation paths would fight over the same tables.
    """
    admin_url = postgres_container.get_connection_url()
    base, _, _ = admin_url.rpartition("/")
    name = f"migration_check_{uuid.uuid4().hex[:8]}"

    async def create() -> None:
        engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as connection:
                await connection.execute(sa.text(f'CREATE DATABASE "{name}"'))
        finally:
            await engine.dispose()

    async def drop() -> None:
        engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as connection:
                await connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}"'))
        finally:
            await engine.dispose()

    asyncio.run(create())
    try:
        yield f"{base}/{name}"
    finally:
        asyncio.run(drop())


def test_upgrade_head_installs_extension_and_both_tables(migration_db_url: str) -> None:
    # Arrange
    config = _alembic_config(migration_db_url)

    # Act
    command.upgrade(config, "head")

    # Assert
    extensions, tables = asyncio.run(
        _fetch_all(
            migration_db_url,
            [
                sa.text("SELECT extname FROM pg_extension WHERE extname = 'vector'"),
                sa.text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
                ),
            ],
        )
    )
    assert [row[0] for row in extensions] == ["vector"]
    assert {row[0] for row in tables} >= {"chunks", "documents"}


def test_upgrade_head_creates_gin_and_hnsw_retrieval_indexes(migration_db_url: str) -> None:
    # Arrange
    config = _alembic_config(migration_db_url)

    # Act
    command.upgrade(config, "head")

    # Assert — both hybrid retrieval paths must be index-backed, and by the
    # right access method: a btree on either column would be useless.
    (index_rows,) = asyncio.run(
        _fetch_all(
            migration_db_url,
            [
                sa.text(
                    """
                    SELECT idx_class.relname, method.amname
                    FROM pg_index AS idx
                    JOIN pg_class AS idx_class ON idx_class.oid = idx.indexrelid
                    JOIN pg_class AS tbl_class ON tbl_class.oid = idx.indrelid
                    JOIN pg_am AS method ON method.oid = idx_class.relam
                    WHERE tbl_class.relname = 'chunks'
                    """
                )
            ],
        )
    )
    methods_by_index = dict(index_rows)
    assert methods_by_index.get("ix_chunks_search_vector_gin") == "gin"
    assert methods_by_index.get("ix_chunks_embedding_hnsw") == "hnsw"


def test_search_vector_is_generated_by_postgres_on_insert(migration_db_url: str) -> None:
    # Arrange
    command.upgrade(_alembic_config(migration_db_url), "head")

    # Act — the insert never mentions search_vector.
    asyncio.run(_execute(migration_db_url, INSERT_DOCUMENT))
    asyncio.run(_execute(migration_db_url, INSERT_CHUNK))

    # Assert
    (generated_row,), (search_vector_row,) = asyncio.run(
        _fetch_all(
            migration_db_url,
            [
                sa.text(
                    "SELECT is_generated FROM information_schema.columns "
                    "WHERE table_name = 'chunks' AND column_name = 'search_vector'"
                ),
                sa.text("SELECT search_vector FROM chunks WHERE id = 'chunk-1'"),
            ],
        )
    )
    assert generated_row[0] == "ALWAYS"
    # French stemming reduces "pompe" to "pomp", proving the configured
    # dictionary — not the default one — produced the vector.
    assert "pomp" in search_vector_row[0]


def test_downgrade_to_base_drops_tables_but_keeps_the_extension(migration_db_url: str) -> None:
    # Arrange
    config = _alembic_config(migration_db_url)
    command.upgrade(config, "head")

    # Act
    command.downgrade(config, "base")

    # Assert — dropping a database-wide extension is not this schema's call.
    tables, extensions = asyncio.run(
        _fetch_all(
            migration_db_url,
            [
                sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"),
                sa.text("SELECT extname FROM pg_extension WHERE extname = 'vector'"),
            ],
        )
    )
    remaining = {row[0] for row in tables}
    assert "chunks" not in remaining
    assert "documents" not in remaining
    assert [row[0] for row in extensions] == ["vector"]


INSERT_DOCUMENT_V2 = sa.text(
    """
    INSERT INTO documents (
        id, product_ref, document_type, title, version,
        status, published_date, source_path, content_hash
    ) VALUES (
        'REF-8842::datasheet::2', 'REF-8842', 'datasheet', 'Fiche REF-8842', '2',
        'active', DATE '2026-06-01', '/corpus/ref-8842.md', 'hash-2'
    )
    """
)

# A different surrogate id, but the same (product_ref, document_type, version).
INSERT_DOCUMENT_V2_DUPLICATE = sa.text(
    """
    INSERT INTO documents (
        id, product_ref, document_type, title, version,
        status, published_date, source_path, content_hash
    ) VALUES (
        'some-other-id', 'REF-8842', 'datasheet', 'Fiche REF-8842', '2',
        'active', DATE '2026-06-01', '/corpus/ref-8842.md', 'hash-2-bis'
    )
    """
)


def test_orphan_chunk_is_rejected_by_the_document_foreign_key(migration_db_url: str) -> None:
    # Arrange
    command.upgrade(_alembic_config(migration_db_url), "head")

    # Act / Assert — no parent document was inserted
    with pytest.raises(IntegrityError, match="fk_chunks_document_id_documents"):
        asyncio.run(_execute(migration_db_url, INSERT_CHUNK))


def test_two_versions_of_one_document_coexist_but_a_duplicate_version_does_not(
    migration_db_url: str,
) -> None:
    """The audit trail depends on this: v1 must be able to outlive its replacement."""
    # Arrange
    command.upgrade(_alembic_config(migration_db_url), "head")
    asyncio.run(_execute(migration_db_url, INSERT_DOCUMENT))

    # Act — mark v1 as deprecated before inserting v2 (mimicking the `deprecate` operation)
    asyncio.run(
        _execute(
            migration_db_url,
            sa.text(
                "UPDATE documents SET status = 'deprecated' WHERE product_ref = 'REF-8842' AND status = 'active'"
            ),
        )
    )
    # Act — insert a second version of the same document
    asyncio.run(_execute(migration_db_url, INSERT_DOCUMENT_V2))

    # Assert — both on record
    (versions,) = asyncio.run(
        _fetch_all(
            migration_db_url,
            [
                sa.text(
                    "SELECT version FROM documents WHERE product_ref = 'REF-8842' ORDER BY version"
                )
            ],
        )
    )
    assert [row[0] for row in versions] == ["1", "2"]

    # Assert — but the same version cannot be registered twice
    with pytest.raises(IntegrityError, match="uq_documents_product_ref_document_type_version"):
        asyncio.run(_execute(migration_db_url, INSERT_DOCUMENT_V2_DUPLICATE))


INSERT_LEGACY_DOCUMENT = sa.text(
    """
    INSERT INTO documents (
        product_ref, document_type, title, version,
        status, published_date, source_path, content_hash
    ) VALUES (
        'REF-100', 'datasheet', 'Fiche REF-100', '3',
        'active', DATE '2026-02-01', '/corpus/ref-100.md', 'hash-100'
    )
    """
)

INSERT_LEGACY_CHUNK = sa.text(
    """
    INSERT INTO chunks (
        id, document_id, content, content_type, title, product_ref,
        version, status, document_type, published_date, content_hash, source_path
    ) VALUES (
        'legacy-chunk', 'REF-100::datasheet', 'contenu historique', 'text',
        'Fiche REF-100', 'REF-100', '3', 'active', 'datasheet',
        DATE '2026-02-01', 'hash-100', '/corpus/ref-100.md'
    )
    """
)

INSERT_ORPHANED_LEGACY_CHUNK = sa.text(
    """
    INSERT INTO chunks (
        id, document_id, content, content_type, title, product_ref,
        version, status, document_type, published_date, content_hash, source_path
    ) VALUES (
        'orphan-chunk', 'REF-200::manuel', 'contenu orphelin', 'text',
        'Manuel REF-200', 'REF-200', '1', 'deprecated', 'manuel',
        DATE '2026-03-01', 'hash-200', '/corpus/ref-200.pdf'
    )
    """
)


def test_upgrade_rekeys_existing_rows_and_reattaches_their_chunks(
    migration_db_url: str,
) -> None:
    """The data migration, not just the DDL: rows written under the old
    composite key must survive the switch to a version-scoped id."""
    # Arrange — a database already at 0002, holding old-shape data
    config = _alembic_config(migration_db_url)
    command.upgrade(config, "0002")
    asyncio.run(_execute(migration_db_url, INSERT_LEGACY_DOCUMENT))
    asyncio.run(_execute(migration_db_url, INSERT_LEGACY_CHUNK))

    # Act
    command.upgrade(config, "head")

    # Assert — the document is rekeyed and its chunk now points at that key
    (document_row,), (chunk_row,) = asyncio.run(
        _fetch_all(
            migration_db_url,
            [
                sa.text("SELECT id, version FROM documents WHERE product_ref = 'REF-100'"),
                sa.text("SELECT document_id FROM chunks WHERE id = 'legacy-chunk'"),
            ],
        )
    )
    assert tuple(document_row) == ("REF-100::datasheet::3", "3")
    assert chunk_row[0] == "REF-100::datasheet::3"


def test_upgrade_rebuilds_a_parent_document_for_chunks_that_lost_one(
    migration_db_url: str,
) -> None:
    """The old delete-then-overwrite flow could leave chunks whose document
    row was gone; those must be reattached, not dropped."""
    # Arrange
    config = _alembic_config(migration_db_url)
    command.upgrade(config, "0002")
    asyncio.run(_execute(migration_db_url, INSERT_ORPHANED_LEGACY_CHUNK))

    # Act
    command.upgrade(config, "head")

    # Assert — a document was reconstructed from the chunk's own metadata
    (document_row,), (chunk_row,) = asyncio.run(
        _fetch_all(
            migration_db_url,
            [
                sa.text(
                    "SELECT id, title, version, status FROM documents WHERE product_ref = 'REF-200'"
                ),
                sa.text("SELECT document_id FROM chunks WHERE id = 'orphan-chunk'"),
            ],
        )
    )
    assert tuple(document_row) == ("REF-200::manuel::1", "Manuel REF-200", "1", "deprecated")
    assert chunk_row[0] == "REF-200::manuel::1"
