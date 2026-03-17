import logging
from enum import Enum

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.bot.lib.message.checks import CheckVerified
from nespresso.bot.lib.message.i18n import GetUserLanguage, SetUserLanguage, t
from nespresso.bot.lib.message.io import SendMessage
from nespresso.core.configs.title_store import GetTitle
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

router = Router()


class SettingsAction(str, Enum):
    ToggleMatching = "toggle_matching"
    ChangeLanguage = "change_language"
    Help = "help"
    Back = "back"


class SettingsCallbackData(CallbackData, prefix="settings"):
    action: SettingsAction


class HelpAction(str, Enum):
    AskHelp = "ask"
    Back = "back"
    BackToHub = "back_hub"


class HelpCallbackData(CallbackData, prefix="help"):
    action: HelpAction


def BuildSettingsPanelContent(
    lang: str, matching_paused: bool
) -> tuple[str, InlineKeyboardMarkup]:
    matching_label = (
        t(lang, "hub.matching_paused")
        if matching_paused
        else t(lang, "hub.matching_active")
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=matching_label,
                    callback_data=SettingsCallbackData(
                        action=SettingsAction.ToggleMatching
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "settings.button_language"),
                    callback_data=SettingsCallbackData(
                        action=SettingsAction.ChangeLanguage
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "settings.button_help"),
                    callback_data=SettingsCallbackData(
                        action=SettingsAction.Help
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "settings.button_back"),
                    callback_data=SettingsCallbackData(
                        action=SettingsAction.Back
                    ).pack(),
                )
            ],
        ]
    )
    return t(lang, "settings.panel_header"), keyboard


def BuildHelpPanelContent(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "help.button_ask"),
                    callback_data=HelpCallbackData(action=HelpAction.AskHelp).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "help.button_back"),
                    callback_data=HelpCallbackData(action=HelpAction.Back).pack(),
                )
            ],
        ]
    )
    return t(lang, "help.panel_header"), keyboard


def BuildHelpCommandPanelContent(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    """Help panel for use with the /help command (Back returns to hub)."""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "help.button_ask"),
                    callback_data=HelpCallbackData(action=HelpAction.AskHelp).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "help.button_back"),
                    callback_data=HelpCallbackData(action=HelpAction.BackToHub).pack(),
                )
            ],
        ]
    )
    return t(lang, "help.panel_header"), keyboard


@router.callback_query(
    SettingsCallbackData.filter(F.action == SettingsAction.ToggleMatching)
)
async def SettingsToggleMatching(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()

    current = await ctx.GetTgUser(chat_id, TgUser.matching_paused) or False
    new_value = not current
    await ctx.UpdateTgUser(chat_id, TgUser.matching_paused, new_value)

    _, keyboard = BuildSettingsPanelContent(lang, matching_paused=new_value)
    try:
        await callback_query.message.edit_reply_markup(reply_markup=keyboard)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.warning(
                f"Failed to update matching toggle keyboard for chat_id={chat_id}: {e}"
            )


@router.callback_query(
    SettingsCallbackData.filter(F.action == SettingsAction.ChangeLanguage)
)
async def SettingsChangeLanguage(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)

    new_lang = "ru" if lang == "en" else "en"
    await SetUserLanguage(chat_id, new_lang)

    ctx = await GetUserContextService()
    matching_paused = await ctx.GetTgUser(chat_id, TgUser.matching_paused) or False

    text, keyboard = BuildSettingsPanelContent(
        new_lang, matching_paused=matching_paused
    )
    try:
        await callback_query.message.edit_text(text=text, reply_markup=keyboard)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.warning(
                f"Failed to edit settings language toggle for chat_id={chat_id}: {e}"
            )


@router.callback_query(SettingsCallbackData.filter(F.action == SettingsAction.Help))
async def SettingsHelpCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)

    text, keyboard = BuildHelpPanelContent(lang)
    try:
        await callback_query.message.edit_text(text=text, reply_markup=keyboard)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.warning(
                f"Failed to edit settings→help panel for chat_id={chat_id}: {e}"
            )


@router.callback_query(SettingsCallbackData.filter(F.action == SettingsAction.Back))
async def SettingsBackCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.message.chat.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()
    is_admin = await ctx.GetTgUser(chat_id, TgUser.is_admin) or False

    from nespresso.bot.handlers.client.commands.hub import HubKeyboard

    try:
        await callback_query.message.edit_text(
            text=GetTitle(lang),
            reply_markup=HubKeyboard(lang, is_admin),
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.warning(f"Failed to edit settings→hub for chat_id={chat_id}: {e}")


@router.callback_query(HelpCallbackData.filter(F.action == HelpAction.AskHelp))
async def HelpAskCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()

    user = await ctx.GetTgUser(chat_id)
    username = f"@{user.username}" if user and user.username else str(chat_id)

    for admin_id in await ctx.GetAdminChatIds():
        admin_lang = await GetUserLanguage(admin_id)
        notification = t(
            admin_lang, "help.admin_notification", username=username, chat_id=chat_id
        )
        await SendMessage(chat_id=admin_id, text=notification)

    await SendMessage(chat_id=chat_id, text=t(lang, "help.request_sent"))


@router.callback_query(HelpCallbackData.filter(F.action == HelpAction.Back))
async def HelpBackCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()
    matching_paused = await ctx.GetTgUser(chat_id, TgUser.matching_paused) or False

    text, keyboard = BuildSettingsPanelContent(lang, matching_paused=matching_paused)
    try:
        await callback_query.message.edit_text(text=text, reply_markup=keyboard)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.warning(f"Failed to edit help→settings for chat_id={chat_id}: {e}")


@router.callback_query(HelpCallbackData.filter(F.action == HelpAction.BackToHub))
async def HelpBackToHubCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    try:
        await callback_query.message.delete()
    except TelegramBadRequest as e:
        logging.warning(f"Failed to delete help message for chat_id={chat_id}: {e}")

    from nespresso.bot.handlers.client.commands.hub import SendHub

    await SendHub(chat_id)


@router.message(Command("help"))
async def HelpCommand(message: types.Message) -> None:
    chat_id = message.chat.id
    if not await CheckVerified(chat_id):
        return

    lang = await GetUserLanguage(chat_id)
    text, keyboard = BuildHelpCommandPanelContent(lang)
    await SendMessage(chat_id=chat_id, text=text, reply_markup=keyboard)
