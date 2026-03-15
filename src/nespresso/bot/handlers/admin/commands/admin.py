from enum import Enum

from aiogram import F, Router, types
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.command import Command
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.bot.handlers.admin.commands.blocking import (
    BlockingAction,
    BlockingKeyboard,
)
from nespresso.bot.handlers.admin.commands.matching import (
    MatchingAction,
    MatchingKeyboard,
)
from nespresso.bot.lib.chat.block import CheckIfBlocked
from nespresso.bot.lib.message.file import SendTemporaryFileFromText, ToJSONText
from nespresso.bot.lib.message.filters import AdminFilter
from nespresso.bot.lib.message.io import (
    ContextIO,
    PersonalMsg,
    SendDocument,
    SendMessage,
    SendMessagesToGroup,
)
from nespresso.core.configs.paths import PATH_BOT_LOGS
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.matching.schedule import GetNextMatchingTime

router = Router()

_description = """\
⚙️ Admin Panel

📋 Logs — download bot logs
💬 Messages — view messages of a user
📤 Send — send a message to a user
📢 Send All — broadcast to all verified users
🚫 Blocking — block or unblock a user
⚙️ Matching — control the matching schedule\
"""


class AdminPanelAction(str, Enum):
    Logs = "📋 Logs"
    Messages = "💬 Messages"
    Send = "📤 Send"
    SendAll = "📢 Send All"
    Blocking = "🚫 Blocking"
    Matching = "⚙️ Matching"


class AdminPanelCallbackData(CallbackData, prefix="admin_panel"):
    action: AdminPanelAction


class AdminPanelStates(StatesGroup):
    BlockingUsername = State()
    MessagesArgs = State()
    SendUsername = State()
    SendMessage = State()
    SendaMessage = State()


def AdminPanelKeyboard() -> InlineKeyboardMarkup:
    def Button(action: AdminPanelAction) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=action.value,
            callback_data=AdminPanelCallbackData(action=action).pack(),
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [Button(AdminPanelAction.Logs), Button(AdminPanelAction.Messages)],
            [Button(AdminPanelAction.Send), Button(AdminPanelAction.SendAll)],
            [Button(AdminPanelAction.Blocking), Button(AdminPanelAction.Matching)],
        ]
    )


