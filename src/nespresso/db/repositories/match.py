import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nespresso.db.models.match import MatchAssignment, MatchFeedback, MatchRound


class MatchRepository:
    def __init__(self, session: async_sessionmaker[AsyncSession]):
        self.session = session

    # ----- MatchRound -----

    async def CreateRoundWithAssignments(
        self, triggered_by: int, assignments: list[tuple[int, int]]
    ) -> tuple[MatchRound, list[MatchAssignment]]:
        """
        Create the round AND its assignments in ONE transaction, so a failure
        partway through can never leave an orphan round with zero assignments
        (which CreateRound + a separate CreateAssignments call could).
        """
        async with self.session() as session:
            round_ = MatchRound(triggered_by=triggered_by)
            session.add(round_)
            await session.flush()  # assigns round_.id without committing yet

            objs = [
                MatchAssignment(
                    round_id=round_.id,
                    assigner_chat_id=assigner,
                    assigned_chat_id=assigned,
                )
                for assigner, assigned in assignments
            ]
            session.add_all(objs)
            await session.commit()
            await session.refresh(round_)
            for obj in objs:
                await session.refresh(obj)
            logging.info(
                f"MatchRound(id={round_.id}) created by chat_id={triggered_by} "
                f"with {len(objs)} assignments"
            )
            return round_, objs

    async def GetLastRound(self) -> MatchRound | None:
        async with self.session() as session:
            result = await session.execute(
                select(MatchRound).order_by(MatchRound.id.desc()).limit(1)
            )
            return result.scalar_one_or_none()

    async def MarkFeedbackSent(self, round_id: int) -> None:
        async with self.session() as session:
            await session.execute(
                update(MatchRound)
                .where(MatchRound.id == round_id)
                .values(feedback_sent_at=datetime.now(UTC))
            )
            await session.commit()

    # ----- MatchAssignment -----

    async def GetAssignmentsByRound(self, round_id: int) -> list[MatchAssignment]:
        async with self.session() as session:
            result = await session.execute(
                select(MatchAssignment).where(MatchAssignment.round_id == round_id)
            )
            return list(result.scalars().all())

    async def GetAssignment(self, assignment_id: int) -> MatchAssignment | None:
        async with self.session() as session:
            result = await session.execute(
                select(MatchAssignment).where(MatchAssignment.id == assignment_id)
            )
            return result.scalar_one_or_none()

    async def GetRecentExcludedPairs(
        self, last_n_rounds: int = 2
    ) -> set[tuple[int, int]]:
        """Return (assigner, assigned) pairs from the last N rounds."""
        async with self.session() as session:
            rounds_result = await session.execute(
                select(MatchRound.id)
                .order_by(MatchRound.id.desc())
                .limit(last_n_rounds)
            )
            round_ids = [r for (r,) in rounds_result.all()]
            if not round_ids:
                return set()

            assignments_result = await session.execute(
                select(
                    MatchAssignment.assigner_chat_id, MatchAssignment.assigned_chat_id
                ).where(MatchAssignment.round_id.in_(round_ids))
            )
            return {(a, b) for a, b in assignments_result.all()}

    # ----- MatchFeedback -----

    async def UpsertFeedback(self, assignment_id: int, response: str) -> None:
        """
        Atomic upsert (INSERT ... ON CONFLICT), backed by the unique index on
        MatchFeedback.assignment_id — a select-then-branch here would let two
        concurrent calls (double-tap, redelivered callback) both see "no row yet"
        and both insert, leaving duplicate/contradictory feedback for one
        assignment.
        """
        async with self.session() as session:
            stmt = insert(MatchFeedback).values(
                assignment_id=assignment_id, response=response
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[MatchFeedback.assignment_id],
                set_={"response": stmt.excluded.response},
            )
            await session.execute(stmt)
            await session.commit()
            logging.info(
                f"MatchFeedback upserted: assignment_id={assignment_id}, response={response}"
            )
