import logging
from enum import Enum

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.bot.handlers.admin.commands.back import BackToHubCallbackData
from nespresso.bot.handlers.client.commands.find import FindStates
from nespresso.bot.lib.hub_state import HUB_MESSAGES
from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import SendMessage
from nespresso.bot.lifecycle.creator import bot
from nespresso.core.configs.title_store import GetTitle
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

router = Router()


class HubAction(str, Enum):
    Find = "find"
    Admin = "admin"
    About = "about"
    Settings = "settings"


class HubCallbackData(CallbackData, prefix="hub"):
    action: HubAction


def HubKeyboard(lang: str, is_admin: bool) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=t(lang, "hub.find_person"),
                callback_data=HubCallbackData(action=HubAction.Find).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text=t(lang, "hub.my_about"),
                callback_data=HubCallbackData(action=HubAction.About).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text=t(lang, "hub.settings"),
                callback_data=HubCallbackData(action=HubAction.Settings).pack(),
            )
        ],
    ]
    if is_admin:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "hub.admin_panel"),
                    callback_data=HubCallbackData(action=HubAction.Admin).pack(),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def SendHub(chat_id: int) -> None:
    """Delete the old hub message (if any) and send a fresh one."""
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()

    # Prefer in-memory cache; fall back to DB (survives bot restarts)
    old_id = HUB_MESSAGES.get(chat_id)
    if old_id is None:
        old_id = await ctx.GetTgUser(chat_id, TgUser.panel_message_id)

    if old_id is not None:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=old_id)
        except Exception:
            logging.warning(
                f"Failed to delete old hub message for chat_id={chat_id} message_id={old_id}",
                exc_info=True,
            )

    is_admin = await ctx.GetTgUser(chat_id, TgUser.is_admin) or False
    msg = await SendMessage(
        chat_id=chat_id,
        text=GetTitle(lang),
        reply_markup=HubKeyboard(lang, is_admin),
    )
    if msg is not None:
        HUB_MESSAGES[chat_id] = msg.message_id
        await ctx.UpdateTgUser(
            chat_id=chat_id, column=TgUser.panel_message_id, value=msg.message_id
        )


@router.callback_query(HubCallbackData.filter(F.action == HubAction.Find))
async def HubFindCallback(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text=t(lang, "find.enter_query"),
    )
    await state.set_state(FindStates.Text)


@router.callback_query(HubCallbackData.filter(F.action == HubAction.Admin))
async def HubAdminCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.message.chat.id
    ctx = await GetUserContextService()
    is_admin = await ctx.GetTgUser(chat_id, TgUser.is_admin) or False
    if not is_admin:
        return

    # Lazy import to avoid circular dependency
    from nespresso.bot.handlers.admin.commands.admin import BuildAdminPanelContent

    lang = await GetUserLanguage(chat_id)
    text, keyboard = BuildAdminPanelContent(lang)
    try:
        await callback_query.message.edit_text(text=text, reply_markup=keyboard)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.warning(
                f"Failed to edit hub→admin panel for chat_id={chat_id}: {e}"
            )


@router.callback_query(HubCallbackData.filter(F.action == HubAction.Settings))
async def HubSettingsCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()
    matching_paused = await ctx.GetTgUser(chat_id, TgUser.matching_paused) or False

    from nespresso.bot.handlers.client.commands.settings import (
        BuildSettingsPanelContent,
    )

    text, keyboard = BuildSettingsPanelContent(lang, matching_paused=matching_paused)
    try:
        await callback_query.message.edit_text(text=text, reply_markup=keyboard)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.warning(
                f"Failed to edit hub→settings panel for chat_id={chat_id}: {e}"
            )


@router.callback_query(HubCallbackData.filter(F.action == HubAction.About))
async def HubAboutCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()
    about = await ctx.GetTgUser(chat_id, TgUser.about)

    from nespresso.bot.handlers.client.commands.about import BuildAboutPanelContent

    text, keyboard = BuildAboutPanelContent(lang, about)
    try:
        await callback_query.message.edit_text(text=text, reply_markup=keyboard)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.warning(
                f"Failed to edit hub→about panel for chat_id={chat_id}: {e}"
            )


@router.callback_query(BackToHubCallbackData.filter())
async def HubBack(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await state.clear()

    chat_id = callback_query.message.chat.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()
    is_admin = await ctx.GetTgUser(chat_id, TgUser.is_admin) or False
    try:
        await callback_query.message.edit_text(
            text=GetTitle(lang),
            reply_markup=HubKeyboard(lang, is_admin),
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.warning(f"Failed to edit back→hub for chat_id={chat_id}: {e}")
