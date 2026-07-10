import logging
from enum import Enum

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.bot.handlers.admin.commands.back import BackToAdminPanelCallbackData
from nespresso.bot.lib.chat.block import (
    BlockUser,
    GetSpamBlockedChatIds,
    IsSpamBlocked,
    UnblockUser,
)
from nespresso.bot.lib.chat.username import GetTgUsername, ResolveChatIdByUsername
from nespresso.bot.lib.hub_state import HUB_MESSAGES
from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import (
    ContextIO,
    PersonalMsg,
    SendMessage,
    SendMessagesToGroup,
)
from nespresso.bot.lifecycle.creator import bot
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.admin import GetAdminIds, IsAdmin
from nespresso.db.services.user_context import GetUserContextService

router = Router()


class BlockingPanelAction(str, Enum):
    BlockUser = "block"
    UnblockUser = "unblock"


class BlockingPanelCallbackData(CallbackData, prefix="blocking_panel"):
    action: BlockingPanelAction


class BlockingPanelStates(StatesGroup):
    BlockUsername = State()
    UnblockUsername = State()


def BlockingPanelKeyboard(lang: str) -> InlineKeyboardMarkup:
    back_button = InlineKeyboardButton(
        text=t(lang, "admin.button_back"),
        callback_data=BackToAdminPanelCallbackData().pack(),
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "admin.blocking_button_block"),
                    callback_data=BlockingPanelCallbackData(
                        action=BlockingPanelAction.BlockUser
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text=t(lang, "admin.blocking_button_unblock"),
                    callback_data=BlockingPanelCallbackData(
                        action=BlockingPanelAction.UnblockUser
                    ).pack(),
                ),
            ],
            [back_button],
        ]
    )


async def _GetBlockedUserDisplayName(chat_id: int) -> str:
    try:
        chat = await bot.get_chat(chat_id)
        if chat.username:
            return f"@{chat.username}"
    except Exception:
        logging.warning(f"Failed to get chat info for chat_id={chat_id}", exc_info=True)

    try:
        ctx = await GetUserContextService()
        username = await ctx.GetTgUser(chat_id=chat_id, column=TgUser.username)
        if username:
            return f"@{username}"
    except Exception:
        logging.warning(
            f"Failed to get username from DB for chat_id={chat_id}", exc_info=True
        )

    return str(chat_id)


async def BuildBlockingPanelText(lang: str) -> str:
    ctx = await GetUserContextService()
    blocked_ids = await ctx.GetTgUsersOnCondition(
        condition=TgUser.blocked,
        column=TgUser.chat_id,
    )

    if not blocked_ids:
        blocked_section = t(lang, "admin.blocking_no_blocked")
    else:
        lines = [await _GetBlockedUserDisplayName(chat_id) for chat_id in blocked_ids]
        blocked_section = "\n".join(f"• {line}" for line in lines)

    header = t(lang, "admin.blocking_header", blocked_section=blocked_section)

    # Surface in-memory spam-blocks too (they never set TgUser.blocked, so they'd
    # otherwise be invisible here). Only DB-blocked users are excluded to avoid
    # listing anyone twice.
    spam_ids = [cid for cid in GetSpamBlockedChatIds() if cid not in set(blocked_ids)]
    if spam_ids:
        spam_lines = [await _GetBlockedUserDisplayName(cid) for cid in spam_ids]
        spam_section = "\n".join(f"• {line}" for line in spam_lines)
        header += "\n\n" + t(lang, "admin.blocking_spam_section", spam_section=spam_section)

    return header


async def _NotifyAdminsAboutBlocking(
    actor_chat_id: int, key: str, **kwargs: str
) -> None:
    """Send a blocking-related notification to all admins except the actor."""
    other_admins = [aid for aid in await GetAdminIds() if aid != actor_chat_id]
    if not other_admins:
        return

    actor_name = str(actor_chat_id)
    try:
        username = await GetTgUsername(actor_chat_id)
        if username:
            actor_name = f"@{username}"
    except Exception:
        logging.debug(
            f"Failed to get username for actor chat_id={actor_chat_id}", exc_info=True
        )

    messages: list[PersonalMsg] = []
    for admin_id in other_admins:
        lang = await GetUserLanguage(admin_id)
        text = t(lang, key, actor=actor_name, **kwargs)
        messages.append(PersonalMsg(chat_id=admin_id, text=text))

    await SendMessagesToGroup(messages)


