from enum import Enum

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.bot.handlers.admin.commands.back import BackToAdminPanelCallbackData
from nespresso.bot.lib.hub_state import HUB_MESSAGES
from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import SendMessage
from nespresso.bot.lifecycle.creator import bot
from nespresso.core.configs.title_store import GetBothTitles, SetTitle
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

router = Router()


class TitlePanelAction(str, Enum):
    EditEN = "edit_en"
    EditRU = "edit_ru"


class TitlePanelCallbackData(CallbackData, prefix="title_panel"):
    action: TitlePanelAction


class TitlePanelStates(StatesGroup):
    EditEN = State()
    EditRU = State()


def TitlePanelKeyboard(lang: str) -> InlineKeyboardMarkup:
    back_button = InlineKeyboardButton(
        text=t(lang, "admin.button_back"),
        callback_data=BackToAdminPanelCallbackData().pack(),
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "admin.title_button_edit_en"),
                    callback_data=TitlePanelCallbackData(
                        action=TitlePanelAction.EditEN
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text=t(lang, "admin.title_button_edit_ru"),
                    callback_data=TitlePanelCallbackData(
                        action=TitlePanelAction.EditRU
                    ).pack(),
                ),
            ],
            [back_button],
        ]
    )


def BuildTitlePanelText(lang: str) -> str:
    en_title, ru_title = GetBothTitles()
    return t(lang, "admin.title_header", en_title=en_title, ru_title=ru_title)


async def ShowTitlePanel(chat_id: int) -> None:
    """Edit the hub message to display the title editor sub-panel."""
    lang = await GetUserLanguage(chat_id)
    text = BuildTitlePanelText(lang)
    keyboard = TitlePanelKeyboard(lang)

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


# --- Edit EN title ---


@router.callback_query(
    TitlePanelCallbackData.filter(F.action == TitlePanelAction.EditEN)
)
async def TitlePanelEditEN(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text=t(lang, "admin.title_enter_en"),
    )
    await state.set_state(TitlePanelStates.EditEN)


@router.message(StateFilter(TitlePanelStates.EditEN), F.content_type == "text")
async def TitlePanelSaveEN(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None
    SetTitle("en", message.text.strip())
    await state.clear()
    await ShowTitlePanel(message.chat.id)


# --- Edit RU title ---


@router.callback_query(
    TitlePanelCallbackData.filter(F.action == TitlePanelAction.EditRU)
)
async def TitlePanelEditRU(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text=t(lang, "admin.title_enter_ru"),
    )
    await state.set_state(TitlePanelStates.EditRU)


@router.message(StateFilter(TitlePanelStates.EditRU), F.content_type == "text")
async def TitlePanelSaveRU(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None
    SetTitle("ru", message.text.strip())
    await state.clear()
    await ShowTitlePanel(message.chat.id)
