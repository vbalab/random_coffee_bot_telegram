import logging
from enum import Enum

from aiogram import F, Router, types
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.command import Command
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from nespresso.api.request import GetNesUserFromMyNES
from nespresso.bot.handlers.client.email.verification import CreateCode, SendCode
from nespresso.bot.lib.chat.username import GetTgUsername
from nespresso.bot.lib.message.checks import CheckVerified
from nespresso.bot.lib.message.i18n import (
    GetUserLanguage,
    GetUserLanguageOrNone,
    SetUserLanguage,
    t,
)
from nespresso.bot.lib.message.io import ContextIO, SendDocument, SendMessage
from nespresso.core.configs.admin_store import GetAdminIds
from nespresso.core.configs.paths import PATH_TERMS_OF_USE
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.searching.document import UpsertAboutOpenSearch

router = Router()

# TODO: add bot's: picture, about, description, description picture


class StartStates(StatesGroup):
    ChooseLanguage = State()
    GetPhoneNumber = State()
    EmailGet = State()
    EmailConfirm = State()
    Terms = State()
    AboutNow = State()


class StartAboutAction(str, Enum):
    WriteNow = "write_now"
    WriteLater = "write_later"


class StartAboutCallbackData(CallbackData, prefix="start_about"):
    action: StartAboutAction


def StartAboutKeyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "start.about_write_now"),
                    callback_data=StartAboutCallbackData(
                        action=StartAboutAction.WriteNow
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "start.about_write_later"),
                    callback_data=StartAboutCallbackData(
                        action=StartAboutAction.WriteLater
                    ).pack(),
                )
            ],
        ]
    )


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
        # Lazy import to avoid circular dependency with hub
        from nespresso.bot.handlers.client.commands.hub import SendHub

        await SendHub(chat_id)
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
        from nespresso.bot.handlers.client.commands.hub import SendHub

        await SendMessage(
            chat_id=chat_id, reply_markup=ReplyKeyboardRemove(), text="\u200b"
        )
        await state.clear()
        await SendHub(chat_id)
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

    existing_chat_id = await ctx.GetTgChatIdBy(nes_email=email)
    if existing_chat_id is not None and existing_chat_id != chat_id:
        is_verified = await ctx.GetTgUser(existing_chat_id, TgUser.verified)
        if is_verified:
            await SendMessage(
                chat_id=chat_id,
                text=t(lang, "start.email_taken"),
                context=ContextIO.UserFailed,
            )
            return

    await ctx.UpdateTgUser(
        chat_id=chat_id,
        column=TgUser.nes_email,
        value=email,
    )

    wait_message = await SendMessage(
        chat_id=chat_id,
        text=t(lang, "start.sending_code"),
    )

    code = CreateCode()
    await SendCode(email=email, code=code)

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "start.sent_code"),
    )

    if wait_message is not None:
        try:
            await wait_message.delete()
        except Exception:
            logging.debug(
                f"Failed to delete wait message for chat_id={chat_id}",
                exc_info=True,
            )

    await state.set_data({"code": code, "attempts": 0})
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
        attempts = data.get("attempts", 0) + 1

        if attempts >= 3:
            await SendMessage(
                chat_id=chat_id,
                text=t(lang, "start.code_attempts_exhausted"),
                context=ContextIO.UserFailed,
            )
            await state.clear()
            await state.set_state(StartStates.EmailGet)
            await SendMessage(
                chat_id=chat_id,
                text=t(lang, "start.enter_email"),
            )
            return

        await state.update_data(attempts=attempts)
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.code_invalid"),
            context=ContextIO.UserFailed,
        )
        return

    ctx = await GetUserContextService()
    nes_email = await ctx.GetTgUser(chat_id, TgUser.nes_email)

    try:
        nes_user = await GetNesUserFromMyNES(nes_email)
    except Exception:
        logging.exception(
            f"GetNesUserFromMyNES raised an exception for chat_id={chat_id}, email={nes_email}"
        )
        nes_user = None

    if nes_user is None:
        username = await GetTgUsername(chat_id) or str(chat_id)
        admin_text = t(
            "en",
            "start.email_not_in_nes_admin",
            username=username,
            chat_id=chat_id,
            email=nes_email or "",
        )
        for admin_id in await GetAdminIds():
            await SendMessage(chat_id=admin_id, text=admin_text)

        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.email_not_in_nes"),
            context=ContextIO.UserFailed,
        )
        await state.set_state(StartStates.EmailGet)
        return

    if not nes_user.alumni:
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.not_alumni"),
            context=ContextIO.UserFailed,
        )
        await state.set_state(StartStates.EmailGet)
        return

    await ctx.UpdateTgUser(chat_id=chat_id, column=TgUser.nes_id, value=nes_user.nes_id)

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
        reply_markup=ReplyKeyboardRemove(),
    )

    await state.set_state(StartStates.AboutNow)
    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "start.about_prompt"),
        reply_markup=StartAboutKeyboard(lang),
    )


@router.callback_query(
    StartAboutCallbackData.filter(F.action == StartAboutAction.WriteNow)
)
async def StartAboutWriteNow(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)

    try:
        await callback_query.message.delete()
    except Exception:
        logging.debug(
            f"Failed to delete about-prompt message for chat_id={chat_id}",
            exc_info=True,
        )

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "about.enter_text"),
    )
    await state.set_state(StartStates.AboutNow)


@router.callback_query(
    StartAboutCallbackData.filter(F.action == StartAboutAction.WriteLater)
)
async def StartAboutWriteLater(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await state.clear()

    try:
        await callback_query.message.delete()
    except Exception:
        logging.debug(
            f"Failed to delete about-prompt message for chat_id={callback_query.from_user.id}",
            exc_info=True,
        )

    from nespresso.bot.handlers.client.commands.hub import SendHub

    await SendHub(callback_query.from_user.id)


@router.message(StateFilter(StartStates.AboutNow), F.content_type == "text")
async def StartAboutNowMessage(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    chat_id = message.chat.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()

    await ctx.UpdateTgUser(chat_id=chat_id, column=TgUser.about, value=message.text)
    await state.clear()

    nes_id = await ctx.GetTgUser(chat_id, TgUser.nes_id)
    if nes_id is not None:
        await UpsertAboutOpenSearch(nes_id, message.text)

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "about.saved"),
    )

    from nespresso.bot.handlers.client.commands.hub import SendHub

    await SendHub(chat_id)
