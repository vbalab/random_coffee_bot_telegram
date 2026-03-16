from enum import Enum

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import SendMessage
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

router = Router()


class AboutStates(StatesGroup):
    WriteAbout = State()


class AboutAction(str, Enum):
    WriteNew = "write_new"
    Back = "back"


class AboutCallbackData(CallbackData, prefix="about"):
    action: AboutAction


def BuildAboutPanelContent(lang: str, about: str | None) -> tuple[str, types.InlineKeyboardMarkup]:
    current = about if about else t(lang, "about.not_set")
    text = t(lang, "about.panel_header", current=current)
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=t(lang, "about.button_write_new"),
                    callback_data=AboutCallbackData(action=AboutAction.WriteNew).pack(),
                )
            ],
            [
                types.InlineKeyboardButton(
                    text=t(lang, "about.button_back"),
                    callback_data=AboutCallbackData(action=AboutAction.Back).pack(),
                )
            ],
        ]
    )
    return text, keyboard


@router.callback_query(AboutCallbackData.filter(F.action == AboutAction.WriteNew))
async def AboutWriteNewCallback(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "about.enter_text"),
    )
    await state.set_state(AboutStates.WriteAbout)


@router.callback_query(AboutCallbackData.filter(F.action == AboutAction.Back))
async def AboutBackCallback(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await state.clear()

    chat_id = callback_query.message.chat.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()
    matching_paused = await ctx.GetTgUser(chat_id, TgUser.matching_paused) or False

    from nespresso.bot.handlers.client.commands.hub import HubKeyboard

    try:
        await callback_query.message.edit_text(
            text=t(lang, "hub.welcome"),
            reply_markup=HubKeyboard(chat_id, lang, matching_paused=matching_paused),
        )
    except TelegramBadRequest:
        pass


@router.message(AboutStates.WriteAbout, F.content_type == "text")
async def AboutWriteAboutMessage(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    chat_id = message.chat.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()

    await ctx.UpdateTgUser(chat_id=chat_id, column=TgUser.about, value=message.text)
    await state.clear()

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "about.saved"),
    )

    from nespresso.bot.handlers.client.commands.hub import SendHub

    await SendHub(chat_id)
