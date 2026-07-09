import logging
from enum import StrEnum

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.bot.handlers.admin.commands.admins import ShowAdminsPanel
from nespresso.bot.handlers.admin.commands.back import (
    BackToAdminPanelCallbackData,
    BackToHubCallbackData,
)
from nespresso.bot.handlers.admin.commands.blocking import ShowBlockingPanel
from nespresso.bot.handlers.admin.commands.logs import ShowLogsPanel
from nespresso.bot.handlers.admin.commands.matching import (
    ShowMatchingPanel,
)
from nespresso.bot.handlers.admin.commands.mynes import ShowMyNesPanel
from nespresso.bot.handlers.admin.commands.statistics import ShowStatisticsPanel
from nespresso.bot.handlers.admin.commands.title import ShowTitlePanel
from nespresso.bot.lib.chat.username import ResolveChatIdByUsername
from nespresso.bot.lib.hub_state import HUB_MESSAGES
from nespresso.bot.lib.message.file import SendTemporaryFileFromText, ToJSONText
from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import (
    ContextIO,
    PersonalMsg,
    SendMessage,
    SendMessagesToGroup,
)
from nespresso.bot.lifecycle.creator import bot
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

router = Router()


class AdminPanelAction(StrEnum):
    Logs = "logs"
    Messages = "messages"
    Send = "send"
    SendAll = "send_all"
    Blocking = "blocking"
    Matching = "matching"
    Admins = "admins"
    Statistics = "statistics"
    Title = "title"
    MyNes = "mynes"


class AdminPanelCallbackData(CallbackData, prefix="admin_panel"):
    action: AdminPanelAction


class AdminPanelStates(StatesGroup):
    MessagesArgs = State()
    SendUsername = State()
    SendMessage = State()
    SendaMessage = State()


def AdminPanelKeyboard(lang: str) -> InlineKeyboardMarkup:
    def Button(action: AdminPanelAction, label_key: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=t(lang, label_key),
            callback_data=AdminPanelCallbackData(action=action).pack(),
        )

    back_hub_button = InlineKeyboardButton(
        text=t(lang, "admin.button_back_hub"),
        callback_data=BackToHubCallbackData().pack(),
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                Button(AdminPanelAction.Logs, "admin.button_logs"),
                Button(AdminPanelAction.Messages, "admin.button_messages"),
            ],
            [
                Button(AdminPanelAction.Send, "admin.button_send"),
                Button(AdminPanelAction.SendAll, "admin.button_send_all"),
            ],
            [
                Button(AdminPanelAction.Blocking, "admin.button_blocking"),
                Button(AdminPanelAction.Matching, "admin.button_matching"),
            ],
            [
                Button(AdminPanelAction.Admins, "admin.button_admins"),
                Button(AdminPanelAction.Statistics, "admin.button_statistics"),
            ],
            [
                Button(AdminPanelAction.Title, "admin.button_title"),
                Button(AdminPanelAction.MyNes, "admin.button_mynes"),
            ],
            [back_hub_button],
        ]
    )


def BuildAdminPanelContent(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    return t(lang, "admin.panel_header"), AdminPanelKeyboard(lang)


async def ShowAdminPanel(chat_id: int) -> None:
    """Edit the hub message to display the admin panel."""
    lang = await GetUserLanguage(chat_id)
    text, keyboard = BuildAdminPanelContent(lang)

    hub_msg_id = HUB_MESSAGES.get(chat_id)
    if hub_msg_id is None:
        ctx = await GetUserContextService()
        hub_msg_id = await ctx.GetTgUser(chat_id, TgUser.panel_message_id)

    if hub_msg_id is not None:
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=hub_msg_id,
                reply_markup=keyboard,
            )
            return
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return
            # Message was deleted or inaccessible — fall through to send a new one

    msg = await SendMessage(chat_id=chat_id, text=text, reply_markup=keyboard)
    if msg is not None:
        HUB_MESSAGES[chat_id] = msg.message_id
        ctx = await GetUserContextService()
        await ctx.UpdateTgUser(
            chat_id=chat_id, column=TgUser.panel_message_id, value=msg.message_id
        )


# --- Back to Admin Panel ---


