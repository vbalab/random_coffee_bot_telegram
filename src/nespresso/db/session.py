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
        # Persisted retrieval texts (so an admin DB export shows them): raw
        # directory SearchText, raw user bio, and the final enriched text.
        await conn.execute(
            text("ALTER TABLE nes_user ADD COLUMN IF NOT EXISTS mynes_text VARCHAR")
        )
        await conn.execute(
            text("ALTER TABLE nes_user ADD COLUMN IF NOT EXISTS about_text VARCHAR")
        )
        await conn.execute(
            text("ALTER TABLE nes_user ADD COLUMN IF NOT EXISTS enriched_text VARCHAR")
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

        # Best-effort: enforce one verified TgUser per nes_id. Isolated in its own
        # SAVEPOINT because on a database that already has duplicate verified rows
        # for the same nes_id (the exact bug this closes), CREATE UNIQUE INDEX
        # fails — and without the savepoint that failure would poison every
        # statement after it in this transaction, breaking startup entirely.
        try:
            async with conn.begin_nested():
                await conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS "
                        "ix_tg_user_nes_id_verified_uniq ON tg_user (nes_id) "
                        "WHERE verified = true"
                    )
                )
        except Exception:
            logging.warning(
                "Could not create unique index on tg_user(nes_id) WHERE verified "
                "— there are likely pre-existing duplicate verified rows for the "
                "same nes_id that need manual cleanup first.",
                exc_info=True,
            )

        try:
            async with conn.begin_nested():
                await conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS "
                        "ix_match_feedback_assignment_id_uniq "
                        "ON match_feedback (assignment_id)"
                    )
                )
        except Exception:
            logging.warning(
                "Could not create unique index on match_feedback(assignment_id) "
                "— there are likely pre-existing duplicate feedback rows for the "
                "same assignment that need manual cleanup first.",
                exc_info=True,
            )

        await conn.execute(
            text(
                "ALTER TABLE match_round ADD COLUMN IF NOT EXISTS "
                "feedback_sent_at TIMESTAMPTZ"
            )
        )

        # Per-user profile reactions + hidden profiles (see ProfileReaction).
        # create_all above builds the whole table on a fresh DB; these idempotent
        # statements bring an already-existing table up to the current shape and
        # guarantee the unique target the atomic upserts (ON CONFLICT) rely on.
        await conn.execute(
            text("ALTER TABLE profile_reaction ADD COLUMN IF NOT EXISTS reaction VARCHAR")
        )
        await conn.execute(
            text(
                "ALTER TABLE profile_reaction ADD COLUMN IF NOT EXISTS "
                "blocked BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_profile_reaction_rater_chat_id "
                "ON profile_reaction (rater_chat_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_profile_reaction_target_nes_id "
                "ON profile_reaction (target_nes_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_profile_reaction_rater_target "
                "ON profile_reaction (rater_chat_id, target_nes_id)"
            )
        )
