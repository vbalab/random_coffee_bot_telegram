import logging

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import func

from nespresso.db.models.profile_reaction import ProfileReaction
from nespresso.db.models.tg_user import TgUser


class ProfileReactionRepository:
    """
    Pure DB access for per-user profile reactions / hidden profiles. All writes
    are atomic upserts keyed on the (rater_chat_id, target_nes_id) unique
    constraint, so a double-tap or a redelivered callback can never leave two
    contradictory rows for the same pair.
    """

    def __init__(self, session: async_sessionmaker[AsyncSession]):
        self.session = session

    # ----- Write -----

    async def SetReaction(
        self, rater_chat_id: int, target_nes_id: int, reaction: str | None
    ) -> None:
        """
        Record (or clear, when reaction is None) the searcher's like/dislike on a
        result profile. Leaves the `blocked` column untouched — rating and hiding
        are independent.
        """
        async with self.session() as session:
            stmt = insert(ProfileReaction).values(
                rater_chat_id=rater_chat_id,
                target_nes_id=target_nes_id,
                reaction=reaction,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    ProfileReaction.rater_chat_id,
                    ProfileReaction.target_nes_id,
                ],
                set_={"reaction": stmt.excluded.reaction, "updated_at": func.now()},
            )
            await session.execute(stmt)
            await session.commit()
            logging.info(
                f"ProfileReaction: rater={rater_chat_id} target_nes_id={target_nes_id} "
                f"reaction={reaction}"
            )

    async def SetBlocked(
        self, rater_chat_id: int, target_nes_id: int, blocked: bool
    ) -> None:
        """
        Hide (blocked=True) or un-hide (blocked=False) a profile for this rater.
        Leaves the `reaction` column untouched.
        """
        async with self.session() as session:
            stmt = insert(ProfileReaction).values(
                rater_chat_id=rater_chat_id,
                target_nes_id=target_nes_id,
                blocked=blocked,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    ProfileReaction.rater_chat_id,
                    ProfileReaction.target_nes_id,
                ],
                set_={"blocked": stmt.excluded.blocked, "updated_at": func.now()},
            )
            await session.execute(stmt)
            await session.commit()
            logging.info(
                f"ProfileReaction: rater={rater_chat_id} target_nes_id={target_nes_id} "
                f"blocked={blocked}"
            )

    # ----- Delete -----

    async def DeleteForUser(
        self, rater_chat_id: int, target_nes_id: int | None = None
    ) -> None:
        """
        Remove every reaction row that concerns this user — both the ones they
        authored (rater_chat_id) and, when their nes_id is known, the ones OTHER
        users left ON their profile (target_nes_id). Used by account deletion so
        no reaction outlives the deleted user in either direction.
        """
        condition = ProfileReaction.rater_chat_id == rater_chat_id
        if target_nes_id is not None:
            condition = or_(condition, ProfileReaction.target_nes_id == target_nes_id)

        async with self.session() as session:
            result = await session.execute(delete(ProfileReaction).where(condition))
            await session.commit()
            logging.info(
                f"ProfileReaction: deleted {result.rowcount} rows for "
                f"rater={rater_chat_id} target_nes_id={target_nes_id}"
            )

    # ----- Read -----

    async def GetReaction(
        self, rater_chat_id: int, target_nes_id: int
    ) -> str | None:
        """The rater's current like/dislike on this profile (None if no vote)."""
        async with self.session() as session:
            result = await session.execute(
                select(ProfileReaction.reaction).where(
                    ProfileReaction.rater_chat_id == rater_chat_id,
                    ProfileReaction.target_nes_id == target_nes_id,
                )
            )
            return result.scalar_one_or_none()

    async def GetBlockedNesIds(self, rater_chat_id: int) -> list[int]:
        """
        Every nes_id this rater has hidden, most-recently-hidden first (stable
        order so the Settings manager can index into it by position). Used both
        to exclude blocked profiles from Find and to render the manager UI.
        """
        async with self.session() as session:
            result = await session.execute(
                select(ProfileReaction.target_nes_id)
                .where(
                    ProfileReaction.rater_chat_id == rater_chat_id,
                    ProfileReaction.blocked.is_(True),
                )
                .order_by(ProfileReaction.id.desc())
            )
            return [int(nes_id) for (nes_id,) in result.all()]

    async def GetReactionsForUser(
        self, rater_chat_id: int
    ) -> list[ProfileReaction]:
        """Every reaction/hide row this user authored, newest first. Used by the
        user's own self-service data export (GDPR)."""
        async with self.session() as session:
            result = await session.execute(
                select(ProfileReaction)
                .where(ProfileReaction.rater_chat_id == rater_chat_id)
                .order_by(ProfileReaction.id.desc())
            )
            return list(result.scalars().all())

    async def GetBlockedChatIdPairs(self) -> set[tuple[int, int]]:
        """
        Every active profile-block resolved to a (rater_chat_id, target_chat_id)
        pair by joining the hidden target_nes_id to its VERIFIED TgUser owner.

        Used by matching: the caller adds BOTH directions to the excluded set so
        a one-sided hide still keeps the two users from ever being paired. Blocks
        whose target has no verified owner are simply absent (that target isn't
        matchable anyway).
        """
        async with self.session() as session:
            result = await session.execute(
                select(ProfileReaction.rater_chat_id, TgUser.chat_id)
                .join(TgUser, TgUser.nes_id == ProfileReaction.target_nes_id)
                .where(
                    ProfileReaction.blocked.is_(True),
                    TgUser.verified.is_(True),
                )
            )
            return {(int(rater), int(target)) for rater, target in result.all()}
