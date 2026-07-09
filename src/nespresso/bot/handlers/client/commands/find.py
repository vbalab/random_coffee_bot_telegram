import logging
import math
import time
import uuid
from enum import Enum

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from cachetools import TTLCache

from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import ContextIO, SendMessage
from nespresso.db.models.profile_reaction import ReactionKind
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.searching.preprocessing.embedding import CalculateTokenLen
from nespresso.recsys.searching.preprocessing.model import TOKEN_LEN, RunInference
from nespresso.recsys.searching.search import (
    SEARCHES,
    RegisterSearch,
    ScrollingSearch,
)

router = Router()

# Minimum gap between two searches from the same user. Find is the one
# interactive flow with no rate limit, and every query funnels through the
# shared single-worker inference executor (see model.py) plus an LLM parser
# call — without this, one user hammering the button degrades search latency
# for everyone else on the bot.
_SEARCH_COOLDOWN_SECONDS = 3.0
_last_search_at: TTLCache[int, float] = TTLCache(maxsize=10000, ttl=60)


def PercentageToReduce(token_len: int) -> int:
    result: int = math.ceil((token_len - TOKEN_LEN) / token_len * 10)
    return result * 10


class FindAction(str, Enum):
    Prev = "previous"
    Next = "next"
    # Per-profile actions panel (opened by the "•••" button on the result card).
    Actions = "actions"
    BackToProfile = "back_profile"
    Like = "like"
    Dislike = "dislike"
    Block = "block"


class FindCallbackData(CallbackData, prefix="find"):
    action: FindAction
    search_id: uuid.UUID


# Language-neutral "more options" affordance for the result card.
_MORE_ACTIONS_LABEL = "•••"


class FindStates(StatesGroup):
    Text = State()
    Forward = State()


def _FindButton(search_id: uuid.UUID, action: FindAction, text: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=FindCallbackData(action=action, search_id=search_id).pack(),
    )


def FindKeyboard(
    search_id: uuid.UUID,
    prev: bool = False,
    next: bool = False,
) -> InlineKeyboardMarkup:
    """Result-card keyboard: a full-width '•••' actions row on top, then the
    prev/next arrow row (arrows shown only where navigation is possible)."""
    rows: list[list[InlineKeyboardButton]] = [
        [_FindButton(search_id, FindAction.Actions, _MORE_ACTIONS_LABEL)]
    ]

    arrows: list[InlineKeyboardButton] = []
    if prev:
        arrows.append(_FindButton(search_id, FindAction.Prev, "⬅️"))
    if next:
        arrows.append(_FindButton(search_id, FindAction.Next, "➡️"))
    if arrows:
        rows.append(arrows)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def FindActionsKeyboard(
    lang: str, search_id: uuid.UUID, reaction: str | None
) -> InlineKeyboardMarkup:
    """Per-profile actions panel (same card text, different keyboard):
    like/dislike search-quality vote, hide-profile, and back-to-card."""
    like_text = t(lang, "find.action_like")
    dislike_text = t(lang, "find.action_dislike")
    if reaction == ReactionKind.Like.value:
        like_text = f"{like_text} ✅"
    elif reaction == ReactionKind.Dislike.value:
        dislike_text = f"{dislike_text} ✅"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _FindButton(search_id, FindAction.Like, like_text),
                _FindButton(search_id, FindAction.Dislike, dislike_text),
            ],
            [_FindButton(search_id, FindAction.Block, t(lang, "find.action_block"))],
            [_FindButton(search_id, FindAction.BackToProfile, t(lang, "find.action_back"))],
        ]
    )


