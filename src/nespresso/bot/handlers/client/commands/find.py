import math
import uuid
from enum import Enum

from aiogram import F, Router, types
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.command import Command
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.bot.lib.message.checks import CheckVerified
from nespresso.bot.lib.message.i18n import t_user
from nespresso.bot.lib.message.io import ContextIO, SendMessage
from nespresso.recsys.searching.preprocessing.embedding import CalculateTokenLen
from nespresso.recsys.searching.preprocessing.model import TOKEN_LEN
from nespresso.recsys.searching.search import SEARCHES, Page, ScrollingSearch

router = Router()


def PercentageToReduce(text: str) -> int:
    length = CalculateTokenLen(text)

    result: int = math.ceil((length - TOKEN_LEN) / length * 10)
    return result * 10


class FindAction(str, Enum):
    Prev = "previous"
    Next = "next"


class FindCallbackData(CallbackData, prefix="find"):
    action: FindAction
    search_id: uuid.UUID


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


class FindStates(StatesGroup):
    Text = State()
    Forward = State()


@router.message(StateFilter(None), Command("find"))
async def CommandFind(message: types.Message, state: FSMContext) -> None:
    if not await CheckVerified(chat_id=message.chat.id):
        await SendMessage(
            chat_id=message.chat.id,
            text=await t_user(message.chat.id, "find.only_registered"),
        )
        return

    await SendMessage(
        chat_id=message.chat.id,
        text=await t_user(message.chat.id, "find.enter_query"),
    )
    await state.set_state(FindStates.Text)


@router.message(StateFilter(FindStates.Text), F.content_type == "text")
async def CommandFindText(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    if CalculateTokenLen(message.text) > TOKEN_LEN:
        await SendMessage(
            chat_id=message.chat.id,
            text=await t_user(
                message.chat.id,
                "find.too_long",
                percent=PercentageToReduce(message.text),
            ),
            context=ContextIO.UserFailed,
        )
        return

    await SendMessage(
        chat_id=message.chat.id,
        text=await t_user(message.chat.id, "find.searching"),
    )

    search = ScrollingSearch()
    page = await search.HybridSearch(message)

    if page is None:
        await SendMessage(
            chat_id=message.chat.id,
            text=await t_user(message.chat.id, "find.not_found"),
        )
        await state.clear()
        return

    search_id = uuid.uuid4()
    SEARCHES[search_id] = search

    await SendMessage(
        chat_id=message.chat.id,
        text=page.GetFormattedText(),
        reply_markup=FindKeyboard(search_id=search_id, next=True),
    )

    await state.clear()


@router.callback_query(FindCallbackData.filter())
async def CommandFindCallback(
    callback_query: types.CallbackQuery,
    callback_data: FindCallbackData,
) -> None:
    assert isinstance(callback_query.message, types.Message)

    search_id = callback_data.search_id
    search: ScrollingSearch | None = SEARCHES.get(search_id, None)

    if search is None:
        await callback_query.message.edit_reply_markup(reply_markup=None)
        await callback_query.answer(
            await t_user(callback_query.from_user.id, "find.search_expired")
        )

        return

    page: Page | None
    if callback_data.action == FindAction.Prev:
        page = await search.ScrollBackward()
    else:
        page = await search.ScrollForward()

        if page is None:
            await callback_query.message.edit_reply_markup(
                reply_markup=FindKeyboard(
                    search_id=search_id,
                    prev=search.index > 0,
                )
            )
            await callback_query.answer(
                await t_user(callback_query.from_user.id, "find.no_more_pages")
            )

            return

    markup = FindKeyboard(
        search_id=search_id,
        prev=search.CanScrollFurtherBackward(),
        next=search.CanScrollFurtherForward(),
    )

    await callback_query.message.edit_text(
        text=page.GetFormattedText(),
        reply_markup=markup,
    )
    await callback_query.answer()
