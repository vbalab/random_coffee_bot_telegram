import logging
import random

from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import PersonalMsg, SendMessagesToGroup
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.profile import Profile

_MIN_USERS_FOR_MATCHING = 2
_MIN_USERS_FOR_SECOND_ROUND = 3


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


async def CreateMatching(triggered_by: int) -> dict[int, list[int]]:
    """
    Fetches eligible users, runs asymmetric matching, saves to DB.
    Returns dict[assigner_chat_id -> list[assigned_chat_ids]].
    """
    ctx = await GetUserContextService()

    # Only verified, non-blocked, non-opted-out users with a linked NES profile
    all_users = await ctx.GetTgUsersOnCondition(
        condition=TgUser.verified
        & ~TgUser.blocked
        & ~TgUser.matching_paused
        & TgUser.nes_id.isnot(None),
        column=TgUser.chat_id,
    )

    excluded = await ctx.GetRecentExcludedPairs(last_n_rounds=2)
    assignments_map = MatchUsers(all_users, excluded)

    # Flatten to list of (assigner, assigned) tuples
    flat: list[tuple[int, int]] = [
        (assigner, assigned)
        for assigner, assigned_list in assignments_map.items()
        for assigned in assigned_list
    ]

    if flat:
        round_ = await ctx.CreateRound(triggered_by=triggered_by)
        await ctx.CreateAssignments(round_id=round_.id, assignments=flat)
        logging.info(
            f"MatchingRound id={round_.id}: {len(flat)} assignments for {len(all_users)} users"
        )

    return assignments_map


async def SendMatchingInfo(assignments_map: dict[int, list[int]]) -> None:
    ctx = await GetUserContextService()
    messages: list[PersonalMsg] = []

    for assigner_chat_id, assigned_list in assignments_map.items():
        lang = await GetUserLanguage(assigner_chat_id)
        count = len(assigned_list)
        if count == 0:
            continue

        intro = t(lang, "matching.intro", count=count)
        parts = [intro]

        for assigned_chat_id in assigned_list:
            assigned_nes_id = await ctx.GetTgUser(
                chat_id=assigned_chat_id,
                column=TgUser.nes_id,
            )
            if assigned_nes_id is None:
                logging.error(
                    f"chat_id={assigned_chat_id} has no nes_id during SendMatchingInfo"
                )
                continue

            profile = await Profile.FromNesId(assigned_nes_id)
            parts.append(profile.DescribeProfile())

        text = "\n\n---\n\n".join(parts)
        messages.append(PersonalMsg(chat_id=assigner_chat_id, text=text))

    await SendMessagesToGroup(messages)


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
