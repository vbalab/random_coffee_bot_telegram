import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nespresso.db.models.match import MatchAssignment, MatchFeedback, MatchRound


class MatchRepository:
    def __init__(self, session: async_sessionmaker[AsyncSession]):
        self.session = session

    # ----- MatchRound -----

    async def CreateRound(self, triggered_by: int) -> MatchRound:
        async with self.session() as session:
            round_ = MatchRound(triggered_by=triggered_by)
            session.add(round_)
            await session.commit()
            await session.refresh(round_)
            logging.info(f"MatchRound(id={round_.id}) created by chat_id={triggered_by}")
            return round_

    async def GetLastRound(self) -> MatchRound | None:
        async with self.session() as session:
            result = await session.execute(
                select(MatchRound).order_by(MatchRound.id.desc()).limit(1)
            )
            return result.scalar_one_or_none()

    # ----- MatchAssignment -----

    async def CreateAssignments(
        self, round_id: int, assignments: list[tuple[int, int]]
    ) -> list[MatchAssignment]:
        """assignments: list of (assigner_chat_id, assigned_chat_id)"""
        async with self.session() as session:
            objs = [
                MatchAssignment(
                    round_id=round_id,
                    assigner_chat_id=assigner,
                    assigned_chat_id=assigned,
                )
                for assigner, assigned in assignments
            ]
            session.add_all(objs)
            await session.commit()
            for obj in objs:
                await session.refresh(obj)
            logging.info(
                f"Created {len(objs)} MatchAssignments for round_id={round_id}"
            )
            return objs

    async def GetAssignmentsByRound(self, round_id: int) -> list[MatchAssignment]:
        async with self.session() as session:
            result = await session.execute(
                select(MatchAssignment).where(MatchAssignment.round_id == round_id)
            )
            return list(result.scalars().all())

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
        async with self.session() as session:
            # Check if feedback already exists
            existing = await session.execute(
                select(MatchFeedback).where(
                    MatchFeedback.assignment_id == assignment_id
                )
            )
            obj = existing.scalar_one_or_none()
            if obj:
                obj.response = response
            else:
                obj = MatchFeedback(assignment_id=assignment_id, response=response)
                session.add(obj)
            await session.commit()
            logging.info(
                f"MatchFeedback upserted: assignment_id={assignment_id}, response={response}"
            )
