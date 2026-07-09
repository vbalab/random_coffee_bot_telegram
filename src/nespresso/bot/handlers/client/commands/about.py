import html
import logging
from enum import Enum

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import ContextIO, SendMessage
from nespresso.core.configs.title_store import GetTitle
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.profile import Profile
from nespresso.recsys.searching.profile_write import RebuildProfileForBio

router = Router()

# Max characters for a user-written bio. Bounds the one unbounded input to the
# profile vector: keeps directory text + bio + enrichment comfortably under the
# embedding's 2048-token cap (the directory side alone is ~683 tokens at most),
# and stops a very long bio from dominating the profile embedding. Enforced at
# BOTH bio-input sites — registration (`StartStates.AboutNow`) and this About
# panel (`AboutStates.WriteAbout`) — via `RejectIfAboutTooLong`.
MAX_ABOUT_CHARS = 1500

# `about` is HTML-escaped before being woven into another user's profile card
# (see Profile.DescribeProfile, sent with parse_mode="HTML") — `<`, `>`, `&`
# etc. each expand to several characters, so a bio within MAX_ABOUT_CHARS raw
# could still balloon past Telegram's 4096-char message cap once escaped,
# silently failing to send that profile card to whoever looked this person up.
_MAX_ABOUT_ESCAPED_CHARS = 3000


async def RejectIfAboutTooLong(message: types.Message, lang: str) -> bool:
    """
    If the submitted bio exceeds `MAX_ABOUT_CHARS` (raw) or would exceed the
    escaped-length budget once HTML-escaped, reply with the user's current
    character count and the limit and return True; the caller then returns
    WITHOUT clearing FSM state, so the user stays in the bio-writing step and can
    simply send a shorter version. Returns False when the bio is within both caps.
    """
    text = message.text or ""
    if len(text) <= MAX_ABOUT_CHARS and len(html.escape(text)) <= _MAX_ABOUT_ESCAPED_CHARS:
        return False
    await SendMessage(
        chat_id=message.chat.id,
        text=t(lang, "about.too_long", current=len(text), max=MAX_ABOUT_CHARS),
        context=ContextIO.UserFailed,
    )
    return True


class AboutStates(StatesGroup):
    WriteAbout = State()


class AboutAction(str, Enum):
    WriteNew = "write_new"
    Preview = "preview"
    Back = "back"


class AboutCallbackData(CallbackData, prefix="about"):
    action: AboutAction


def BuildAboutPanelContent(
    lang: str, about: str | None
) -> tuple[str, types.InlineKeyboardMarkup]:
    current = about if about else t(lang, "about.not_set")
    text = t(lang, "about.panel_header", current=current)
    # Minimal "complete your bio" nudge: only shown when the bio is still empty,
    # right where the "Write new about" button is, so it's actionable in place.
    if not about:
        text += "\n\n" + t(lang, "about.complete_tip")
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
                    text=t(lang, "about.button_preview"),
                    callback_data=AboutCallbackData(action=AboutAction.Preview).pack(),
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


@router.callback_query(AboutCallbackData.filter(F.action == AboutAction.Preview))
async def AboutPreviewCallback(callback_query: types.CallbackQuery) -> None:
    """Show the user the exact profile card other alumni see for them (the same
    Profile.DescribeProfile() rendered in Find). Sent as a separate message so the
    About panel stays put."""
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()

    nes_id = await ctx.GetTgUser(chat_id, TgUser.nes_id)
    if nes_id is None:
        await SendMessage(chat_id=chat_id, text=t(lang, "about.preview_no_profile"))
        return

    profile = await Profile.FromNesId(nes_id)
    text = f"{t(lang, 'about.preview_header')}\n\n{profile.DescribeProfile()}"
    await SendMessage(chat_id=chat_id, text=text, parse_mode="HTML")


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
    is_admin = await ctx.GetTgUser(chat_id, TgUser.is_admin) or False

    from nespresso.bot.handlers.client.commands.hub import HubKeyboard

    try:
        await callback_query.message.edit_text(
            text=GetTitle(lang),
            reply_markup=HubKeyboard(lang, is_admin),
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.warning(f"Failed to edit about→hub for chat_id={chat_id}: {e}")


@router.message(AboutStates.WriteAbout, F.content_type == "text")
async def AboutWriteAboutMessage(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    chat_id = message.chat.id
    lang = await GetUserLanguage(chat_id)

    if await RejectIfAboutTooLong(message, lang):
        return  # stays in WriteAbout so the user can resend a shorter bio

    ctx = await GetUserContextService()

    await ctx.UpdateTgUser(chat_id=chat_id, column=TgUser.about, value=message.text)
    await state.clear()

    nes_id = await ctx.GetTgUser(chat_id, TgUser.nes_id)
    if nes_id is not None:
        # Rebuild the whole unified profile doc (directory text + this bio) — the
        # bot's bio is one part of a single indexed document now, not a separate
        # "cv side". Best-effort: failures self-heal on the next sync.
        await RebuildProfileForBio(nes_id, message.text)

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "about.saved"),
    )

    from nespresso.bot.handlers.client.commands.hub import SendHub

    await SendHub(chat_id)
