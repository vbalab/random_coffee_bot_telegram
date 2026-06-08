from enum import Enum
from pathlib import Path

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.bot.handlers.admin.commands.back import BackToAdminPanelCallbackData
from nespresso.bot.lib.hub_state import HUB_MESSAGES
from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import ContextIO, SendDocument, SendMessage
from nespresso.bot.lifecycle.creator import bot
from nespresso.core.configs.paths import PATH_BOT_LOGS, PATH_BOT_QUICK_LOGS
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

router = Router()


class LogsPanelAction(str, Enum):
    Quick = "quick"
    Debug = "debug"


class LogsPanelCallbackData(CallbackData, prefix="logs_panel"):
    action: LogsPanelAction


def LogsPanelKeyboard(lang: str) -> InlineKeyboardMarkup:
    back_button = InlineKeyboardButton(
        text=t(lang, "admin.button_back"),
        callback_data=BackToAdminPanelCallbackData().pack(),
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "admin.logs_button_quick"),
                    callback_data=LogsPanelCallbackData(
                        action=LogsPanelAction.Quick
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text=t(lang, "admin.logs_button_debug"),
                    callback_data=LogsPanelCallbackData(
                        action=LogsPanelAction.Debug
                    ).pack(),
                ),
            ],
            [back_button],
        ]
    )


async def ShowLogsPanel(chat_id: int) -> None:
    """Edit the hub message to display the Logs sub-panel."""
    lang = await GetUserLanguage(chat_id)
    text = t(lang, "admin.logs_header")
    keyboard = LogsPanelKeyboard(lang)

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
        await ctx.UpdateTgUser(
            chat_id=chat_id,
            column=TgUser.panel_message_id,
            value=msg.message_id,
        )


async def _SendLogFile(chat_id: int, path: Path, lang: str) -> None:
    if not path.exists():
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "admin.logs_not_found"),
            context=ContextIO.UserFailed,
        )
        return
    await SendDocument(chat_id=chat_id, document=types.FSInputFile(path))


@router.callback_query(LogsPanelCallbackData.filter(F.action == LogsPanelAction.Quick))
async def LogsPanelQuick(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    chat_id = callback_query.message.chat.id
    lang = await GetUserLanguage(chat_id)
    await _SendLogFile(chat_id, PATH_BOT_QUICK_LOGS, lang)


@router.callback_query(LogsPanelCallbackData.filter(F.action == LogsPanelAction.Debug))
async def LogsPanelDebug(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    chat_id = callback_query.message.chat.id
    lang = await GetUserLanguage(chat_id)
    await _SendLogFile(chat_id, PATH_BOT_LOGS, lang)
