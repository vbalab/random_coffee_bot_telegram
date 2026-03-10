import logging

from aiogram import F, Router, types
from aiogram.filters.command import Command
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from nespresso.bot.handlers.client.email.verification import CreateCode
from nespresso.bot.lib.message.checks import CheckVerified
from nespresso.bot.lib.message.i18n import (
    GetUserLanguage,
    GetUserLanguageOrNone,
    SetUserLanguage,
    t,
)
from nespresso.bot.lib.message.io import ContextIO, SendDocument, SendMessage
from nespresso.core.configs.paths import PATH_TERMS_OF_USE
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

router = Router()

# TODO: add bot's: picture, about, description, description picture


class StartStates(StatesGroup):
    ChooseLanguage = State()
    GetPhoneNumber = State()
    EmailGet = State()
    EmailConfirm = State()
    Terms = State()


def LanguageKeyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("en", "language.english"))],
            [KeyboardButton(text=t("en", "language.russian"))],
        ],
        resize_keyboard=True,
    )


async def AskForContact(chat_id: int, lang: str) -> None:
    button = KeyboardButton(
        text=t(lang, "start.share_contact_button"),
        request_contact=True,
    )
    keyboard = ReplyKeyboardMarkup(keyboard=[[button]], resize_keyboard=True)

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "start.share_contact"),
        reply_markup=keyboard,
    )


@router.message(StateFilter(None), Command("start"))
async def CommandStart(message: types.Message, state: FSMContext) -> None:
    chat_id = message.chat.id

    if await GetUserLanguageOrNone(chat_id) is None:
        await SendMessage(
            chat_id=chat_id,
            text=t("en", "language.choose"),
            reply_markup=LanguageKeyboard(),
        )
        await state.set_state(StartStates.ChooseLanguage)
        return

    lang = await GetUserLanguage(chat_id)

    if await CheckVerified(chat_id=chat_id):
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.already_registered"),
        )
        return

    await AskForContact(chat_id, lang)
    await state.set_state(StartStates.GetPhoneNumber)


@router.message(StateFilter(StartStates.ChooseLanguage), F.content_type == "text")
async def CommandStartChooseLanguage(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    chat_id = message.chat.id

    english = t("en", "language.english")
    russian = t("en", "language.russian")

    if message.text == english:
        await SetUserLanguage(chat_id, "en")
    elif message.text == russian:
        await SetUserLanguage(chat_id, "ru")
    else:
        await SendMessage(
            chat_id=chat_id,
            text=t("en", "language.unsupported"),
            context=ContextIO.UserFailed,
        )
        return

    lang = await GetUserLanguage(chat_id)

    await SendMessage(chat_id=chat_id, text=t(lang, "language.selected"))

    if await CheckVerified(chat_id=chat_id):
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.already_registered"),
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.clear()
        return

    await AskForContact(chat_id, lang)
    await state.set_state(StartStates.GetPhoneNumber)


@router.message(StateFilter(StartStates.GetPhoneNumber))
async def CommandStartGetPhoneNumber(message: types.Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    lang = await GetUserLanguage(chat_id)

    if message.contact is None:
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.contact_missing"),
            context=ContextIO.UserFailed,
        )
        return

    if message.contact.user_id is None or message.from_user is None:
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.contact_unavailable"),
            context=ContextIO.UserFailed,
        )
        return

    if message.contact.user_id != message.from_user.id:
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.contact_foreign"),
            context=ContextIO.UserFailed,
        )
        return

    ctx = await GetUserContextService()
    await ctx.UpdateTgUser(
        chat_id=chat_id,
        column=TgUser.phone_number,
        value=message.contact.phone_number,
    )

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "common.thanks"),
        reply_markup=ReplyKeyboardRemove(),
    )

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "start.enter_email"),
    )

    await state.set_state(StartStates.EmailGet)


@router.message(StateFilter(StartStates.EmailGet), F.content_type == "text")
async def CommandStartEmailGet(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    chat_id = message.chat.id
    lang = await GetUserLanguage(chat_id)
    email = message.text.replace(" ", "")

    if "@nes.ru" not in email:
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.email_invalid"),
            context=ContextIO.UserFailed,
        )
        return

    ctx = await GetUserContextService()
    await ctx.UpdateTgUser(
        chat_id=chat_id,
        column=TgUser.nes_email,
        value=email,
    )

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "start.sending_code"),
    )

    code = CreateCode()
    logging.info(f"Sending code '{code}' to '{email}'")
    # TODO: uncomment
    # await SendCode(email=email, code=code)

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "start.sent_code"),
    )

    await state.set_data({"code": code})
    await state.set_state(StartStates.EmailConfirm)


@router.message(StateFilter(StartStates.EmailConfirm), F.content_type == "text")
async def CommandStartEmailConfirm(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    chat_id = message.chat.id
    lang = await GetUserLanguage(chat_id)

    data = await state.get_data()
    code_actual = str(data["code"])
    code_provided = message.text.replace(" ", "")

    if code_actual != code_provided:
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.code_invalid"),
            context=ContextIO.UserFailed,
        )
        return

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "common.thanks"),
    )

    button = KeyboardButton(text=t(lang, "start.accept_button"))
    keyboard = ReplyKeyboardMarkup(keyboard=[[button]], resize_keyboard=True)

    # TODO: create actual service of service
    await SendDocument(
        chat_id=chat_id,
        document=types.FSInputFile(PATH_TERMS_OF_USE),
        caption=t(lang, "start.terms_caption"),
        reply_markup=keyboard,
    )

    await state.set_state(StartStates.Terms)
    await state.set_data({"button_text": button.text})


@router.message(StateFilter(StartStates.Terms), F.content_type == "text")
async def CommandStartTerms(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    chat_id = message.chat.id
    lang = await GetUserLanguage(chat_id)
    data = await state.get_data()

    if message.text != data["button_text"]:
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.terms_not_accepted"),
            context=ContextIO.UserFailed,
        )
        return

    ctx = await GetUserContextService()
    await ctx.UpdateTgUser(
        chat_id=chat_id,
        column=TgUser.verified,
        value=True,
    )

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "start.verified"),
    )

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "start.about"),
    )

    await state.clear()
