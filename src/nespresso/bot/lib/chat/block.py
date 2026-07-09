import logging
import time
from collections import defaultdict

from cachetools import TTLCache

from nespresso.bot.lib.chat.username import GetChatUserLoggingPart
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.searching.document import DeleteUserOpenSearch

# --- Spam guard: a burst of events from one chat_id -> temporary block ---
# Deliberately NOT a per-chat_id rate limit on writing to the message audit
# table — a flood would just keep getting silently dropped forever with no
# signal to the user. Instead: detect the burst, block the chat_id like an
# admin would (same CheckIfBlocked gate), and say so — once — so a legitimate
# user knows what happened and when they can come back.
_SPAM_WINDOW_SECONDS = 30
_SPAM_MESSAGE_THRESHOLD = 30
# Callbacks get a deliberately LENIENT threshold: normal Find pagination and
# like/dislike/hide taps are all callbacks, so a strict message-grade limit
# would trip on ordinary rapid browsing. This only exists to bound an outright
# flood (a script hammering inline buttons), not to police real navigation.
_CALLBACK_SPAM_THRESHOLD = 60
_SPAM_BLOCK_TTL_SECONDS = 60 * 60  # 1 hour

_recent_message_times: defaultdict[int, list[float]] = defaultdict(list)
_recent_callback_times: defaultdict[int, list[float]] = defaultdict(list)
_spam_blocked: TTLCache[int, bool] = TTLCache(maxsize=10000, ttl=_SPAM_BLOCK_TTL_SECONDS)


def IsSpamBlocked(chat_id: int) -> bool:
    return chat_id in _spam_blocked


def GetSpamBlockedChatIds() -> list[int]:
    """Currently spam-blocked chat_ids (auto-expire within the 1h TTL). Lets the
    admin blocking panel surface temporary spam-blocks, which live only in this
    in-memory cache and never touch the `TgUser.blocked` column."""
    return list(_spam_blocked.keys())


def ClearSpamBlock(chat_id: int) -> None:
    """Drop any in-memory spam-block for `chat_id`. Used by UnblockUser so an
    admin unblock frees a spam-blocked user immediately instead of leaving them
    stuck until the 1h TTL lapses."""
    _spam_blocked.pop(chat_id, None)


def _RegisterAndCheckSpam(
    times: list[float], chat_id: int, threshold: int
) -> bool:
    """
    Record one event timestamp in `times`, prune the window, and return True
    exactly once — the moment this event pushes `chat_id` over `threshold` —
    so the caller reacts (block + notify) a single time, not on every event
    while already blocked. Both message and callback guards share this logic
    and the same `_spam_blocked` set, differing only in their threshold/window.
    """
    now = time.monotonic()
    times.append(now)
    cutoff = now - _SPAM_WINDOW_SECONDS
    while times and times[0] < cutoff:
        times.pop(0)

    if len(times) > threshold and chat_id not in _spam_blocked:
        _spam_blocked[chat_id] = True
        times.clear()
        return True
    return False


def RegisterMessageAndCheckSpam(chat_id: int) -> bool:
    """Message-side spam guard (see `_RegisterAndCheckSpam`)."""
    return _RegisterAndCheckSpam(
        _recent_message_times[chat_id], chat_id, _SPAM_MESSAGE_THRESHOLD
    )


def RegisterCallbackAndCheckSpam(chat_id: int) -> bool:
    """Callback-side spam guard with a lenient threshold so ordinary pagination
    and reaction taps never trip it (see `_RegisterAndCheckSpam`)."""
    return _RegisterAndCheckSpam(
        _recent_callback_times[chat_id], chat_id, _CALLBACK_SPAM_THRESHOLD
    )


async def CheckIfBlocked(chat_id: int) -> bool:
    if IsSpamBlocked(chat_id):
        return True

    ctx = await GetUserContextService()
    blocked = await ctx.GetTgUser(chat_id=chat_id, column=TgUser.blocked)

    if blocked:
        part = await GetChatUserLoggingPart(chat_id)
        logging.info(f"{part} messages while being blocked.")

    return blocked or False


async def _UnverifyUser(chat_id: int) -> None:
    ctx = await GetUserContextService()

    await ctx.UpdateTgUser(
        chat_id=chat_id,
        column=TgUser.verified,
        value=False,
    )

    nes_id = await ctx.GetTgUser(chat_id=chat_id, column=TgUser.nes_id)
    if nes_id:
        await DeleteUserOpenSearch(nes_id)

    logging.info(f"chat_id={chat_id} unverified.")


async def BlockUser(chat_id: int) -> None:
    ctx = await GetUserContextService()

    await ctx.UpdateTgUser(
        chat_id=chat_id,
        column=TgUser.blocked,
        value=True,
    )

    await _UnverifyUser(chat_id)

    part = await GetChatUserLoggingPart(chat_id)
    logging.info(f"{part} blocked.")


async def UnblockUser(chat_id: int) -> None:
    ctx = await GetUserContextService()

    # Clear BOTH block sources: the DB flag AND the in-memory spam-block. Without
    # this an admin unblock of a spam-blocked user would report success yet leave
    # `CheckIfBlocked` (IsSpamBlocked OR db.blocked) still True until the 1h TTL.
    ClearSpamBlock(chat_id)

    await ctx.UpdateTgUser(
        chat_id=chat_id,
        column=TgUser.blocked,
        value=False,
    )

    # BlockUser force-unverifies as a side effect of revoking access (see
    # _UnverifyUser above); restore that status on unblock so the user isn't left
    # stuck behind a stale hub message whose Find/About/Settings buttons never
    # re-check `verified`. Only restore it for someone who had actually completed
    # registration before being blocked (nes_id set) — never verify an identity
    # that was never confirmed.
    nes_id = await ctx.GetTgUser(chat_id=chat_id, column=TgUser.nes_id)
    if nes_id:
        await ctx.UpdateTgUser(
            chat_id=chat_id,
            column=TgUser.verified,
            value=True,
        )

    part = await GetChatUserLoggingPart(chat_id)
    logging.info(f"{part} unblocked.")


async def UserBlockedBot(chat_id: int) -> None:
    await _UnverifyUser(chat_id)

    logging.info(f"chat_id={chat_id} blocked the bot.")
