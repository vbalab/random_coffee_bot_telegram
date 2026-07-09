import asyncio
import logging
from dataclasses import dataclass
from enum import Enum

from aiogram import types
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.filters.callback_data import CallbackData
from aiolimiter import AsyncLimiter

from nespresso.bot.lib.chat.block import UserBlockedBot
from nespresso.bot.lib.chat.username import GetChatUserLoggingPart
from nespresso.bot.lifecycle.creator import bot
from nespresso.db.services.user_context import GetUserContextService


class ContextIO(str, Enum):
    No = ""
    Error = " \033[91m[Error]\033[0m"
    Blocked = " \033[91m[Blocked]\033[0m"
    BadRequest = " \033[91m[BadRequest]\033[0m"
    RetryAfter = " \033[91m[RetryAfter]\033[0m"
    UserFailed = " \033[91m[UserFailed]\033[0m"
    Callback = " \033[92m[Callback]\033[0m"
    Doc = " \033[92m[Document]\033[0m"
    Edit = " \033[92m[Edit]\033[0m"
    Pending = " \033[96m[Pending]\033[0m"
    ZeroMessage = " \033[96m[ZeroMessage]\033[0m"
    NoText = " \033[96m[NoText]\033[0m"
    NoChange = " \033[96m[NoChange]\033[0m"


class SignIO(str, Enum):
    In = "\033[35m>>\033[0m"
    Out = "\033[36m<<\033[0m"


async def SendDocument(
    chat_id: int,
    document: types.FSInputFile,
    caption: str | None = None,
    reply_markup: (
        types.ReplyKeyboardMarkup
        | types.ReplyKeyboardRemove
        | types.InlineKeyboardMarkup
        | None
    ) = None,
) -> types.Message | None:
    add = ContextIO.No

    message: types.Message | None = None
    try:
        message = await bot.send_document(
            chat_id=chat_id,
            document=document,
            caption=caption,
            reply_markup=reply_markup,
        )

        ctx = await GetUserContextService()
        await ctx.RegisterOutgoingMessage(message)

    except TelegramForbiddenError:
        add = ContextIO.Blocked
        await UserBlockedBot(chat_id)

    except TelegramBadRequest:
        add = ContextIO.BadRequest

    except TelegramRetryAfter as e:
        # Flood control (429). Do NOT sleep(e.retry_after) inline — that would
        # stall the whole event loop / bulk-send loop; just skip this one send.
        add = ContextIO.RetryAfter
        logging.warning(
            f"chat_id={chat_id} flood control: retry_after={e.retry_after}s "
            "(document skipped)."
        )

    except TelegramAPIError as e:
        # Any other Telegram API error (network, server, migrate, …) must never
        # crash the caller mid-loop.
        add = ContextIO.Error
        logging.warning(f"chat_id={chat_id} document send failed: {e}")

    except Exception as e:  # noqa: BLE001 — a send must never crash a handler.
        add = ContextIO.Error
        logging.warning(f"chat_id={chat_id} unexpected document send error: {e}")

    part = await GetChatUserLoggingPart(chat_id)
    logging.info(f"{part} {SignIO.Out.value}{add.value}{ContextIO.Doc.value} {caption}")

    return message


async def SendMessage(
    chat_id: int,
    text: str,
    reply_markup: (
        types.ReplyKeyboardMarkup
        | types.ReplyKeyboardRemove
        | types.InlineKeyboardMarkup
        | None
    ) = None,
    context: ContextIO = ContextIO.No,
    parse_mode: str | None = None,
) -> types.Message | None:
    add = ContextIO.No

    message: types.Message | None = None
    try:
        message = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )

        ctx = await GetUserContextService()
        await ctx.RegisterOutgoingMessage(message)

    except TelegramForbiddenError:
        add = ContextIO.Blocked
        await UserBlockedBot(chat_id)

    except TelegramBadRequest:
        add = ContextIO.BadRequest

    except TelegramRetryAfter as e:
        # Flood control (429). Do NOT sleep(e.retry_after) inline — that would
        # stall the whole event loop / bulk-send loop; just skip this one send.
        add = ContextIO.RetryAfter
        logging.warning(
            f"chat_id={chat_id} flood control: retry_after={e.retry_after}s "
            "(message skipped)."
        )

    except TelegramAPIError as e:
        # Any other Telegram API error (network, server, migrate, …) must never
        # crash the caller mid-loop.
        add = ContextIO.Error
        logging.warning(f"chat_id={chat_id} message send failed: {e}")

    except Exception as e:  # noqa: BLE001 — a send must never crash a handler.
        add = ContextIO.Error
        logging.warning(f"chat_id={chat_id} unexpected message send error: {e}")

    part = await GetChatUserLoggingPart(chat_id)
    logging.info(f"{part} {SignIO.Out.value}{add.value}{context.value} {repr(text)}")

    return message