@router.callback_query(BackToAdminPanelCallbackData.filter())
async def PanelBack(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await state.clear()

    lang = await GetUserLanguage(callback_query.from_user.id)
    text, keyboard = BuildAdminPanelContent(lang)
    try:
        await callback_query.message.edit_text(text=text, reply_markup=keyboard)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.warning(
                f"Failed to edit back→admin panel for chat_id={callback_query.from_user.id}: {e}"
            )


# --- Logs ---


@router.callback_query(AdminPanelCallbackData.filter(F.action == AdminPanelAction.Logs))
async def PanelLogs(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await ShowLogsPanel(callback_query.message.chat.id)


# --- Matching ---


@router.callback_query(
    AdminPanelCallbackData.filter(F.action == AdminPanelAction.Matching)
)
async def PanelMatching(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    try:
        await callback_query.message.edit_text(**ShowMatchingPanel(lang))
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.warning(
                f"Failed to edit admin→matching panel for chat_id={callback_query.from_user.id}: {e}"
            )


# --- Send All ---


@router.callback_query(
    AdminPanelCallbackData.filter(F.action == AdminPanelAction.SendAll)
)
async def PanelSendAll(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text=t(lang, "admin.broadcast_enter_text"),
    )
    await state.set_state(AdminPanelStates.SendaMessage)


@router.message(StateFilter(AdminPanelStates.SendaMessage), F.content_type == "text")
async def PanelSendaMessage(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    ctx = await GetUserContextService()
    chat_ids = await ctx.GetVerifiedTgUsersChatId()

    messages = [PersonalMsg(chat_id=chat_id, text=message.text) for chat_id in chat_ids]
    await SendMessagesToGroup(messages)

    lang = await GetUserLanguage(message.chat.id)
    await SendMessage(chat_id=message.chat.id, text=t(lang, "admin.broadcast_done"))
    await state.clear()
    await ShowAdminPanel(message.chat.id)


# --- Blocking ---


@router.callback_query(
    AdminPanelCallbackData.filter(F.action == AdminPanelAction.Blocking)
)
async def PanelBlocking(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await state.clear()
    await ShowBlockingPanel(callback_query.message.chat.id)


# --- Messages ---


@router.callback_query(
    AdminPanelCallbackData.filter(F.action == AdminPanelAction.Messages)
)
async def PanelMessages(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text=t(lang, "admin.messages_enter_args"),
    )
    await state.set_state(AdminPanelStates.MessagesArgs)


@router.message(StateFilter(AdminPanelStates.MessagesArgs), F.content_type == "text")
async def PanelMessagesArgs(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    lang = await GetUserLanguage(message.chat.id)
    parts = message.text.split()
    if len(parts) != 2:  # noqa: PLR2004
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.messages_args_invalid"),
            context=ContextIO.UserFailed,
        )
        return

    tg_username, limit_str = parts
    chat_id = await ResolveChatIdByUsername(tg_username.replace("@", ""))
    ctx = await GetUserContextService()

    if chat_id is None or not await ctx.CheckTgUserExists(chat_id):
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.user_not_found"),
            context=ContextIO.UserFailed,
        )
        await state.clear()
        return

    if not limit_str.isdigit():
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.limit_not_number"),
            context=ContextIO.UserFailed,
        )
        await state.clear()
        return

    messages = await ctx.GetRecentMessages(chat_id=chat_id, limit=int(limit_str))
    messages_dict = [m.IntoDict() for m in messages]
    messages_str = ToJSONText(messages_dict)

    await SendTemporaryFileFromText(chat_id=message.chat.id, text=messages_str)
    await state.clear()
    await ShowAdminPanel(message.chat.id)


# --- Send ---


@router.callback_query(AdminPanelCallbackData.filter(F.action == AdminPanelAction.Send))
async def PanelSend(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text=t(lang, "admin.send_enter_username"),
    )
    await state.set_state(AdminPanelStates.SendUsername)


@router.message(StateFilter(AdminPanelStates.SendUsername), F.content_type == "text")
async def PanelSendUsername(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    lang = await GetUserLanguage(message.chat.id)
    username = message.text.replace("@", "").strip()
    chat_id = await ResolveChatIdByUsername(username)
    ctx = await GetUserContextService()

    if chat_id is None or not await ctx.CheckTgUserExists(chat_id):
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.user_not_found"),
            context=ContextIO.UserFailed,
        )
        return

    await SendMessage(chat_id=message.chat.id, text=t(lang, "admin.send_enter_text"))
    await state.set_state(AdminPanelStates.SendMessage)
    await state.set_data({"chat_id": chat_id})


@router.message(StateFilter(AdminPanelStates.SendMessage), F.content_type == "text")
async def PanelSendMessage(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    lang = await GetUserLanguage(message.chat.id)
    data = await state.get_data()
    output = await SendMessage(chat_id=data["chat_id"], text=message.text)

    if output:
        await SendMessage(
            chat_id=message.chat.id, text=t(lang, "admin.send_successful")
        )
    else:
        await SendMessage(
            chat_id=message.chat.id, text=t(lang, "admin.send_unsuccessful")
        )

    await state.clear()
    await ShowAdminPanel(message.chat.id)


# --- Admins ---


@router.callback_query(
    AdminPanelCallbackData.filter(F.action == AdminPanelAction.Admins)
)
async def PanelAdmins(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await ShowAdminsPanel(callback_query.message.chat.id)


# --- Statistics ---


@router.callback_query(
    AdminPanelCallbackData.filter(F.action == AdminPanelAction.Statistics)
)
async def PanelStatistics(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await ShowStatisticsPanel(callback_query.message.chat.id)


# --- Title ---


@router.callback_query(
    AdminPanelCallbackData.filter(F.action == AdminPanelAction.Title)
)
async def PanelTitle(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await ShowTitlePanel(callback_query.message.chat.id)


# --- MyNES ---


@router.callback_query(
    AdminPanelCallbackData.filter(F.action == AdminPanelAction.MyNes)
)
async def PanelMyNes(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await state.clear()
    await ShowMyNesPanel(callback_query.message.chat.id)
