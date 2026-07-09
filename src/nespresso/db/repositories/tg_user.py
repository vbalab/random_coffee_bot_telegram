import logging
from collections.abc import Sequence
from typing import TypeVar, overload

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from nespresso.core.configs.admin_ids import DEFAULT_ADMIN_IDS
from nespresso.db.models.tg_user import TgUser
from nespresso.db.repositories.checking import (
    CheckColumnBelongsToModel,
    CheckOnlyOneArgProvided,
)

T = TypeVar("T")

# asyncpg caps a statement at 32767 bound params; ids-only IN scans are tiny, so
# a generous chunk keeps round-trips down.
_SELECT_CHUNK = 1000


class TgUserRepository:
    def __init__(self, session: async_sessionmaker[AsyncSession]):
        self.session = session

    # ----- Create -----

    async def CreateTgUser(self, chat_id: int) -> None:
        async with self.session() as session:
            try:
                session.add(
                    TgUser(chat_id=chat_id, is_admin=chat_id in DEFAULT_ADMIN_IDS)
                )

                await session.commit()
                logging.info(f"TgUser(chat_id={chat_id}) created successfully.")

            except IntegrityError:
                # Concurrent registration is expected — middleware can race
                # with itself if multiple updates arrive simultaneously.
                await session.rollback()
                logging.debug(
                    f"TgUser(chat_id={chat_id}) already exists; skipping create."
                )

    # ----- Read -----

    @overload
    async def GetTgUsersOnCondition(
        self,
        condition: ColumnElement[bool] | InstrumentedAttribute[bool],
        column: None = None,
    ) -> list[TgUser]: ...

    @overload
    async def GetTgUsersOnCondition(
        self,
        condition: ColumnElement[bool] | InstrumentedAttribute[bool],
        column: InstrumentedAttribute[T],
    ) -> list[T]: ...

    async def GetTgUsersOnCondition(
        self,
        condition: ColumnElement[bool] | InstrumentedAttribute[bool],
        column: InstrumentedAttribute[T] | None = None,
    ) -> list[TgUser] | list[T]:
        selection = TgUser
        if column is not None:
            CheckColumnBelongsToModel(column, TgUser)
            selection = getattr(TgUser, column.key)

        async with self.session() as session:
            result = await session.execute(select(selection).where(condition))

            return list(result.scalars().all())

    @overload
    async def GetTgUser(
        self,
        chat_id: int,
        column: None = None,
    ) -> TgUser | None: ...

    @overload
    async def GetTgUser(
        self,
        chat_id: int,
        column: InstrumentedAttribute[T],
    ) -> T | None: ...

    async def GetTgUser(
        self,
        chat_id: int,
        column: InstrumentedAttribute[T] | None = None,
    ) -> TgUser | T | None:
        result = await self.GetTgUsersOnCondition(
            condition=TgUser.chat_id == chat_id,
            column=column,
        )
        return result[0] if result else None

    async def GetChatIdBy(
        self,
        chat_id: int | None = None,
        tg_username: str | None = None,
        nes_id: int | None = None,
        nes_email: str | None = None,
    ) -> int | None:
        CheckOnlyOneArgProvided(
            chat_id=chat_id,
            tg_username=tg_username,
            nes_id=nes_id,
            nes_email=nes_email,
        )

        if chat_id is not None:
            condition = TgUser.chat_id == chat_id
        elif tg_username is not None:
            condition = TgUser.username == tg_username
        elif nes_id is not None:
            condition = TgUser.nes_id == nes_id
        elif nes_email is not None:
            condition = TgUser.nes_email == nes_email

        # A given nes_id / nes_email / username can transiently be shared by more
        # than one row (an unverified re-registration attempt, a mid-flow race).
        # Resolve deterministically and prefer the VERIFIED owner, so callers
        # like Profile.FromNesId never surface a stray unverified row's data.
        async with self.session() as session:
            result = await session.execute(
                select(TgUser.chat_id)
                .where(condition)
                .order_by(TgUser.verified.desc(), TgUser.chat_id)
                .limit(1)
            )
            row = result.scalar_one_or_none()
        return int(row) if row is not None else None

    async def GetAboutByNesIds(self, nes_ids: Sequence[int]) -> dict[int, str]:
        """
        Map ``nes_id -> non-empty TgUser.about`` for the given ids. Used by the
        directory sync to fold each user's bio into the unified profile text and
        change hash.

        Deterministic on collisions: if two chat_ids ever bound the same nes_id,
        ``ORDER BY chat_id`` makes the winning value stable across syncs, so the
        folded-bio hash cannot flap and cause spurious re-embeds.
        """
        ids = list(nes_ids)
        out: dict[int, str] = {}
        async with self.session() as session:
            for start in range(0, len(ids), _SELECT_CHUNK):
                chunk = ids[start : start + _SELECT_CHUNK]
                result = await session.execute(
                    select(TgUser.nes_id, TgUser.about)
                    .where(TgUser.nes_id.in_(chunk), TgUser.about.isnot(None))
                    .order_by(TgUser.chat_id)
                )
                for nes_id, about in result.all():
                    if nes_id is not None and about and about.strip():
                        out[int(nes_id)] = about
        return out

    # ----- Update -----

    async def UpdateTgUser(
        self,
        chat_id: int,
        column: InstrumentedAttribute[T],
        value: T,
    ) -> None:
        CheckColumnBelongsToModel(column, TgUser)

        async with self.session() as session:
            try:
                result = await session.execute(
                    update(TgUser)
                    .where(TgUser.chat_id == chat_id)
                    .values({column.key: value})
                )

                if result.rowcount == 0:
                    raise NoResultFound()

                await session.commit()
                logging.info(
                    f"TgUser(chat_id={chat_id}) updated: '{column}={value}' successfully."
                )

            except NoResultFound:
                logging.error(
                    f"Failed to update: '{column}={value}'. No TgUser(chat_id={chat_id}) found."
                )
                raise

    # ----- Delete -----
