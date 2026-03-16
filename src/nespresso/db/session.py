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
            text(
                "ALTER TABLE tg_user ADD COLUMN IF NOT EXISTS panel_message_id BIGINT"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE tg_user ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )

        # One-time migration: seed admin IDs from admins.json if it exists
        _admins_json = Path("data/admins/admins.json")
        admin_ids_to_seed = list(DEFAULT_ADMIN_IDS)
        if _admins_json.is_file():
            try:
                stored_ids = json.loads(_admins_json.read_text())
                admin_ids_to_seed = list({*admin_ids_to_seed, *stored_ids})
            except Exception:
                logging.warning("Could not read admins.json for migration", exc_info=True)

        for admin_id in admin_ids_to_seed:
            await conn.execute(
                text("UPDATE tg_user SET is_admin = TRUE WHERE chat_id = :chat_id"),
                {"chat_id": admin_id},
            )
