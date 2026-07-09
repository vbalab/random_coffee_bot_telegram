import asyncio
import logging
import random
import time

from aiolimiter import AsyncLimiter
from sqlalchemy import select

from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import SendMessage
from nespresso.db.models.nes_user import NesUser
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import (
    GetUserContextService,
    UserContextService,
)
from nespresso.recsys.profile import Profile

_MIN_USERS_FOR_MATCHING = 2
_MIN_USERS_FOR_SECOND_ROUND = 3

# Serializes "Run Matching Now" so a double-tap or two admins racing each other
# can't both pass the eligibility read and each create their own independent
# round, silently sending everyone two conflicting sets of assignments.
_matching_lock = asyncio.Lock()

# A round is manual/occasional by design; refuse a new one this soon after the
# last, so repeated taps (or repeated admin action) can't blast the whole
# alumni base with matching DMs back-to-back.
_MIN_SECONDS_BETWEEN_ROUNDS = 10 * 60


class MatchingInProgressError(RuntimeError):
    """Another matching round is currently being created."""


class MatchingCooldownError(RuntimeError):
    """A round was created too recently; carries the remaining wait in seconds."""

    def __init__(self, remaining_seconds: int):
        self.remaining_seconds = remaining_seconds
        super().__init__(f"Matching on cooldown for {remaining_seconds}s more")


def _CreateDerangement(
    users: list[int],
    excluded: set[tuple[int, int]],
    max_attempts: int = 2000,
) -> list[int] | None:
    """
    Returns a permutation of `users` where:
      - users[i] != result[i]  (no self-match)
      - (users[i], result[i]) not in excluded  (no historically repeated pair)
    Returns None if no valid permutation found within max_attempts.
    """
    candidates = users.copy()
    for _ in range(max_attempts):
        random.shuffle(candidates)
        if all(
            users[i] != candidates[i] and (users[i], candidates[i]) not in excluded
            for i in range(len(users))
        ):
            return candidates
    return None


def MatchUsers(
    chat_ids: list[int],
    excluded_pairs: set[tuple[int, int]] | None = None,
) -> dict[int, list[int]]:
    """
    Asymmetric matching: each user gets 1 or 2 directed assignments.
    Returns dict[assigner_chat_id -> list[assigned_chat_ids]].
    """
    if excluded_pairs is None:
        excluded_pairs = set()

    n = len(chat_ids)
    if n < _MIN_USERS_FOR_MATCHING:
        return {cid: [] for cid in chat_ids}

    result: dict[int, list[int]] = {cid: [] for cid in chat_ids}

    # First assignment (everyone gets at least 1)
    first = _CreateDerangement(chat_ids, excluded_pairs)
    if first is None:
        # Fallback: ignore history exclusions
        first = _CreateDerangement(chat_ids, set())
    if first is None:
        logging.error("MatchUsers: could not create even a basic derangement")
        return result

    for i, uid in enumerate(chat_ids):
        result[uid].append(first[i])

    # Second assignment (if 3+ users)
    if n >= _MIN_USERS_FOR_SECOND_ROUND:
        # Exclude first-round pairs + historical pairs
        extended_excluded = excluded_pairs | {(chat_ids[i], first[i]) for i in range(n)}
        second = _CreateDerangement(chat_ids, extended_excluded)
        if second is None:
            # Fallback: only exclude the first round pairs (drop history)
            second = _CreateDerangement(
                chat_ids, {(chat_ids[i], first[i]) for i in range(n)}
            )
        if second is not None:
            for i, uid in enumerate(chat_ids):
                result[uid].append(second[i])

    return result


async def _ExcludedPairsWithBlocks(ctx: UserContextService) -> set[tuple[int, int]]:
    """
    History-based excluded pairs (last 2 rounds) PLUS every user's hidden-profile
    blocks. A block is stored directionally (A hid B), but a one-sided hide still
    makes a forced meeting awkward, so we exclude the pair BOTH ways — neither A→B
    nor B→A can be assigned.
    """
    excluded = await ctx.GetRecentExcludedPairs(last_n_rounds=2)
    for rater_chat_id, target_chat_id in await ctx.GetBlockedChatIdPairs():
        excluded.add((rater_chat_id, target_chat_id))
        excluded.add((target_chat_id, rater_chat_id))
    return excluded


async def _EligibleChatIds(ctx: UserContextService) -> list[int]:
    """
    Verified, non-blocked, non-opted-out users whose linked NES profile is still
    listed in the MyNES directory (delisted users opted out of discoverability).
    The `IN (listed nes_ids)` subquery also implies nes_id IS NOT NULL.
    """
    listed_nes_ids = select(NesUser.nes_id).where(NesUser.listed.is_(True))
    return await ctx.GetTgUsersOnCondition(
        condition=TgUser.verified
        & ~TgUser.blocked
        & ~TgUser.matching_paused
        & TgUser.nes_id.in_(listed_nes_ids),
        column=TgUser.chat_id,
    )


async def EligibleMatchingChatIds() -> list[int]:
    """
    Public accessor for the matching-eligible pool, so the admin statistics
    report the SAME set the algorithm actually matches over (single source of
    truth — a divergent copy is exactly how the 'eligible' count drifted before).
    """
    ctx = await GetUserContextService()
    return await _EligibleChatIds(ctx)