@router.message(StateFilter(FindStates.Text), F.content_type == "text")
async def CommandFindText(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    chat_id = message.chat.id
    lang = await GetUserLanguage(chat_id)

    now = time.monotonic()
    last_search = _last_search_at.get(chat_id)
    if last_search is not None and now - last_search < _SEARCH_COOLDOWN_SECONDS:
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "find.rate_limited"),
            context=ContextIO.UserFailed,
        )
        return
    _last_search_at[chat_id] = now

    # Off the event loop AND serialized with every other tokenizer/encoder call
    # via the shared single-worker executor — calling CalculateTokenLen directly
    # here would race the same non-thread-safe tokenizer used by the encoder
    # thread for other users' concurrent searches (see model.py).
    token_len = await RunInference(CalculateTokenLen, message.text)
    if token_len > TOKEN_LEN:
        await SendMessage(
            chat_id=chat_id,
            text=t(
                lang,
                "find.too_long",
                percent=PercentageToReduce(token_len),
            ),
            context=ContextIO.UserFailed,
        )
        return

    searching_message = await SendMessage(
        chat_id=message.chat.id,
        text=t(lang, "find.searching"),
    )

    ctx = await GetUserContextService()
    nes_id: int | None = await ctx.GetTgUser(message.chat.id, TgUser.nes_id)
    # Profiles this user hid via the actions panel must never resurface in a
    # fresh search — excluded at retrieval time alongside the user themselves.
    blocked_nes_ids = set(await ctx.GetBlockedTargetNesIds(message.chat.id))

    search = ScrollingSearch(exclude_nes_id=nes_id, blocked_nes_ids=blocked_nes_ids)
    page = await search.HybridSearch(message)

    # The "searching, please wait" message was only a progress indicator — remove
    # it now that the search is done.
    if searching_message is not None:
        try:
            await searching_message.delete()
        except Exception:
            logging.debug(
                f"Failed to delete searching message for chat_id={message.chat.id}",
                exc_info=True,
            )

    if page is None:
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "find.not_found"),
        )
        await state.clear()
        return

    search_id = uuid.uuid4()
    RegisterSearch(chat_id, search_id, search)

    await SendMessage(
        chat_id=message.chat.id,
        text=search.CurrentText(),
        reply_markup=FindKeyboard(
            search_id=search_id, next=search.CanScrollFurtherForward()
        ),
        parse_mode="HTML",
    )

    await state.clear()


async def _RenderProfileView(
    callback_query: types.CallbackQuery,
    search: ScrollingSearch,
    search_id: uuid.UUID,
) -> None:
    """Edit the message to the current page's profile card + card keyboard."""
    assert isinstance(callback_query.message, types.Message)

    text = search.CurrentText()
    logging.info(f"chat_id={callback_query.from_user.id}  (scroll)  << {text!r}")

    await callback_query.message.edit_text(
        text=text,
        reply_markup=FindKeyboard(
            search_id=search_id,
            prev=search.CanScrollFurtherBackward(),
            next=search.CanScrollFurtherForward(),
        ),
        parse_mode="HTML",
    )


async def _HandleScroll(
    callback_query: types.CallbackQuery,
    lang: str,
    search: ScrollingSearch,
    search_id: uuid.UUID,
    action: FindAction,
) -> None:
    assert isinstance(callback_query.message, types.Message)

    if action is FindAction.Prev:
        page = await search.ScrollBackward()
        if page is None:
            await callback_query.message.edit_reply_markup(
                reply_markup=FindKeyboard(
                    search_id=search_id, next=search.CanScrollFurtherForward()
                )
            )
            await callback_query.answer(t(lang, "find.no_more_pages"))
            return
    else:
        page = await search.ScrollForward()
        if page is None:
            await callback_query.message.edit_reply_markup(
                reply_markup=FindKeyboard(search_id=search_id, prev=search.index > 0)
            )
            await callback_query.answer(t(lang, "find.no_more_pages"))
            return

    await _RenderProfileView(callback_query, search, search_id)
    await callback_query.answer()