async def EditMessage(
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: types.InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> types.Message | bool | None:
    """Canonical panel editor — edit an existing message's text/markup in place.

    Mirrors ``SendMessage``'s error handling so every call site inherits it
    consistently instead of re-implementing the "message is not modified" swallow
    (and missing the block-cleanup that ``SendMessage`` does):
      - "message is not modified" BadRequest → swallowed (no-op edit).
      - any other BadRequest → logged (bad HTML, message-to-edit-gone, …).
      - user blocked the bot → ``UserBlockedBot`` cleanup, same as ``SendMessage``.
      - any other API / unexpected error → logged.
    Returns the edited message (or ``True`` for markup-only edits) / ``None``.
    """
    add = ContextIO.No

    result: types.Message | bool | None = None
    try:
        result = await bot.edit_message_text(
            text=text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )

    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            add = ContextIO.NoChange
        else:
            add = ContextIO.BadRequest
            logging.warning(f"chat_id={chat_id} message edit failed: {e}")

    except TelegramForbiddenError:
        add = ContextIO.Blocked
        await UserBlockedBot(chat_id)

    except TelegramRetryAfter as e:
        add = ContextIO.RetryAfter
        logging.warning(
            f"chat_id={chat_id} flood control: retry_after={e.retry_after}s "
            "(edit skipped)."
        )

    except TelegramAPIError as e:
        add = ContextIO.Error
        logging.warning(f"chat_id={chat_id} message edit failed: {e}")

    except Exception as e:  # noqa: BLE001 — an edit must never crash a handler.
        add = ContextIO.Error
        logging.warning(f"chat_id={chat_id} unexpected message edit error: {e}")

    part = await GetChatUserLoggingPart(chat_id)
    logging.info(f"{part} {SignIO.Out.value}{add.value}{ContextIO.Edit.value} {repr(text)}")

    return result


async def EditPanel(
    callback_query: types.CallbackQuery,
    text: str,
    reply_markup: types.InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> types.Message | bool | None:
    """Edit the message a callback fired on, via ``EditMessage``. No-op if the
    message is missing (deleted/too old — Telegram sends no editable message)."""
    message = callback_query.message
    if message is None:
        return None

    return await EditMessage(
        chat_id=message.chat.id,
        message_id=message.message_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )


@dataclass
class PersonalMsg:
    chat_id: int
    text: str


async def SendMessagesToGroup(messages: list[PersonalMsg]) -> None:
    limiter = AsyncLimiter(max_rate=30, time_period=1)

    async def SendMessageLimited(message: PersonalMsg) -> None:
        nonlocal limiter

        async with limiter:
            await SendMessage(chat_id=message.chat_id, text=message.text)

    tasks = []
    for message in messages:
        tasks.append(SendMessageLimited(message))

    await asyncio.gather(*tasks)


async def _CheckNewUser(chat_id: int) -> None:
    ctx = await GetUserContextService()
    exists = await ctx.CheckTgUserExists(chat_id)

    if exists:
        return

    await ctx.RegisterTgUser(chat_id=chat_id)


async def ReceiveMessage(
    message: types.Message,
    context: ContextIO = ContextIO.No,
) -> None:
    chat_id = message.chat.id
    await _CheckNewUser(chat_id)

    part = await GetChatUserLoggingPart(chat_id)
    logging.info(f"{part} {SignIO.In.value}{context.value} {repr(message.text)}")

    ctx = await GetUserContextService()
    await ctx.RegisterIncomingMessage(message)


async def ReceiveCallback(query: types.CallbackQuery, data: CallbackData) -> None:
    chat_id = query.from_user.id
    await _CheckNewUser(chat_id)

    part = await GetChatUserLoggingPart(chat_id)
    logging.info(
        f"{part} {SignIO.In.value} {ContextIO.Callback.value} {data.__prefix__}"
    )
    logging.debug(f"{part}, model_dump={data.model_dump()}")