async def CreateMatching(triggered_by: int) -> dict[int, list[int]]:
    """
    Fetches eligible users, runs asymmetric matching, saves to DB.
    Returns dict[assigner_chat_id -> list[assigned_chat_ids]].

    Guarded against a double-tap / two-admins-at-once race two ways: a hard
    concurrency lock (raises MatchingInProgressError if a round is already being
    created) and a cooldown since the last round (raises MatchingCooldownError).
    """
    if _matching_lock.locked():
        raise MatchingInProgressError()

    async with _matching_lock:
        ctx = await GetUserContextService()

        last_round = await ctx.GetLastRound()
        if last_round is not None:
            elapsed = time.time() - last_round.created_at.timestamp()
            if elapsed < _MIN_SECONDS_BETWEEN_ROUNDS:
                raise MatchingCooldownError(
                    remaining_seconds=int(_MIN_SECONDS_BETWEEN_ROUNDS - elapsed)
                )

        all_users = await _EligibleChatIds(ctx)
        excluded = await _ExcludedPairsWithBlocks(ctx)
        # CPU-bound (rejection-sampling up to 2000 shuffles); off the event loop
        # so it can't stall every other user's request while it runs.
        assignments_map = await asyncio.to_thread(MatchUsers, all_users, excluded)

        # Flatten to list of (assigner, assigned) tuples
        flat: list[tuple[int, int]] = [
            (assigner, assigned)
            for assigner, assigned_list in assignments_map.items()
            for assigned in assigned_list
        ]

        if flat:
            round_, _assignments = await ctx.CreateRoundWithAssignments(
                triggered_by=triggered_by, assignments=flat
            )
            logging.info(
                f"MatchingRound id={round_.id}: {len(flat)} assignments for {len(all_users)} users"
            )

        return assignments_map


async def DemoMatching() -> dict[int, list[int]]:
    """
    Dry-run matching: compute assignments over the SAME eligible pool + history
    exclusions as a real round, but do NOT persist a round and do NOT notify
    anyone. For admin preview/export only.
    """
    ctx = await GetUserContextService()
    all_users = await _EligibleChatIds(ctx)
    excluded = await _ExcludedPairsWithBlocks(ctx)
    return await asyncio.to_thread(MatchUsers, all_users, excluded)


async def SendMatchingInfo(assignments_map: dict[int, list[int]]) -> None:
    """
    DM each matched user an explanatory greeting followed by ONE message per
    assigned profile (so a user gets up to 3 messages: greeting + 2 profiles)
    instead of a single blob. Per user the greeting is sent before the profiles
    (sequential); different users are sent concurrently under one 30 msg/s limit.
    """
    ctx = await GetUserContextService()
    limiter = AsyncLimiter(max_rate=30, time_period=1)

    async def _SendToUser(assigner_chat_id: int, assigned_list: list[int]) -> None:
        # Isolate each recipient: one user's failure (a TelegramRetryAfter, a
        # profile that can't be built, etc.) must not abort the whole gather and
        # fail the pipeline — the round is already committed and other users
        # were/will be notified, and failing here would also arm the cooldown
        # against a retry. Log and move on.
        try:
            lang = await GetUserLanguage(assigner_chat_id)

            # Ordered texts: greeting first, then one message per assigned profile.
            texts: list[str] = [t(lang, "matching.intro", count=len(assigned_list))]
            for assigned_chat_id in assigned_list:
                assigned_nes_id = await ctx.GetTgUser(
                    chat_id=assigned_chat_id, column=TgUser.nes_id
                )
                if assigned_nes_id is None:
                    logging.error(
                        f"chat_id={assigned_chat_id} has no nes_id during SendMatchingInfo"
                    )
                    continue
                profile = await Profile.FromNesId(assigned_nes_id)
                texts.append(profile.DescribeProfile())

            # Sequential send → the greeting reliably arrives before the profiles.
            # texts[0] is the plain greeting; texts[1:] are HTML profile cards.
            for i, text in enumerate(texts):
                async with limiter:
                    await SendMessage(
                        chat_id=assigner_chat_id,
                        text=text,
                        parse_mode="HTML" if i > 0 else None,
                    )
        except Exception:
            logging.exception(
                f"SendMatchingInfo: failed to notify chat_id={assigner_chat_id}"
            )

    await asyncio.gather(
        *(
            _SendToUser(assigner_chat_id, assigned_list)
            for assigner_chat_id, assigned_list in assignments_map.items()
            if assigned_list
        )
    )


async def MatchingPipeline(triggered_by: int) -> int:
    """
    Runs the full matching pipeline. Returns number of users matched.
    """
    logging.info("MatchingPipeline: creating assignments")
    assignments_map = await CreateMatching(triggered_by=triggered_by)
    participants = sum(1 for v in assignments_map.values() if v)
    logging.info(f"MatchingPipeline: sending info to {participants} users")
    await SendMatchingInfo(assignments_map)
    logging.info("MatchingPipeline: done")
    return participants
