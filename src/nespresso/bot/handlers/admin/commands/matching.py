from enum import Enum
from typing import Any

from aiogram import F, Router, types
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.bot.handlers.admin.commands.back import BackToAdminPanelCallbackData
from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.recsys.matching.schedule import (
    GetNextMatchingTime,
    PauseMatching,
    ResumeMatching,
)

router = Router()


class MatchingAction(str, Enum):
    Pause = "pause"
    Resume = "resume"
    Leave = "leave"


class MatchingCallbackData(CallbackData, prefix="matching"):
    action: MatchingAction


def MatchingKeyboard(lang: str, actions: list[MatchingAction]) -> InlineKeyboardMarkup:
    _labels = {
        MatchingAction.Pause: "admin.matching_button_pause",
        MatchingAction.Resume: "admin.matching_button_resume",
        MatchingAction.Leave: "admin.matching_button_leave",
    }

    def Button(action: MatchingAction) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=t(lang, _labels[action]),
            callback_data=MatchingCallbackData(action=action).pack(),
        )

    back_button = InlineKeyboardButton(
        text=t(lang, "admin.button_back"),
        callback_data=BackToAdminPanelCallbackData().pack(),
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[[Button(a) for a in actions], [back_button]]
    )


def ShowMatchingPanel(lang: str) -> dict[str, Any]:
    """Return kwargs for edit_text to display the matching panel."""
    next_run_time = GetNextMatchingTime()

    if next_run_time is None:
        text = t(lang, "admin.matching_paused")
        keyboard = MatchingKeyboard(lang, [MatchingAction.Resume, MatchingAction.Leave])
    else:
        text = t(lang, "admin.matching_active", next_run=next_run_time.isoformat())
        keyboard = MatchingKeyboard(lang, [MatchingAction.Pause, MatchingAction.Leave])

    return {"text": text, "reply_markup": keyboard}


@router.callback_query(MatchingCallbackData.filter(F.action == MatchingAction.Resume))
async def CommandMatchingResume(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)

    ResumeMatching()
    next_run = GetNextMatchingTime()
    assert next_run is not None

    lang = await GetUserLanguage(callback_query.from_user.id)
    await callback_query.message.edit_text(
        text=t(lang, "admin.matching_resumed", next_run=next_run.isoformat()),
        reply_markup=MatchingKeyboard(lang, [MatchingAction.Pause, MatchingAction.Leave]),
    )
    await callback_query.answer(t(lang, "admin.matching_answer_resumed"))


@router.callback_query(MatchingCallbackData.filter(F.action == MatchingAction.Pause))
async def CommandMatchingPause(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)

    PauseMatching()

    lang = await GetUserLanguage(callback_query.from_user.id)
    await callback_query.message.edit_text(
        text=t(lang, "admin.matching_paused_confirmed"),
        reply_markup=MatchingKeyboard(lang, [MatchingAction.Resume, MatchingAction.Leave]),
    )
    await callback_query.answer(t(lang, "admin.matching_answer_paused"))


@router.callback_query(MatchingCallbackData.filter(F.action == MatchingAction.Leave))
async def CommandMatchingCancel(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)

    lang = await GetUserLanguage(callback_query.from_user.id)
    await callback_query.message.edit_reply_markup(reply_markup=None)
    await callback_query.answer(t(lang, "admin.matching_answer_leave"))