async def _OpenActionsPanel(
    callback_query: types.CallbackQuery,
    lang: str,
    search: ScrollingSearch,
    search_id: uuid.UUID,
) -> None:
    """Swap only the keyboard (card text unchanged) to the actions panel."""
    assert isinstance(callback_query.message, types.Message)

    ctx = await GetUserContextService()
    nes_id = search.CurrentProfileNesId()
    reaction = await ctx.GetProfileReaction(callback_query.from_user.id, nes_id)

    await callback_query.message.edit_reply_markup(
        reply_markup=FindActionsKeyboard(lang, search_id, reaction)
    )
    await callback_query.answer()


async def _BackToProfile(
    callback_query: types.CallbackQuery,
    search: ScrollingSearch,
    search_id: uuid.UUID,
) -> None:
    """Restore the card keyboard (card text unchanged)."""
    assert isinstance(callback_query.message, types.Message)

    await callback_query.message.edit_reply_markup(
        reply_markup=FindKeyboard(
            search_id=search_id,
            prev=search.CanScrollFurtherBackward(),
            next=search.CanScrollFurtherForward(),
        )
    )
    await callback_query.answer()


async def _HandleReaction(
    callback_query: types.CallbackQuery,
    lang: str,
    search: ScrollingSearch,
    search_id: uuid.UUID,
    action: FindAction,
) -> None:
    """Record/toggle a like/dislike (analytics-only) and re-render the panel."""
    assert isinstance(callback_query.message, types.Message)

    ctx = await GetUserContextService()
    chat_id = callback_query.from_user.id
    nes_id = search.CurrentProfileNesId()

    kind = ReactionKind.Like if action is FindAction.Like else ReactionKind.Dislike
    current = await ctx.GetProfileReaction(chat_id, nes_id)
    # Toggle: tapping the already-selected vote clears it; otherwise switch to it.
    new_reaction = None if current == kind.value else kind.value
    await ctx.SetProfileReaction(chat_id, nes_id, new_reaction)

    try:
        await callback_query.message.edit_reply_markup(
            reply_markup=FindActionsKeyboard(lang, search_id, new_reaction)
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await callback_query.answer(t(lang, "find.reaction_saved"))


async def _HandleBlock(
    callback_query: types.CallbackQuery,
    lang: str,
    search: ScrollingSearch,
    search_id: uuid.UUID,
) -> None:
    """Hide this profile for the user, then advance past it."""
    assert isinstance(callback_query.message, types.Message)

    ctx = await GetUserContextService()
    chat_id = callback_query.from_user.id
    nes_id = search.CurrentProfileNesId()
    await ctx.SetProfileBlocked(chat_id, nes_id, True)
    await callback_query.answer(t(lang, "find.profile_hidden"))

    # Advance off the just-hidden card: forward if possible, else backward, else
    # (it was the only result) clear the card entirely.
    page = await search.ScrollForward()
    if page is None:
        page = await search.ScrollBackward()
    if page is None:
        await callback_query.message.edit_text(text=t(lang, "find.all_hidden"))
        return

    await _RenderProfileView(callback_query, search, search_id)


@router.callback_query(FindCallbackData.filter())
async def CommandFindCallback(
    callback_query: types.CallbackQuery,
    callback_data: FindCallbackData,
) -> None:
    assert isinstance(callback_query.message, types.Message)

    lang = await GetUserLanguage(callback_query.from_user.id)

    search_id = callback_data.search_id
    search: ScrollingSearch | None = SEARCHES.get(search_id, None)

    if search is None:
        await callback_query.message.edit_reply_markup(reply_markup=None)
        await callback_query.answer(t(lang, "find.search_expired"))
        return

    action = callback_data.action
    if action in (FindAction.Prev, FindAction.Next):
        await _HandleScroll(callback_query, lang, search, search_id, action)
    elif action is FindAction.Actions:
        await _OpenActionsPanel(callback_query, lang, search, search_id)
    elif action is FindAction.BackToProfile:
        await _BackToProfile(callback_query, search, search_id)
    elif action in (FindAction.Like, FindAction.Dislike):
        await _HandleReaction(callback_query, lang, search, search_id, action)
    elif action is FindAction.Block:
        await _HandleBlock(callback_query, lang, search, search_id)
