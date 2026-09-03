import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.infrastructure.postgres.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    """Resolve the migration target, most specific source first.

    Falling back to `Settings` only as a last resort keeps `alembic upgrade
    head` runnable with nothing but a connection string — the full `Settings`
    model also requires Azure OpenAI credentials, which migrations never use.
    """
    configured = config.get_main_option("sqlalchemy.url", default=None)
    if configured:
        return configured
    from_env = os.environ.get("DATABASE_URL")
    if from_env:
        return from_env
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # NOTE: `--autogenerate` does not reliably diff `Computed` columns or
    # index options such as HNSW's `m`/`ef_construction`. Revisions touching
    # either must be hand-checked after generation.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(database_url())
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
