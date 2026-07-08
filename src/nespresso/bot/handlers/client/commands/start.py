import logging
import time
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

from nespresso.api.request import EmailLookup, ResolveNesUserByEmail
from nespresso.bot.handlers.client.commands.about import RejectIfAboutTooLong
from nespresso.bot.handlers.client.email.verification import CreateCode, SendCode
from nespresso.bot.lib.message.checks import CheckVerified
from nespresso.bot.lib.message.i18n import (
    GetUserLanguage,
    GetUserLanguageOrNone,
    SetUserLanguage,
    t,
)
from nespresso.bot.lib.message.io import ContextIO, SendMessage
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.searching.profile_write import RebuildProfileForBio

router = Router()

# TODO: add bot's: picture, about, description, description picture


async def _DeleteMessageSafe(message: types.Message | None, chat_id: int) -> None:
    if message is None:
        return
    try:
        await message.delete()
    except Exception:
        logging.debug(
            f"Failed to delete message for chat_id={chat_id}",
            exc_info=True,
        )


class StartStates(StatesGroup):
    ChooseLanguage = State()
    EmailGet = State()
    EmailConfirm = State()
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

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "start.enter_email"),
    )
    await state.set_state(StartStates.EmailGet)


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

    # ReplyKeyboardRemove dismisses the EN/RU reply keyboard the moment a valid
    # language is picked (the next step adds its own keyboard / hub as needed).
    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "language.selected"),
        reply_markup=ReplyKeyboardRemove(),
    )

    if await CheckVerified(chat_id=chat_id):
        from nespresso.bot.handlers.client.commands.hub import SendHub

        await state.clear()
        await SendHub(chat_id)
        return

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "start.enter_email"),
    )
    await state.set_state(StartStates.EmailGet)


_EMAIL_COOLDOWN_SECONDS = 10 * 60


@router.message(StateFilter(StartStates.EmailGet), F.content_type == "text")
async def CommandStartEmailGet(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    chat_id = message.chat.id
    lang = await GetUserLanguage(chat_id)

    data = await state.get_data()
    cooldown_until = data.get("cooldown_until")
    if cooldown_until is not None and time.time() < cooldown_until:
        remaining = int((cooldown_until - time.time()) // 60) + 1
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.email_cooldown", minutes=remaining),
            context=ContextIO.UserFailed,
        )
        return

    email = message.text.replace(" ", "").lower()

    if not email.endswith("@nes.ru"):
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
        text=t(lang, "start.checking_email"),
    )

    # Resolve email -> nes_id BEFORE emailing a code: DB-first (synced MyNES
    # directory), falling back to a single /user/byEmail call. A code is only
    # sent if the address belongs to a real, directory-shared NES alumnus.
    try:
        resolution = await ResolveNesUserByEmail(email)
    except Exception:
        # Only genuine transient failures (timeouts, 5xx) reach here — a real
        # 403/404 is classified by ResolveNesUserByEmail, not raised.
        logging.exception(
            f"ResolveNesUserByEmail failed for chat_id={chat_id}, email={email}"
        )
        await _DeleteMessageSafe(wait_message, chat_id)
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.email_check_failed"),
            context=ContextIO.UserFailed,
        )
        return

    await _DeleteMessageSafe(wait_message, chat_id)

    # 404: the email is unknown to NES — just ask the user to re-enter it.
    if resolution.status is EmailLookup.not_found:
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.email_not_in_nes"),
            context=ContextIO.UserFailed,
        )
        return

    # 403: a real alumnus whose profile isn't shared in the directory — give
    # them the actionable fix instead of a misleading "try again later".
    if resolution.status is EmailLookup.not_shared:
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.email_not_shared"),
            context=ContextIO.UserFailed,
        )
        return

    # status is `found`
    if not resolution.alumni or resolution.nes_id is None:
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.not_alumni"),
            context=ContextIO.UserFailed,
        )
        return

    nes_id = resolution.nes_id

    code = CreateCode()
    await SendCode(email=email, code=code)

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "start.sent_code"),
    )

    await state.set_data({"code": code, "attempts": 0, "nes_id": nes_id})
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
            cooldown_until = time.time() + _EMAIL_COOLDOWN_SECONDS
            remaining = _EMAIL_COOLDOWN_SECONDS // 60
            await SendMessage(
                chat_id=chat_id,
                text=t(lang, "start.code_attempts_exhausted", minutes=remaining),
                context=ContextIO.UserFailed,
            )
            await state.set_state(StartStates.EmailGet)
            await state.set_data({"cooldown_until": cooldown_until})
            return

        await state.update_data(attempts=attempts)
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.code_invalid"),
            context=ContextIO.UserFailed,
        )
        return

    # Existence + alumni were already verified at the EmailGet step, which stored
    # the resolved nes_id in FSM state — no MyNES API call is needed here.
    nes_id = data.get("nes_id")
    if nes_id is None:
        logging.error(
            f"EmailConfirm: missing nes_id in state for chat_id={chat_id}; "
            "restarting email step"
        )
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "start.email_check_failed"),
            context=ContextIO.UserFailed,
        )
        await state.set_state(StartStates.EmailGet)
        await state.set_data({})
        return

    ctx = await GetUserContextService()
    await ctx.UpdateTgUser(chat_id=chat_id, column=TgUser.nes_id, value=nes_id)
    # No terms-of-use step: a correct code completes registration outright.
    await ctx.UpdateTgUser(chat_id=chat_id, column=TgUser.verified, value=True)

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

    if await RejectIfAboutTooLong(message, lang):
        return  # stays in AboutNow so the user can resend a shorter bio

    ctx = await GetUserContextService()

    await ctx.UpdateTgUser(chat_id=chat_id, column=TgUser.about, value=message.text)
    await state.clear()

    nes_id = await ctx.GetTgUser(chat_id, TgUser.nes_id)
    if nes_id is not None:
        # Rebuild the whole unified profile doc (directory text + this bio) — the
        # bio is one part of a single indexed document now. Best-effort.
        await RebuildProfileForBio(nes_id, message.text)

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "about.saved"),
    )

    from nespresso.bot.handlers.client.commands.hub import SendHub

    await SendHub(chat_id)
