import asyncio
import logging
import time
from typing import Any

from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types.error_event import ErrorEvent

from nespresso.bot.lib.message.io import ContextIO, SendDocument, SendMessage
from nespresso.bot.lifecycle.creator import BOT_ID, dp
from nespresso.core.configs.admin_store import GetAdminIds
from nespresso.core.configs.paths import PATH_BOT_LOGS

# At most one "full log dump to every admin" per this window. Without it, any
# trivially-reproducible uncaught exception (a user just mashing a button) would
# re-send the whole bot.log to every admin on every single occurrence.
_NOTIFY_INTERVAL_SECONDS = 300.0
_last_notify_monotonic: float | None = None
_suppressed_since_last: int = 0


async def NotifyAdminsOfError(exc: BaseException) -> None:
    global _last_notify_monotonic, _suppressed_since_last

    now = time.monotonic()
    if (
        _last_notify_monotonic is not None
        and now - _last_notify_monotonic < _NOTIFY_INTERVAL_SECONDS
    ):
        _suppressed_since_last += 1
        return

    suppressed = _suppressed_since_last
    _suppressed_since_last = 0
    _last_notify_monotonic = now

    caption = f"🚨 Error: {exc}.\n\nCheck logs for details."
    if suppressed:
        window_min = int(_NOTIFY_INTERVAL_SECONDS // 60)
        caption += f"\n\n({suppressed} more error(s) suppressed in the last {window_min} min.)"

    for admin in await GetAdminIds():
        await SendDocument(
            chat_id=admin,
            document=types.FSInputFile(PATH_BOT_LOGS),
            caption=caption,
        )


def AsyncioExceptionHandler(
    loop: asyncio.AbstractEventLoop, context: dict[str, Any]
) -> None:
    exc = context.get("exception") or RuntimeError(context.get("message"))

    if not loop.is_closed():
        loop.create_task(NotifyAdminsOfError(exc))

    loop.default_exception_handler(context)  # default: do own handling


_ERROR_TEXT = (
    "Oops, something went wrong.\nWe've logged the error.\n\n"
    "If the issue isn't resolved soon, feel free to reach out to @vbalab"
)


@dp.error()
async def AiogramExceptionHandler(event: ErrorEvent) -> bool:
    logging.exception(
        f"Cause exception while processing update:\n{event.model_dump()}",
        exc_info=event.exception,
    )

    chat_id: int | None = None
    user_id: int | None = None

    if event.update.message:
        chat_id = event.update.message.chat.id
        if event.update.message.from_user:
            user_id = event.update.message.from_user.id
    elif event.update.callback_query:
        callback_query = event.update.callback_query
        user_id = callback_query.from_user.id
        if callback_query.message:
            chat_id = callback_query.message.chat.id
        else:
            chat_id = user_id

    if chat_id is not None and user_id is not None:
        # Clear FSM state for this user — an error mid-flow shouldn't leave them
        # stuck in a state that can no longer make progress.
        key = StorageKey(bot_id=BOT_ID, chat_id=chat_id, user_id=user_id)
        context = FSMContext(storage=dp.storage, key=key)
        await context.clear()

    if event.update.callback_query:
        # A callback needs `.answer()`, not a new message, or the tapping
        # client is left with the button stuck in its loading state.
        try:
            await event.update.callback_query.answer(_ERROR_TEXT, show_alert=True)
        except Exception:
            logging.debug("Failed to answer callback after error", exc_info=True)
    elif chat_id is not None:
        await SendMessage(chat_id, text=_ERROR_TEXT, context=ContextIO.Error)

    await NotifyAdminsOfError(event.exception)

    return True


def SetExceptionHandlers() -> None:
    asyncio.get_running_loop().set_exception_handler(AsyncioExceptionHandler)
