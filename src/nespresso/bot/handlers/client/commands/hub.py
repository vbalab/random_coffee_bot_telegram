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
from nespresso.core.configs.admin_store import admin_store

router = Router()


class HubAction(str, Enum):
    Find = "find"
    Admin = "admin"


class HubCallbackData(CallbackData, prefix="hub"):
    action: HubAction


def HubKeyboard(chat_id: int, lang: str) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=t(lang, "hub.find_person"),
                callback_data=HubCallbackData(action=HubAction.Find).pack(),
            )
        ]
    ]
    if admin_store.Contains(chat_id):
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

    old_id = HUB_MESSAGES.get(chat_id)
    if old_id is not None:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=old_id)
        except Exception:
            logging.warning(f"Failed to delete old hub message for chat_id={chat_id} message_id={old_id}", exc_info=True)

    msg = await SendMessage(
        chat_id=chat_id,
        text=t(lang, "hub.welcome"),
        reply_markup=HubKeyboard(chat_id, lang),
    )
    if msg is not None:
        HUB_MESSAGES[chat_id] = msg.message_id


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
    if not admin_store.Contains(chat_id):
        return

    # Lazy import to avoid circular dependency
    from nespresso.bot.handlers.admin.commands.admin import BuildAdminPanelContent

    lang = await GetUserLanguage(chat_id)
    text, keyboard = BuildAdminPanelContent(lang)
    try:
        await callback_query.message.edit_text(text=text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass


@router.callback_query(BackToHubCallbackData.filter())
async def HubBack(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await state.clear()

    chat_id = callback_query.message.chat.id
    lang = await GetUserLanguage(chat_id)
    try:
        await callback_query.message.edit_text(
            text=t(lang, "hub.welcome"),
            reply_markup=HubKeyboard(chat_id, lang),
        )
    except TelegramBadRequest:
        pass
