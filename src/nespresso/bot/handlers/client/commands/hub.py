import logging

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from nespresso.bot.handlers.admin.commands.admin import BuildAdminPanelContent
from nespresso.bot.handlers.admin.commands.back import BackToHubCallbackData
from nespresso.bot.handlers.client.commands.about import BuildAboutPanelContent
from nespresso.bot.handlers.client.commands.find import FindStates
from nespresso.bot.handlers.client.commands.settings import BuildSettingsPanelContent
from nespresso.bot.handlers.client.hub_view import (
    HubAction,
    HubCallbackData,
    HubKeyboard,
)
from nespresso.bot.lib.hub_state import HUB_MESSAGES
from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import EditPanel, SendMessage
from nespresso.core.configs.title_store import GetTitle
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

router = Router()


async def _IsStalePanel(chat_id: int, message_id: int) -> bool:
    """
    True if `message_id` is NOT the panel currently tracked for `chat_id`. A
    user can still have an old hub message sitting in their chat history (e.g.
    from before a restart, or several navigations back); tapping its buttons
    should be a clean no-op rather than silently acting on/deleting a message
    that isn't the one HUB_MESSAGES/panel_message_id actually points at
    (which would orphan whichever message WAS current).
    """
    tracked = HUB_MESSAGES.get(chat_id)
    if tracked is None:
        ctx = await GetUserContextService()
        tracked = await ctx.GetTgUser(chat_id, TgUser.panel_message_id)
    return tracked is not None and tracked != message_id


@router.callback_query(HubCallbackData.filter(F.action == HubAction.Find))
async def HubFindCallback(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    chat_id = callback_query.from_user.id
    if await _IsStalePanel(chat_id, callback_query.message.message_id):
        lang = await GetUserLanguage(chat_id)
        await callback_query.answer(t(lang, "common.button_outdated"), show_alert=True)
        return
    await callback_query.answer()

    lang = await GetUserLanguage(chat_id)

    # Delete the hub message so it doesn't remain clickable during the search flow
    try:
        await callback_query.message.delete()
    except Exception:
        logging.warning(
            f"Failed to delete hub message for chat_id={chat_id} during Find",
            exc_info=True,
        )
    HUB_MESSAGES.pop(chat_id, None)

    msg = await SendMessage(
        chat_id=callback_query.message.chat.id,
        text=t(lang, "find.enter_query"),
    )

    # Track the search prompt so SendHub can clean it up when the user returns to hub
    if msg is not None:
        HUB_MESSAGES[chat_id] = msg.message_id
        ctx = await GetUserContextService()
        await ctx.UpdateTgUser(
            chat_id=chat_id, column=TgUser.panel_message_id, value=msg.message_id
        )

    await state.set_state(FindStates.Text)


@router.callback_query(HubCallbackData.filter(F.action == HubAction.Admin))
async def HubAdminCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    chat_id = callback_query.message.chat.id
    if await _IsStalePanel(chat_id, callback_query.message.message_id):
        lang = await GetUserLanguage(chat_id)
        await callback_query.answer(t(lang, "common.button_outdated"), show_alert=True)
        return
    await callback_query.answer()

    ctx = await GetUserContextService()
    is_admin = await ctx.GetTgUser(chat_id, TgUser.is_admin) or False
    if not is_admin:
        return

    lang = await GetUserLanguage(chat_id)
    text, keyboard = BuildAdminPanelContent(lang)
    await EditPanel(callback_query, text, reply_markup=keyboard)


@router.callback_query(HubCallbackData.filter(F.action == HubAction.Settings))
async def HubSettingsCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)
    if await _IsStalePanel(chat_id, callback_query.message.message_id):
        await callback_query.answer(t(lang, "common.button_outdated"), show_alert=True)
        return
    await callback_query.answer()

    ctx = await GetUserContextService()
    matching_paused = await ctx.GetTgUser(chat_id, TgUser.matching_paused) or False

    text, keyboard = BuildSettingsPanelContent(lang, matching_paused=matching_paused)
    await EditPanel(callback_query, text, reply_markup=keyboard)


@router.callback_query(HubCallbackData.filter(F.action == HubAction.About))
async def HubAboutCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)
    if await _IsStalePanel(chat_id, callback_query.message.message_id):
        await callback_query.answer(t(lang, "common.button_outdated"), show_alert=True)
        return
    await callback_query.answer()

    ctx = await GetUserContextService()
    about = await ctx.GetTgUser(chat_id, TgUser.about)

    text, keyboard = BuildAboutPanelContent(lang, about)
    await EditPanel(callback_query, text, reply_markup=keyboard)


@router.callback_query(BackToHubCallbackData.filter())
async def HubBack(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    assert isinstance(callback_query.message, types.Message)
    chat_id = callback_query.message.chat.id
    if await _IsStalePanel(chat_id, callback_query.message.message_id):
        lang = await GetUserLanguage(chat_id)
        await callback_query.answer(t(lang, "common.button_outdated"), show_alert=True)
        return
    await callback_query.answer()
    await state.clear()

    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()
    is_admin = await ctx.GetTgUser(chat_id, TgUser.is_admin) or False
    await EditPanel(
        callback_query,
        GetTitle(lang),
        reply_markup=HubKeyboard(lang, is_admin),
    )
