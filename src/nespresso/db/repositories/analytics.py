from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nespresso.db.models.match import MatchAssignment, MatchRound
from nespresso.db.models.message import Message, MessageSide
from nespresso.db.models.nes_user import NesUser
from nespresso.db.models.tg_user import TgUser


class AnalyticsRepository:
    def __init__(self, session: async_sessionmaker[AsyncSession]):
        self.session = session

    async def GetTgUserStats(self) -> dict[str, int]:
        now = datetime.now(UTC)
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        async with self.session() as session:
            total = await session.scalar(select(func.count()).select_from(TgUser)) or 0
            verified = (
                await session.scalar(
                    select(func.count()).where(TgUser.verified.is_(True))
                )
                or 0
            )
            blocked = (
                await session.scalar(
                    select(func.count()).where(TgUser.blocked.is_(True))
                )
                or 0
            )
            lang_en = (
                await session.scalar(
                    select(func.count()).where(TgUser.language == "en")
                )
                or 0
            )
            lang_ru = (
                await session.scalar(
                    select(func.count()).where(TgUser.language == "ru")
                )
                or 0
            )
            with_username = (
                await session.scalar(
                    select(func.count()).where(TgUser.username.isnot(None))
                )
                or 0
            )
            with_about = (
                await session.scalar(
                    select(func.count()).where(TgUser.about.isnot(None))
                )
                or 0
            )
            new_week = (
                await session.scalar(
                    select(func.count()).where(TgUser.created_at >= week_ago)
                )
                or 0
            )
            new_month = (
                await session.scalar(
                    select(func.count()).where(TgUser.created_at >= month_ago)
                )
                or 0
            )

        return {
            "total": total,
            "verified": verified,
            "unverified": total - verified,
            "blocked": blocked,
            "lang_en": lang_en,
            "lang_ru": lang_ru,
            "with_username": with_username,
            "with_about": with_about,
            "new_week": new_week,
            "new_month": new_month,
        }

    async def GetNesUserStats(
        self,
    ) -> dict[str, int | list[tuple[str, int]]]:
        async with self.session() as session:
            result = await session.execute(select(NesUser))
            users = list(result.scalars().all())

        countries: Counter[str] = Counter()
        cities: Counter[str] = Counter()
        programs: Counter[str] = Counter()
        industries: Counter[str] = Counter()
        professional: Counter[str] = Counter()

        for u in users:
            if u.country:
                countries[u.country] += 1
            if u.city:
                cities[u.city] += 1
            if u.program:
                programs[u.program] += 1
            if u.industry_expertise:
                industries.update(u.industry_expertise)
            if u.professional_expertise:
                professional.update(u.professional_expertise)

        return {
            "total": len(users),
            "top_countries": countries.most_common(5),
            "top_cities": cities.most_common(5),
            "top_programs": programs.most_common(5),
            "top_industries": industries.most_common(5),
            "top_professional": professional.most_common(5),
        }

    async def GetActivityStats(
        self,
    ) -> dict[str, int | list[tuple[int, int]]]:
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)

        async with self.session() as session:
            total = await session.scalar(select(func.count()).select_from(Message)) or 0
            bot_msgs = (
                await session.scalar(
                    select(func.count()).where(Message.side == MessageSide.Bot)
                )
                or 0
            )
            user_msgs = (
                await session.scalar(
                    select(func.count()).where(Message.side == MessageSide.User)
                )
                or 0
            )
            today = (
                await session.scalar(
                    select(func.count()).where(Message.time >= today_start)
                )
                or 0
            )
            this_week = (
                await session.scalar(
                    select(func.count()).where(Message.time >= week_ago)
                )
                or 0
            )
            top_result = await session.execute(
                select(Message.chat_id, func.count().label("cnt"))
                .where(Message.side == MessageSide.User)
                .group_by(Message.chat_id)
                .order_by(func.count().desc())
                .limit(5)
            )
            top_users = [(int(r.chat_id), int(r.cnt)) for r in top_result]

        return {
            "total": total,
            "bot": bot_msgs,
            "user": user_msgs,
            "today": today,
            "week": this_week,
            "top_users": top_users,
        }

    async def GetAllTgUsers(self) -> list[TgUser]:
        async with self.session() as session:
            result = await session.execute(select(TgUser).order_by(TgUser.created_at))
            return list(result.scalars().all())

    async def GetAllNesUsers(self) -> list[NesUser]:
        async with self.session() as session:
            result = await session.execute(select(NesUser).order_by(NesUser.nes_id))
            return list(result.scalars().all())

    async def GetAllMessages(self) -> list[Message]:
        async with self.session() as session:
            result = await session.execute(select(Message).order_by(Message.time))
            return list(result.scalars().all())

    async def GetMatchingStats(self) -> dict[str, int | str]:
        async with self.session() as session:
            opted_out = (
                await session.scalar(
                    select(func.count()).where(TgUser.matching_paused.is_(True))
                )
                or 0
            )
            total_rounds = (
                await session.scalar(select(func.count()).select_from(MatchRound)) or 0
            )
            # Order by id (monotonic), matching MatchRepository.GetLastRound —
            # created_at can tie at second resolution, so the two "last round"
            # definitions must not disagree.
            last_round = await session.scalar(
                select(MatchRound).order_by(MatchRound.id.desc()).limit(1)
            )
            last_round_date: str = (
                last_round.created_at.strftime("%Y-%m-%d %H:%M UTC")
                if last_round is not None
                else "—"
            )
            last_round_assignments = 0
            if last_round is not None:
                last_round_assignments = (
                    await session.scalar(
                        select(func.count()).where(
                            MatchAssignment.round_id == last_round.id
                        )
                    )
                    or 0
                )

        return {
            "opted_out": opted_out,
            "total_rounds": total_rounds,
            "last_round_date": last_round_date,
            "last_round_assignments": last_round_assignments,
        }
