import logging
from enum import Enum

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.bot.handlers.admin.commands.back import BackToAdminPanelCallbackData
from nespresso.bot.lib.chat.username import GetTgUsername
from nespresso.bot.lib.hub_state import HUB_MESSAGES
from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import ContextIO, PersonalMsg, SendMessage, SendMessagesToGroup
from nespresso.bot.lifecycle.creator import bot
from nespresso.core.configs.admin_store import AddAdmin, GetAdminIds, RemoveAdmin
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

router = Router()


class AdminsAction(str, Enum):
    AddAdmin = "add"
    RemoveAdmin = "remove"


class AdminsCallbackData(CallbackData, prefix="admins_panel"):
    action: AdminsAction


class AdminsStates(StatesGroup):
    AddUsername = State()
    RemoveUsername = State()


def AdminsKeyboard(lang: str) -> InlineKeyboardMarkup:
    back_button = InlineKeyboardButton(
        text=t(lang, "admin.button_back"),
        callback_data=BackToAdminPanelCallbackData().pack(),
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "admin.admins_button_add"),
                    callback_data=AdminsCallbackData(
                        action=AdminsAction.AddAdmin
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text=t(lang, "admin.admins_button_remove"),
                    callback_data=AdminsCallbackData(
                        action=AdminsAction.RemoveAdmin
                    ).pack(),
                ),
            ],
            [back_button],
        ]
    )


async def _GetAdminDisplayName(chat_id: int) -> str:
    try:
        chat = await bot.get_chat(chat_id)
        if chat.username:
            try:
                ctx = await GetUserContextService()
                await ctx.UpdateTgUser(
                    chat_id=chat_id,
                    column=TgUser.username,
                    value=chat.username,
                )
            except Exception:
                logging.warning(
                    f"Failed to update username for chat_id={chat_id}", exc_info=True
                )
            return f"@{chat.username}"
    except Exception:
        logging.warning(f"Failed to get chat info for chat_id={chat_id}", exc_info=True)

    try:
        ctx = await GetUserContextService()
        username = await ctx.GetTgUser(chat_id=chat_id, column=TgUser.username)
        if username:
            return f"@{username}"
    except Exception:
        logging.warning(
            f"Failed to get username from DB for chat_id={chat_id}", exc_info=True
        )

    return str(chat_id)


async def _NotifyAdminsAboutChange(actor_chat_id: int, key: str, **kwargs: str) -> None:
    """Send a notification to all admins except the actor."""
    other_admins = [aid for aid in await GetAdminIds() if aid != actor_chat_id]
    if not other_admins:
        return

    actor_name = str(actor_chat_id)
    try:
        username = await GetTgUsername(actor_chat_id)
        if username:
            actor_name = f"@{username}"
    except Exception:
        pass

    messages: list[PersonalMsg] = []
    for admin_id in other_admins:
        lang = await GetUserLanguage(admin_id)
        text = t(lang, key, actor=actor_name, **kwargs)
        messages.append(PersonalMsg(chat_id=admin_id, text=text))

    await SendMessagesToGroup(messages)


async def BuildAdminsPanelText(lang: str) -> str:
    ids = await GetAdminIds()
    if not ids:
        admins_section = t(lang, "admin.admins_no_admins")
    else:
        lines = [await _GetAdminDisplayName(chat_id) for chat_id in ids]
        admins_section = "\n".join(f"• {line}" for line in lines)

    return t(lang, "admin.admins_header", admins_section=admins_section)


async def ShowAdminsPanel(chat_id: int) -> None:
    """Edit the hub message to display the admins sub-panel."""
    lang = await GetUserLanguage(chat_id)
    text = await BuildAdminsPanelText(lang)
    keyboard = AdminsKeyboard(lang)

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

    msg = await SendMessage(chat_id=chat_id, text=text, reply_markup=keyboard)
    if msg is not None:
        HUB_MESSAGES[chat_id] = msg.message_id
        ctx = await GetUserContextService()
        await ctx.UpdateTgUser(chat_id=chat_id, column=TgUser.panel_message_id, value=msg.message_id)


# --- Add Admin ---


@router.callback_query(AdminsCallbackData.filter(F.action == AdminsAction.AddAdmin))
async def AdminsPanelAdd(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text=t(lang, "admin.admins_enter_add"),
    )
    await state.set_state(AdminsStates.AddUsername)


@router.message(StateFilter(AdminsStates.AddUsername), F.content_type == "text")
async def AdminsPanelAddUsername(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    lang = await GetUserLanguage(message.chat.id)
    username = message.text.replace("@", "").strip()
    ctx = await GetUserContextService()
    chat_id = await ctx.GetTgChatIdBy(tg_username=username)

    if chat_id is None:
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.admins_not_found", username=username),
            context=ContextIO.UserFailed,
        )
        return

    added = await AddAdmin(chat_id)
    await state.clear()

    if not added:
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.admins_already_admin", username=username),
        )
    else:
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.admins_added", username=username),
        )
        await _NotifyAdminsAboutChange(
            message.chat.id, "admin.admins_notify_added", target=f"@{username}"
        )

    await ShowAdminsPanel(message.chat.id)


# --- Remove Admin ---


@router.callback_query(AdminsCallbackData.filter(F.action == AdminsAction.RemoveAdmin))
async def AdminsPanelRemove(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text=t(lang, "admin.admins_enter_remove"),
    )
    await state.set_state(AdminsStates.RemoveUsername)


@router.message(StateFilter(AdminsStates.RemoveUsername), F.content_type == "text")
async def AdminsPanelRemoveUsername(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    lang = await GetUserLanguage(message.chat.id)
    username = message.text.replace("@", "").strip()
    ctx = await GetUserContextService()
    chat_id = await ctx.GetTgChatIdBy(tg_username=username)

    if chat_id is None:
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.admins_not_found", username=username),
            context=ContextIO.UserFailed,
        )
        return

    if chat_id == message.chat.id:
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.admins_cannot_remove_self"),
            context=ContextIO.UserFailed,
        )
        await state.clear()
        await ShowAdminsPanel(message.chat.id)
        return

    removed = await RemoveAdmin(chat_id)
    await state.clear()

    if not removed:
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.admins_not_admin", username=username),
        )
    else:
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.admins_removed", username=username),
        )
        await _NotifyAdminsAboutChange(
            message.chat.id, "admin.admins_notify_removed", target=f"@{username}"
        )

    await ShowAdminsPanel(message.chat.id)
