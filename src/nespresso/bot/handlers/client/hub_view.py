"""Shared hub-panel builders — a LEAF module.

`SendHub` / `HubKeyboard` (+ their `HubCallbackData` / `HubAction`) live here,
apart from `commands/hub.py` (which keeps the hub router + callback handlers), so
that sibling handler modules (`about`, `settings`, `start`) can import them at top
level WITHOUT forming an import cycle with `hub` — `hub` in turn needs those
modules' panel-content builders. This module must therefore import ONLY leaf
dependencies (io, i18n, hub_state, title_store, db models/services, the
`admin/commands/back` callbacks, aiogram, `lifecycle/creator`); it must never
import a handler-router module.
"""

import logging
from enum import Enum

from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.bot.lib.hub_state import HUB_LOCKS, HUB_MESSAGES
from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import SendMessage
from nespresso.bot.lifecycle.creator import bot
from nespresso.core.configs.title_store import GetTitle
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService


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
    # Serialized per chat_id so two concurrent calls can't both act on the same
    # "old" message and leave an orphaned duplicate hub (see HUB_LOCKS).
    async with HUB_LOCKS[chat_id]:
        lang = await GetUserLanguage(chat_id)
        ctx = await GetUserContextService()

        # Prefer in-memory cache; fall back to DB (survives bot restarts)
        old_id = HUB_MESSAGES.get(chat_id)
        if old_id is None:
            old_id = await ctx.GetTgUser(chat_id, TgUser.panel_message_id)

        if old_id is not None:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=old_id)
            except TelegramBadRequest as e:
                # Expected & harmless: the old hub is already gone, or older than
                # Telegram's 48h delete window. One clean line, no traceback.
                logging.warning(
                    f"Old hub message not deleted (chat_id={chat_id} "
                    f"message_id={old_id}): {e.message}"
                )
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