@router.message(Command("admin"), AdminFilter())
async def CommandAdmin(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await SendMessage(
        chat_id=message.chat.id,
        text=_description,
        reply_markup=AdminPanelKeyboard(),
    )


# --- Logs ---


@router.callback_query(AdminPanelCallbackData.filter(F.action == AdminPanelAction.Logs))
async def PanelLogs(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await SendDocument(
        chat_id=callback_query.message.chat.id,
        document=types.FSInputFile(PATH_BOT_LOGS),
    )


# --- Matching ---


@router.callback_query(
    AdminPanelCallbackData.filter(F.action == AdminPanelAction.Matching)
)
async def PanelMatching(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    next_run_time = GetNextMatchingTime()

    if next_run_time is None:
        await SendMessage(
            chat_id=callback_query.message.chat.id,
            text="🔴 Job is paused.\nNo next run scheduled\n\nDo you want to resume?",
            reply_markup=MatchingKeyboard([MatchingAction.Resume, MatchingAction.Leave]),
        )
    else:
        await SendMessage(
            chat_id=callback_query.message.chat.id,
            text=f"🟢 Job is active.\nNext run at {next_run_time.isoformat()}\n\nDo you want to pause?",
            reply_markup=MatchingKeyboard([MatchingAction.Pause, MatchingAction.Leave]),
        )


# --- Send All ---


@router.callback_query(
    AdminPanelCallbackData.filter(F.action == AdminPanelAction.SendAll)
)
async def PanelSendAll(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text="Input text of message to broadcast:",
    )
    await state.set_state(AdminPanelStates.SendaMessage)


@router.message(StateFilter(AdminPanelStates.SendaMessage), F.content_type == "text")
async def PanelSendaMessage(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    ctx = await GetUserContextService()
    chat_ids = await ctx.GetVerifiedTgUsersChatId()

    messages = [PersonalMsg(chat_id=chat_id, text=message.text) for chat_id in chat_ids]
    await SendMessagesToGroup(messages)

    await SendMessage(chat_id=message.chat.id, text="Done")
    await state.clear()


# --- Blocking ---


@router.callback_query(
    AdminPanelCallbackData.filter(F.action == AdminPanelAction.Blocking)
)
async def PanelBlocking(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text="Enter Telegram username (e.g. @vbalab):",
    )
    await state.set_state(AdminPanelStates.BlockingUsername)


@router.message(StateFilter(AdminPanelStates.BlockingUsername), F.content_type == "text")
async def PanelBlockingUsername(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    username = message.text.replace("@", "").strip()
    ctx = await GetUserContextService()
    chat_id = await ctx.GetTgChatIdBy(tg_username=username)

    if chat_id is None:
        await SendMessage(
            chat_id=message.chat.id,
            text="No such user.",
            context=ContextIO.UserFailed,
        )
        await state.clear()
        return

    blocked = await CheckIfBlocked(chat_id)
    await state.clear()

    if blocked:
        await SendMessage(
            chat_id=message.chat.id,
            text="🔴 User is blocked.\n\nDo you want to unblock?",
            reply_markup=BlockingKeyboard(
                actions=[BlockingAction.Unblock, BlockingAction.Leave],
                chat_id=chat_id,
            ),
        )
    else:
        await SendMessage(
            chat_id=message.chat.id,
            text="🟢 User is not blocked.\n\nDo you want to block?",
            reply_markup=BlockingKeyboard(
                actions=[BlockingAction.Block, BlockingAction.Leave],
                chat_id=chat_id,
            ),
        )


# --- Messages ---


@router.callback_query(
    AdminPanelCallbackData.filter(F.action == AdminPanelAction.Messages)
)
async def PanelMessages(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text='Enter username and message limit (e.g. "@vbalab 15"):',
    )
    await state.set_state(AdminPanelStates.MessagesArgs)


@router.message(StateFilter(AdminPanelStates.MessagesArgs), F.content_type == "text")
async def PanelMessagesArgs(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    parts = message.text.split()
    if len(parts) != 2:  # noqa: PLR2004
        await SendMessage(
            chat_id=message.chat.id,
            text='Expected format: "@vbalab 15"\nTry again.',
            context=ContextIO.UserFailed,
        )
        await state.clear()
        return

    tg_username, limit_str = parts
    ctx = await GetUserContextService()
    chat_id = await ctx.GetTgChatIdBy(tg_username=tg_username.replace("@", ""))

    if chat_id is None:
        await SendMessage(
            chat_id=message.chat.id,
            text="User with such credentials doesn't exist.\nAborting",
            context=ContextIO.UserFailed,
        )
        await state.clear()
        return

    if not limit_str.isdigit():
        await SendMessage(
            chat_id=message.chat.id,
            text="Limit should be a number, e.g. 50\nTry again",
            context=ContextIO.UserFailed,
        )
        await state.clear()
        return

    messages = await ctx.GetRecentMessages(chat_id=chat_id, limit=int(limit_str))
    messages_dict = [m.IntoDict() for m in messages]
    messages_str = ToJSONText(messages_dict)

    await SendTemporaryFileFromText(chat_id=message.chat.id, text=messages_str)
    await state.clear()


# --- Send ---


@router.callback_query(
    AdminPanelCallbackData.filter(F.action == AdminPanelAction.Send)
)
async def PanelSend(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text="Enter Telegram username (e.g. @vbalab):",
    )
    await state.set_state(AdminPanelStates.SendUsername)


@router.message(StateFilter(AdminPanelStates.SendUsername), F.content_type == "text")
async def PanelSendUsername(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    username = message.text.replace("@", "").strip()
    ctx = await GetUserContextService()
    chat_id = await ctx.GetTgChatIdBy(tg_username=username)

    if chat_id is None:
        await SendMessage(
            chat_id=message.chat.id,
            text="User with such credentials doesn't exist.\nAborting",
            context=ContextIO.UserFailed,
        )
        await state.clear()
        return

    await SendMessage(chat_id=message.chat.id, text="Input text of message:")
    await state.set_state(AdminPanelStates.SendMessage)
    await state.set_data({"chat_id": chat_id})


@router.message(StateFilter(AdminPanelStates.SendMessage), F.content_type == "text")
async def PanelSendMessage(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    data = await state.get_data()
    output = await SendMessage(chat_id=data["chat_id"], text=message.text)

    if output:
        await SendMessage(chat_id=message.chat.id, text="Successful")
    else:
        await SendMessage(chat_id=message.chat.id, text="Unsuccessful")

    await state.clear()
