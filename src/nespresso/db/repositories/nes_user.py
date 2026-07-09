import logging
from collections.abc import Iterable, Sequence
from typing import Any, TypeVar, overload

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from nespresso.db.models.nes_user import NesUser
from nespresso.db.repositories.checking import (
    CheckColumnBelongsToModel,
)

T = TypeVar("T")

# Bulk-write chunk sizes. Postgres/asyncpg caps a single statement at 32767
# bound parameters; a sync row carries ~23 columns, so 500 rows ≈ 11.5k params.
_UPSERT_CHUNK = 500
_SELECT_CHUNK = 1000


class NesUserRepository:
    def __init__(self, session: async_sessionmaker[AsyncSession]):
        self.session = session

    # ----- Create -----

    async def UpsertNesUsers(self, users: NesUser | list[NesUser]) -> None:
        if isinstance(users, NesUser):
            users = [users]

        async with self.session() as session:
            for user in users:
                full = {
                    c.name: getattr(user, c.name) for c in NesUser.__table__.columns
                }
                # only keep client-supplied (non-None) fields
                insert_dict = {k: v for k, v in full.items() if v is not None}
                update_dict = {k: v for k, v in insert_dict.items() if k != "nes_id"}

                await session.execute(
                    insert(NesUser)
                    .values(insert_dict)
                    .on_conflict_do_update(
                        index_elements=[NesUser.nes_id],
                        set_=update_dict,
                    )
                )

                logging.info(f"NesUser(nes_id={user.nes_id}) upserted successfully.")

            await session.commit()

    async def SyncUpsertNesUsers(self, rows: list[dict[str, Any]]) -> None:
        """
        Full-mirror upsert used by the hourly MyNES directory sync.

        Unlike `UpsertNesUsers`, this writes every supplied column verbatim —
        including ``None`` — so that a profile that lost work/education data
        (because the user revoked that flag) is overwritten rather than kept
        stale. The caller decides which columns are in `rows`; ``created_at`` is
        intentionally excluded so it is preserved across syncs. (As of the feed
        update, ``nes_email``/``sex``/``programs`` ARE in `rows` and get written.)
        """
        if not rows:
            return

        update_cols = [c for c in rows[0] if c != "nes_id"]

        def _set_value(stmt: Any, col: str) -> Any:
            # nes_email can be bound at registration (byEmail) independently of the
            # directory feed. Never let a NULL incoming value clobber a stored one:
            # only overwrite when the feed actually carries an email.
            if col == "nes_email":
                return func.coalesce(stmt.excluded.nes_email, NesUser.nes_email)
            return getattr(stmt.excluded, col)

        async with self.session() as session:
            for start in range(0, len(rows), _UPSERT_CHUNK):
                chunk = rows[start : start + _UPSERT_CHUNK]
                stmt = insert(NesUser).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[NesUser.nes_id],
                    set_={c: _set_value(stmt, c) for c in update_cols},
                )
                await session.execute(stmt)

            await session.commit()

        logging.info(f"SyncUpsertNesUsers: {len(rows)} rows upserted.")

    # ----- Read -----

    async def GetNesUserByEmail(self, nes_email: str) -> NesUser | None:
        async with self.session() as session:
            result = await session.execute(
                select(NesUser).where(NesUser.nes_email == nes_email).limit(1)
            )
            return result.scalars().first()

    async def CountListedNesUsers(self) -> int:
        async with self.session() as session:
            result = await session.execute(
                select(func.count()).select_from(NesUser).where(NesUser.listed.is_(True))
            )
            return int(result.scalar_one())

    async def GetNesUserHashes(
        self, nes_ids: Sequence[int]
    ) -> dict[int, str | None]:
        """Return ``{nes_id: mynes_text_hash}`` for the given ids (sync diffing)."""
        ids = list(nes_ids)
        hashes: dict[int, str | None] = {}
        async with self.session() as session:
            for start in range(0, len(ids), _SELECT_CHUNK):
                chunk = ids[start : start + _SELECT_CHUNK]
                result = await session.execute(
                    select(NesUser.nes_id, NesUser.mynes_text_hash).where(
                        NesUser.nes_id.in_(chunk)
                    )
                )
                for nes_id, text_hash in result.all():
                    hashes[nes_id] = text_hash
        return hashes

    @overload
    async def GetNesUsersOnCondition(
        self,
        condition: ColumnElement[bool] | InstrumentedAttribute[bool],
        column: None = None,
    ) -> list[NesUser] | None: ...

    @overload
    async def GetNesUsersOnCondition(
        self,
        condition: ColumnElement[bool] | InstrumentedAttribute[bool],
        column: InstrumentedAttribute[T],
    ) -> list[T] | None: ...

    async def GetNesUsersOnCondition(
        self,
        condition: ColumnElement[bool] | InstrumentedAttribute[bool],
        column: InstrumentedAttribute[T] | None = None,
    ) -> list[NesUser] | list[T] | None:
        selection = NesUser
        if column is not None:
            CheckColumnBelongsToModel(column, NesUser)
            selection = getattr(NesUser, column.key)

        async with self.session() as session:
            result = await session.execute(select(selection).where(condition))

            return list(result.scalars().all())

    @overload
    async def GetNesUser(
        self,
        nes_id: int,
        column: None = None,
    ) -> NesUser | None: ...

    @overload
    async def GetNesUser(
        self,
        nes_id: int,
        column: InstrumentedAttribute[T],
    ) -> T | None: ...

    async def GetNesUser(
        self,
        nes_id: int,
        column: InstrumentedAttribute[T] | None = None,
    ) -> NesUser | T | None:
        result = await self.GetNesUsersOnCondition(
            condition=NesUser.nes_id == nes_id,
            column=column,
        )
        return result[0] if result else None

    # ----- Update -----

    async def DelistMissingNesUsers(self, fresh_ids: Iterable[int]) -> list[int]:
        """
        Mark every currently-listed row whose ``nes_id`` is NOT in `fresh_ids`
        as delisted (``listed = False``) and clear its ``mynes_text_hash`` so a
        future re-appearance forces a re-index. Returns the delisted nes_ids
        (the caller removes their OpenSearch documents).

        Safety: `fresh_ids` is consumed into a set by the caller; this method
        must never be called with an empty set (that would delist everyone),
        which the sync orchestrator guards against on fetch failure.
        """
        ids = list(fresh_ids)
        async with self.session() as session:
            result = await session.execute(
                update(NesUser)
                .where(NesUser.listed.is_(True), NesUser.nes_id.notin_(ids))
                .values(listed=False, mynes_text_hash=None)
                .returning(NesUser.nes_id)
            )
            delisted = [row[0] for row in result.all()]
            await session.commit()

        if delisted:
            logging.info(f"DelistMissingNesUsers: {len(delisted)} rows delisted.")
        return delisted

    # ----- Delete -----
