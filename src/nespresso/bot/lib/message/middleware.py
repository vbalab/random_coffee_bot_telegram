import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Dispatcher
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from nespresso.bot.lib.chat.block import (
    CheckIfBlocked,
    RegisterCallbackAndCheckSpam,
    RegisterMessageAndCheckSpam,
)
from nespresso.bot.lib.message.checks import IsUnshared
from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import (
    ContextIO,
    ReceiveCallback,
    ReceiveMessage,
    SendMessage,
)


class MessageLoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,  # type: ignore[override]
        data: dict[str, Any],
    ) -> Any:
        chat_id = event.chat.id

        if await CheckIfBlocked(chat_id):
            return

        if RegisterMessageAndCheckSpam(chat_id):
            lang = await GetUserLanguage(chat_id)
            await SendMessage(
                chat_id=chat_id,
                text=t(lang, "common.spam_blocked"),
                context=ContextIO.Blocked,
            )
            return

        if await IsUnshared(chat_id):
            lang = await GetUserLanguage(chat_id)
            await SendMessage(
                chat_id=chat_id,
                text=t(lang, "common.directory_unshared"),
                context=ContextIO.Blocked,
            )
            return

        await ReceiveMessage(event)

        return await handler(event, data)


class CallbackLoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,  # type: ignore[override]
        data: dict[str, Any],
    ) -> Any:
        chat_id = event.from_user.id

        if await CheckIfBlocked(chat_id):
            return

        # Callbacks bypassed the spam counter entirely before (only the message
        # middleware ran it), so a callback flood was unbounded. Run it here too,
        # with the lenient callback threshold so normal pagination/reaction taps
        # stay well clear.
        if RegisterCallbackAndCheckSpam(chat_id):
            lang = await GetUserLanguage(chat_id)
            await SendMessage(
                chat_id=chat_id,
                text=t(lang, "common.spam_blocked"),
                context=ContextIO.Blocked,
            )
            return

        if await IsUnshared(chat_id):
            # Paused (opted out of directory sharing) — answer with a toast alert
            # instead of a new message so repeated taps don't spam the chat.
            lang = await GetUserLanguage(chat_id)
            try:
                await event.answer(
                    t(lang, "common.directory_unshared"), show_alert=True
                )
            except Exception:
                logging.debug("Failed to answer unshared-gate callback", exc_info=True)
            return

        if isinstance(event.message, InaccessibleMessage):
            # Telegram sends InaccessibleMessage (not Message) whenever the
            # original message was deleted or is too old to still be tracked.
            # Every handler in the codebase asserts
            # `isinstance(callback_query.message, types.Message)` — dispatching
            # here would crash the handler on every such tap (a near-guaranteed
            # occurrence: any user tapping a button under a deleted message).
            # Short-circuit here, once, instead of letting that assert blow up.
            lang = await GetUserLanguage(event.from_user.id)
            try:
                await event.answer(t(lang, "common.button_outdated"), show_alert=True)
            except Exception:
                logging.debug(
                    "Failed to answer callback on InaccessibleMessage", exc_info=True
                )
            return

        callback_data = data.get("callback_data")
        assert isinstance(callback_data, CallbackData)

        await ReceiveCallback(
            query=event,
            data=callback_data,
        )

        return await handler(event, data)


def SetBotMiddleware(dp: Dispatcher) -> None:
    dp.message.middleware(MessageLoggingMiddleware())
    dp.callback_query.middleware(CallbackLoggingMiddleware())
