import logging
import math
import time
import uuid
from enum import Enum

from aiogram import F, Router, types
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from cachetools import TTLCache

from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import ContextIO, SendMessage
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.searching.preprocessing.embedding import CalculateTokenLen
from nespresso.recsys.searching.preprocessing.model import TOKEN_LEN, RunInference
from nespresso.recsys.searching.search import (
    SEARCHES,
    Page,
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


class FindCallbackData(CallbackData, prefix="find"):
    action: FindAction
    search_id: uuid.UUID


class FindStates(StatesGroup):
    Text = State()
    Forward = State()


def FindKeyboard(
    search_id: uuid.UUID,
    prev: bool = False,
    next: bool = False,
) -> InlineKeyboardMarkup | None:
    def Button(action: FindAction) -> InlineKeyboardButton:
        nonlocal search_id

        callback_data = FindCallbackData(action=action, search_id=search_id).pack()

        return InlineKeyboardButton(
            text="⬅️" if action is FindAction.Prev else "➡️",
            callback_data=callback_data,
        )

    buttons: list[InlineKeyboardButton] = []

    if prev:
        buttons.append(Button(FindAction.Prev))
    if next:
        buttons.append(Button(FindAction.Next))

    if not buttons:
        return None

    return InlineKeyboardMarkup(inline_keyboard=[buttons])


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

    search = ScrollingSearch(exclude_nes_id=nes_id)
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

    page: Page | None
    if callback_data.action == FindAction.Prev:
        page = await search.ScrollBackward()

        if page is None:
            await callback_query.message.edit_reply_markup(
                reply_markup=FindKeyboard(
                    search_id=search_id,
                    next=search.CanScrollFurtherForward(),
                )
            )
            await callback_query.answer(t(lang, "find.no_more_pages"))

            return
    else:
        page = await search.ScrollForward()

        if page is None:
            await callback_query.message.edit_reply_markup(
                reply_markup=FindKeyboard(
                    search_id=search_id,
                    prev=search.index > 0,
                )
            )
            await callback_query.answer(t(lang, "find.no_more_pages"))

            return

    markup = FindKeyboard(
        search_id=search_id,
        prev=search.CanScrollFurtherBackward(),
        next=search.CanScrollFurtherForward(),
    )

    text = search.CurrentText()
    logging.info(
        f"chat_id={callback_query.from_user.id}  (scroll)  << {text!r}"
    )

    await callback_query.message.edit_text(
        text=text,
        reply_markup=markup,
        parse_mode="HTML",
    )
    await callback_query.answer()
