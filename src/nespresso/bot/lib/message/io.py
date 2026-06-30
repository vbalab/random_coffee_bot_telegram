import asyncio
import logging
from dataclasses import dataclass
from enum import Enum

from aiogram import types
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
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
    UserFailed = " \033[91m[UserFailed]\033[0m"
    Callback = " \033[92m[Callback]\033[0m"
    Doc = " \033[92m[Document]\033[0m"
    Pending = " \033[96m[Pending]\033[0m"
    ZeroMessage = " \033[96m[ZeroMessage]\033[0m"
    NoText = " \033[96m[NoText]\033[0m"


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

    part = await GetChatUserLoggingPart(chat_id)
    logging.info(f"{part} {SignIO.Out.value}{add.value}{context.value} {repr(text)}")

    return message


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
