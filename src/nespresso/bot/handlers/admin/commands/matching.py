import asyncio
import logging
from enum import Enum
from typing import Any

from aiogram import F, Router, types
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.bot.handlers.admin.commands.back import BackToAdminPanelCallbackData
from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import PersonalMsg, SendMessage, SendMessagesToGroup
from nespresso.core.configs.admin_store import GetAdminIds
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.matching.schedule import RunMatching

router = Router()


class MatchingAction(str, Enum):
    Run = "run"
    Feedback = "feedback"


class MatchingCallbackData(CallbackData, prefix="matching"):
    action: MatchingAction


class FeedbackCallbackData(CallbackData, prefix="match_fb"):
    assignment_id: int
    response: str


def MatchingKeyboard(lang: str) -> InlineKeyboardMarkup:
    back_button = InlineKeyboardButton(
        text=t(lang, "admin.button_back"),
        callback_data=BackToAdminPanelCallbackData().pack(),
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "admin.matching_button_run"),
                    callback_data=MatchingCallbackData(action=MatchingAction.Run).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "admin.matching_button_feedback"),
                    callback_data=MatchingCallbackData(
                        action=MatchingAction.Feedback
                    ).pack(),
                )
            ],
            [back_button],
        ]
    )


def ShowMatchingPanel(lang: str) -> dict[str, Any]:
    return {
        "text": t(lang, "admin.matching_header"),
        "reply_markup": MatchingKeyboard(lang),
    }


async def _NotifyOtherAdmins(actor_chat_id: int, key: str, **kwargs: Any) -> None:
    other_admins = [aid for aid in await GetAdminIds() if aid != actor_chat_id]
    if not other_admins:
        return

    actor_lang = await GetUserLanguage(actor_chat_id)
    actor_name = f"[{actor_chat_id}]"
    try:
        from nespresso.bot.lib.chat.username import GetTgUsername
        username = await GetTgUsername(actor_chat_id)
        if username:
            actor_name = f"@{username}"
    except Exception:
        logging.debug(f"Failed to get username for actor chat_id={actor_chat_id}", exc_info=True)

    messages: list[PersonalMsg] = []
    for admin_id in other_admins:
        lang = await GetUserLanguage(admin_id)
        text = t(lang, key, actor=actor_name, **kwargs)
        messages.append(PersonalMsg(chat_id=admin_id, text=text))

    await SendMessagesToGroup(messages)


@router.callback_query(MatchingCallbackData.filter(F.action == MatchingAction.Run))
async def CommandMatchingRun(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)

    await SendMessage(chat_id=chat_id, text=t(lang, "admin.matching_running"))

    # Notify other admins that this admin started matching
    asyncio.create_task(_NotifyOtherAdmins(chat_id, "admin.matching_notify_started"))

    try:
        participants = await RunMatching(triggered_by=chat_id)
        await SendMessage(
            chat_id=chat_id,
            text=t(lang, "admin.matching_done", count=participants),
        )
    except Exception:
        logging.exception("MatchingPipeline failed")
        await SendMessage(chat_id=chat_id, text=t(lang, "admin.matching_failed"))


@router.callback_query(MatchingCallbackData.filter(F.action == MatchingAction.Feedback))
async def CommandMatchingFeedback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)

    ctx = await GetUserContextService()
    last_round = await ctx.GetLastRound()

    if last_round is None:
        await SendMessage(chat_id=chat_id, text=t(lang, "admin.matching_no_rounds"))
        return

    assignments = await ctx.GetAssignmentsByRound(round_id=last_round.id)
    if not assignments:
        await SendMessage(chat_id=chat_id, text=t(lang, "admin.matching_no_assignments"))
        return

    # Group assignments by assigner
    by_assigner: dict[int, list] = {}
    for a in assignments:
        by_assigner.setdefault(a.assigner_chat_id, []).append(a)

    sent = 0
    for assigner_chat_id, user_assignments in by_assigner.items():
        user_lang = await GetUserLanguage(assigner_chat_id)
        for assignment in user_assignments:
            assigned_chat_id = assignment.assigned_chat_id
            # Get a display name for the assigned user
            display = str(assigned_chat_id)
            try:
                from nespresso.bot.lib.chat.username import GetTgUsername
                username = await GetTgUsername(assigned_chat_id)
                if username:
                    display = f"@{username}"
            except Exception:
                logging.debug(f"Failed to get username for assigned chat_id={assigned_chat_id}", exc_info=True)

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=t(user_lang, "matching.feedback_met"),
                            callback_data=FeedbackCallbackData(
                                assignment_id=assignment.id, response="met"
                            ).pack(),
                        ),
                        InlineKeyboardButton(
                            text=t(user_lang, "matching.feedback_not_met"),
                            callback_data=FeedbackCallbackData(
                                assignment_id=assignment.id, response="not_met"
                            ).pack(),
                        ),
                        InlineKeyboardButton(
                            text=t(user_lang, "matching.feedback_planning"),
                            callback_data=FeedbackCallbackData(
                                assignment_id=assignment.id, response="planning"
                            ).pack(),
                        ),
                    ]
                ]
            )
            await SendMessage(
                chat_id=assigner_chat_id,
                text=t(user_lang, "matching.feedback_question", name=display),
                reply_markup=keyboard,
            )
            sent += 1

    await SendMessage(
        chat_id=chat_id,
        text=t(lang, "admin.matching_feedback_sent", count=sent),
    )


@router.callback_query(FeedbackCallbackData.filter())
async def HandleFeedbackResponse(
    callback_query: types.CallbackQuery, callback_data: FeedbackCallbackData
) -> None:
    assert isinstance(callback_query.message, types.Message)

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)

    ctx = await GetUserContextService()
    await ctx.UpsertFeedback(
        assignment_id=callback_data.assignment_id,
        response=callback_data.response,
    )

    # Remove the keyboard after response
    try:
        await callback_query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        logging.debug(f"Failed to remove feedback keyboard for chat_id={chat_id}", exc_info=True)

    await callback_query.answer(t(lang, "matching.feedback_thanks"))
