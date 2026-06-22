import json
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import nespresso.db.models  # noqa: F401 — ensure all models are registered with Base.metadata
from nespresso.core.configs.admin_ids import DEFAULT_ADMIN_IDS
from nespresso.core.configs.settings import settings
from nespresso.db.base import Base

engine = create_async_engine(
    settings.POSTGRES_DSN.get_secret_value(),
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def EnsureDB() -> None:
    """
    Create all SQLAlchemy-mapped tables in the database if they don't already exist.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("ALTER TABLE tg_user ADD COLUMN IF NOT EXISTS language VARCHAR")
        )
        await conn.execute(
            text(
                "ALTER TABLE tg_user ADD COLUMN IF NOT EXISTS matching_paused BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await conn.execute(
            text("ALTER TABLE tg_user ADD COLUMN IF NOT EXISTS panel_message_id BIGINT")
        )
        await conn.execute(
            text(
                "ALTER TABLE tg_user ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await conn.execute(
            text("ALTER TABLE nes_user ADD COLUMN IF NOT EXISTS alumni BOOLEAN")
        )
        await conn.execute(
            text("ALTER TABLE nes_user ADD COLUMN IF NOT EXISTS nes_email VARCHAR")
        )
        await conn.execute(
            text("ALTER TABLE nes_user ADD COLUMN IF NOT EXISTS sex VARCHAR")
        )
        await conn.execute(
            text("ALTER TABLE nes_user ADD COLUMN IF NOT EXISTS programs JSON")
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_nes_user_nes_email ON nes_user (nes_email)"
            )
        )
        # MyNES directory sync columns (see NesUser model).
        await conn.execute(
            text(
                "ALTER TABLE nes_user ADD COLUMN IF NOT EXISTS "
                "listed BOOLEAN NOT NULL DEFAULT TRUE"
            )
        )
        await conn.execute(
            text("ALTER TABLE nes_user ADD COLUMN IF NOT EXISTS mynes_text_hash VARCHAR")
        )
        await conn.execute(
            text(
                "ALTER TABLE nes_user ADD COLUMN IF NOT EXISTS "
                "synced_at TIMESTAMPTZ"
            )
        )

        # Migration: convert message PK from (message_id) to (chat_id, message_id)
        # because Telegram message_id is unique only within a chat.
        pk_columns = await conn.execute(
            text(
                "SELECT a.attname "
                "FROM pg_index i "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid = 'message'::regclass AND i.indisprimary"
            )
        )
        existing_pk = {row[0] for row in pk_columns}
        if existing_pk == {"message_id"}:
            logging.info(
                "Migrating message table PK from (message_id) to (chat_id, message_id)"
            )
            await conn.execute(text("ALTER TABLE message DROP CONSTRAINT message_pkey"))
            await conn.execute(
                text("ALTER TABLE message ADD PRIMARY KEY (chat_id, message_id)")
            )

        # One-time migration: seed admin IDs from admins.json if it exists
        _admins_json = Path("data/admins/admins.json")
        admin_ids_to_seed = list(DEFAULT_ADMIN_IDS)
        if _admins_json.is_file():
            try:
                stored_ids = json.loads(_admins_json.read_text())
                admin_ids_to_seed = list({*admin_ids_to_seed, *stored_ids})
            except Exception:
                logging.warning(
                    "Could not read admins.json for migration", exc_info=True
                )

        for admin_id in admin_ids_to_seed:
            await conn.execute(
                text("UPDATE tg_user SET is_admin = TRUE WHERE chat_id = :chat_id"),
                {"chat_id": admin_id},
            )
