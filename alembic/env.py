"""Alembic migration environment for the NESpresso bot.

Wiring notes:
- ``target_metadata`` is ``nespresso.db.base.Base.metadata``. We import
  ``nespresso.db.models`` (its ``__init__`` imports every model module) purely
  for its side effect of registering all tables on ``Base.metadata`` — including
  ``profile_reaction`` — so ``--autogenerate`` sees the full schema.
- The database URL is pulled from
  ``nespresso.core.configs.settings.settings.POSTGRES_DSN`` (a ``SecretStr``),
  the exact same source the running app uses. The placeholder in ``alembic.ini``
  is never used. We inject the real DSN directly into the engine-config dict
  (rather than ``config.set_main_option``) so a password containing ``%`` is not
  mangled by ConfigParser interpolation.
- The DSN is async (``postgresql+asyncpg://``). We keep it async and use the
  standard Alembic async template (``async_engine_from_config`` +
  ``asyncio.run`` + ``connection.run_sync(do_run_migrations)``) rather than
  swapping in a sync driver — this reuses the app's own driver/DSN verbatim, so
  there is one connection string to reason about and nothing to keep in sync.
"""

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Make the `nespresso` package importable when alembic is invoked from the repo
# root (the Docker image sets PYTHONPATH=/usr/src/app/src, but this keeps local
# `alembic ...` runs working too). env.py lives at <root>/alembic/env.py, so
# parents[1] is the repo root and `src/` sits beside it.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import nespresso.db.models  # noqa: E402,F401 — registers every model on Base.metadata
from nespresso.core.configs.settings import settings  # noqa: E402
from nespresso.db.base import Base  # noqa: E402

# Alembic Config object — access to values in alembic.ini.
config = context.config

# Configure Python logging from the ini file.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata autogenerate compares the live DB against.
target_metadata = Base.metadata


def _database_url() -> str:
    """The app's async DSN, unwrapped from its SecretStr."""
    return settings.POSTGRES_DSN.get_secret_value()


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DB connection (`alembic ... --sql`)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations through a sync-wrapped connection."""
    configuration = config.get_section(config.config_ini_section, {})
    # Inject the real DSN here (not via ConfigParser) so `%` in a password is safe.
    configuration["sqlalchemy.url"] = _database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
