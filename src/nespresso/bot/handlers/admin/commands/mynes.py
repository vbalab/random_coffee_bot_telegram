from enum import Enum

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.api.sync import GetLastSync, SyncFromMyNES
from nespresso.bot.handlers.admin.commands.back import BackToAdminPanelCallbackData
from nespresso.bot.lib.hub_state import HUB_MESSAGES
from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import SendMessage
from nespresso.bot.lifecycle.creator import bot
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

router = Router()


class MyNesPanelAction(str, Enum):
    SyncNow = "sync_now"


class MyNesPanelCallbackData(CallbackData, prefix="mynes_panel"):
    action: MyNesPanelAction


def MyNesPanelKeyboard(lang: str) -> InlineKeyboardMarkup:
    back_button = InlineKeyboardButton(
        text=t(lang, "admin.button_back"),
        callback_data=BackToAdminPanelCallbackData().pack(),
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "admin.mynes_button_sync"),
                    callback_data=MyNesPanelCallbackData(
                        action=MyNesPanelAction.SyncNow
                    ).pack(),
                ),
            ],
            [back_button],
        ]
    )


def _FormatLastSync(lang: str) -> str:
    report = GetLastSync()
    if report is None or report.started_at is None:
        return t(lang, "admin.mynes_last_sync_none")

    status = t(
        lang, "admin.mynes_status_ok" if report.ok else "admin.mynes_status_failed"
    )
    return t(
        lang,
        "admin.mynes_last_sync",
        status=status,
        when=report.started_at.strftime("%Y-%m-%d %H:%M UTC"),
        trigger=report.trigger,
        fetched=report.fetched,
        alumni=report.alumni,
        upserted=report.upserted,
        reindexed=report.reindexed,
        delisted=report.delisted,
        errors=report.index_errors,
        seconds=report.duration_s,
    )


async def ShowMyNesPanel(chat_id: int) -> None:
    """Edit the hub message to display the MyNES sub-panel."""
    lang = await GetUserLanguage(chat_id)
    text = f"{t(lang, 'admin.mynes_header')}\n\n{_FormatLastSync(lang)}"
    keyboard = MyNesPanelKeyboard(lang)

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


@router.callback_query(
    MyNesPanelCallbackData.filter(F.action == MyNesPanelAction.SyncNow)
)
async def MyNesPanelSyncNow(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)

    await SendMessage(chat_id=chat_id, text=t(lang, "admin.mynes_sync_running"))

    report = await SyncFromMyNES(trigger=f"admin:{chat_id}")

    if report.busy:
        await SendMessage(chat_id=chat_id, text=t(lang, "admin.mynes_sync_busy"))
        return

    if report.ok:
        await SendMessage(
            chat_id=chat_id,
            text=t(
                lang,
                "admin.mynes_sync_done",
                fetched=report.fetched,
                alumni=report.alumni,
                upserted=report.upserted,
                reindexed=report.reindexed,
                delisted=report.delisted,
                errors=report.index_errors,
                seconds=report.duration_s,
            ),
        )
    else:
        await SendMessage(chat_id=chat_id, text=t(lang, "admin.mynes_sync_failed"))

    # Refresh the panel header so it shows the run that just completed.
    await ShowMyNesPanel(chat_id)
