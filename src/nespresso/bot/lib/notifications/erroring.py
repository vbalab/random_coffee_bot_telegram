import asyncio
import logging
from typing import Any

from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types.error_event import ErrorEvent

from nespresso.bot.lib.message.io import ContextIO, SendDocument, SendMessage
from nespresso.bot.lifecycle.creator import BOT_ID, dp
from nespresso.core.configs.admin_store import admin_store
from nespresso.core.configs.paths import PATH_BOT_LOGS


async def NotifyAdminsOfError(exc: BaseException) -> None:
    for admin in admin_store.GetIds():
        await SendDocument(
            chat_id=admin,
            document=types.FSInputFile(PATH_BOT_LOGS),
            caption=f"🚨 Error: {exc}.\n\nCheck logs for details.",
        )


def AsyncioExceptionHandler(
    loop: asyncio.AbstractEventLoop, context: dict[str, Any]
) -> None:
    exc = context.get("exception") or RuntimeError(context.get("message"))

    if not loop.is_closed():
        loop.create_task(NotifyAdminsOfError(exc))

    loop.default_exception_handler(context)  # default: do own handling


@dp.error()
async def AiogramExceptionHandler(event: ErrorEvent) -> bool:
    logging.exception(
        f"Cause exception while processing update:\n{event.model_dump()}",
        exc_info=event.exception,
    )

    if event.update.message:
        chat_id = event.update.message.chat.id

        # Clear FSM state for this user
        if event.update.message.from_user:
            user_id = event.update.message.from_user.id

            key = StorageKey(bot_id=BOT_ID, chat_id=chat_id, user_id=user_id)
            context = FSMContext(storage=dp.storage, key=key)

            await context.clear()

        await SendMessage(
            chat_id,
            text="Oops, something went wrong.\nWe've logged the error.\n\nIf the issue isn't resolved soon, feel free to reach out to @vbalab",
            context=ContextIO.Error,
        )

    await NotifyAdminsOfError(event.exception)

    return True


def SetExceptionHandlers() -> None:
    asyncio.get_running_loop().set_exception_handler(AsyncioExceptionHandler)