async def ShowBlockingPanel(chat_id: int) -> None:
    """Edit the hub message to display the blocking sub-panel."""
    lang = await GetUserLanguage(chat_id)
    text = await BuildBlockingPanelText(lang)
    keyboard = BlockingPanelKeyboard(lang)

    hub_msg_id = HUB_MESSAGES.get(chat_id)
    if hub_msg_id is None:
        ctx = await GetUserContextService()
        hub_msg_id = await ctx.GetTgUser(chat_id, TgUser.panel_message_id)

    if hub_msg_id is not None:
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=hub_msg_id,
                reply_markup=keyboard,
            )
            return
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return

    msg = await SendMessage(chat_id=chat_id, text=text, reply_markup=keyboard)
    if msg is not None:
        HUB_MESSAGES[chat_id] = msg.message_id
        ctx = await GetUserContextService()
        await ctx.UpdateTgUser(
            chat_id=chat_id, column=TgUser.panel_message_id, value=msg.message_id
        )


# --- Block User ---


@router.callback_query(
    BlockingPanelCallbackData.filter(F.action == BlockingPanelAction.BlockUser)
)
async def BlockingPanelBlock(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text=t(lang, "admin.blocking_enter_block"),
    )
    await state.set_state(BlockingPanelStates.BlockUsername)


@router.message(
    StateFilter(BlockingPanelStates.BlockUsername), F.content_type == "text"
)
async def BlockingPanelBlockUsername(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    lang = await GetUserLanguage(message.chat.id)
    username = message.text.replace("@", "").strip()
    chat_id = await ResolveChatIdByUsername(username)
    ctx = await GetUserContextService()

    if chat_id is None or not await ctx.CheckTgUserExists(chat_id):
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.blocking_not_found", username=username),
            context=ContextIO.UserFailed,
        )
        return

    if await IsAdmin(chat_id):
        await state.clear()
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.blocking_is_admin", username=username),
            context=ContextIO.UserFailed,
        )
        await _NotifyAdminsAboutBlocking(
            message.chat.id, "admin.blocking_notify_tried_admin", target=f"@{username}"
        )
        await ShowBlockingPanel(message.chat.id)
        return

    # Branch on the DB `blocked` flag, NOT CheckIfBlocked: a user who is only
    # spam-blocked (in-memory, auto-expiring) is NOT yet truly blocked, so
    # "already blocked" would be a lie and, worse, we'd skip BlockUser and let
    # the DB flag stay False — the user would auto-unblock when the 1h TTL lapsed.
    db_blocked = await ctx.GetTgUser(chat_id, TgUser.blocked) or False
    await state.clear()

    if db_blocked:
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.blocking_already_blocked", username=username),
        )
    else:
        # BlockUser sets the DB flag unconditionally, so this makes the block
        # permanent even for a currently spam-blocked user.
        await BlockUser(chat_id)
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.blocking_blocked", username=username),
        )
        await _NotifyAdminsAboutBlocking(
            message.chat.id, "admin.blocking_notify_blocked", target=f"@{username}"
        )

    await ShowBlockingPanel(message.chat.id)


# --- Unblock User ---


@router.callback_query(
    BlockingPanelCallbackData.filter(F.action == BlockingPanelAction.UnblockUser)
)
async def BlockingPanelUnblock(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text=t(lang, "admin.blocking_enter_unblock"),
    )
    await state.set_state(BlockingPanelStates.UnblockUsername)


@router.message(
    StateFilter(BlockingPanelStates.UnblockUsername), F.content_type == "text"
)
async def BlockingPanelUnblockUsername(
    message: types.Message, state: FSMContext
) -> None:
    assert message.text is not None

    lang = await GetUserLanguage(message.chat.id)
    username = message.text.replace("@", "").strip()
    chat_id = await ResolveChatIdByUsername(username)
    ctx = await GetUserContextService()

    if chat_id is None or not await ctx.CheckTgUserExists(chat_id):
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.blocking_not_found", username=username),
            context=ContextIO.UserFailed,
        )
        return

    # A user can be blocked by the DB flag, by the in-memory spam-block, or both.
    # Treat ANY of them as "blocked" so the unblock is offered, and UnblockUser
    # clears BOTH sources — otherwise unblocking a spam-blocked-only user would
    # report success yet leave them blocked until the 1h spam TTL expired.
    db_blocked = await ctx.GetTgUser(chat_id, TgUser.blocked) or False
    spam_blocked = IsSpamBlocked(chat_id)
    await state.clear()

    if not db_blocked and not spam_blocked:
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.blocking_not_blocked", username=username),
        )
    else:
        await UnblockUser(chat_id)
        await SendMessage(
            chat_id=message.chat.id,
            text=t(lang, "admin.blocking_unblocked", username=username),
        )
        await _NotifyAdminsAboutBlocking(
            message.chat.id, "admin.blocking_notify_unblocked", target=f"@{username}"
        )

    await ShowBlockingPanel(message.chat.id)
