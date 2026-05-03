import csv
import io
import logging
from enum import Enum

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.api.request import GetNesUserFromMyNES
from nespresso.bot.handlers.admin.commands.back import BackToAdminPanelCallbackData
from nespresso.bot.lib.hub_state import HUB_MESSAGES
from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import ContextIO, SendMessage
from nespresso.bot.lifecycle.creator import bot
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

router = Router()

_NES_EMAIL_DOMAIN = "@nes.ru"
_LOGIN_HEADER = "login"


class MyNesPanelAction(str, Enum):
    UploadCSV = "upload_csv"


class MyNesPanelCallbackData(CallbackData, prefix="mynes_panel"):
    action: MyNesPanelAction


class MyNesPanelStates(StatesGroup):
    WaitForCSV = State()


def MyNesPanelKeyboard(lang: str) -> InlineKeyboardMarkup:
    back_button = InlineKeyboardButton(
        text=t(lang, "admin.button_back"),
        callback_data=BackToAdminPanelCallbackData().pack(),
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "admin.mynes_button_upload"),
                    callback_data=MyNesPanelCallbackData(
                        action=MyNesPanelAction.UploadCSV
                    ).pack(),
                ),
            ],
            [back_button],
        ]
    )


async def ShowMyNesPanel(chat_id: int) -> None:
    """Edit the hub message to display the MyNES sub-panel."""
    lang = await GetUserLanguage(chat_id)
    text = t(lang, "admin.mynes_header")
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
    MyNesPanelCallbackData.filter(F.action == MyNesPanelAction.UploadCSV)
)
async def MyNesPanelUploadCSV(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text=t(lang, "admin.mynes_enter_csv"),
    )
    await state.set_state(MyNesPanelStates.WaitForCSV)


def _ParseLogins(content: str) -> tuple[list[str], str | None]:
    """Return (logins, error_key). Strips whitespace and ignores blanks."""
    try:
        reader = csv.reader(io.StringIO(content))
        rows = [row for row in reader if row and any(cell.strip() for cell in row)]
    except csv.Error:
        return [], "admin.mynes_csv_invalid"

    if not rows:
        return [], "admin.mynes_csv_empty"

    header = [cell.strip().lower() for cell in rows[0]]
    if header != [_LOGIN_HEADER]:
        return [], "admin.mynes_csv_bad_header"

    logins: list[str] = []
    for row in rows[1:]:
        login = row[0].strip().lower()
        if not login:
            continue
        if login.endswith(_NES_EMAIL_DOMAIN):
            login = login[: -len(_NES_EMAIL_DOMAIN)]
        logins.append(login)

    if not logins:
        return [], "admin.mynes_csv_no_logins"

    return logins, None


@router.message(StateFilter(MyNesPanelStates.WaitForCSV), F.content_type == "document")
async def MyNesPanelReceiveCSV(message: types.Message, state: FSMContext) -> None:
    assert message.document is not None

    chat_id = message.chat.id
    lang = await GetUserLanguage(chat_id)

    file_name = message.document.file_name or ""
    if not file_name.lower().endswith(".csv"):
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "admin.mynes_csv_not_csv"),
            context=ContextIO.UserFailed,
        )
        return

    buffer = io.BytesIO()
    await bot.download(message.document, destination=buffer)
    buffer.seek(0)

    try:
        content = buffer.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "admin.mynes_csv_not_utf8"),
            context=ContextIO.UserFailed,
        )
        return

    logins, error_key = _ParseLogins(content)
    if error_key is not None:
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, error_key),
            context=ContextIO.UserFailed,
        )
        return

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "admin.mynes_processing", count=len(logins)),
    )

    success = 0
    not_alumni = 0
    failed = 0
    for login in logins:
        email = f"{login}{_NES_EMAIL_DOMAIN}"
        try:
            nes_user = await GetNesUserFromMyNES(email, grant_data_sharing=True)
        except Exception:
            logging.exception(
                f"MyNES CSV import: failed to fetch login={login}",
            )
            failed += 1
            continue

        if nes_user is None:
            failed += 1
            continue

        if not nes_user.alumni:
            not_alumni += 1
            continue

        success += 1

    await SendMessage(
        chat_id=chat_id,
        text=t(
            lang,
            "admin.mynes_done",
            total=len(logins),
            success=success,
            not_alumni=not_alumni,
            failed=failed,
        ),
    )

    await state.clear()
    await ShowMyNesPanel(chat_id)


@router.message(StateFilter(MyNesPanelStates.WaitForCSV))
async def MyNesPanelWrongContent(message: types.Message) -> None:
    lang = await GetUserLanguage(message.chat.id)
    await SendMessage(
        chat_id=message.chat.id,
        text=t(lang, "admin.mynes_csv_not_csv"),
        context=ContextIO.UserFailed,
    )
