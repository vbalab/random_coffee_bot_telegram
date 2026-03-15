from enum import Enum

from aiogram import F, Router, types
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.bot.handlers.admin.commands.back import BackToAdminPanelCallbackData
from nespresso.bot.lib.chat.block import BlockUser, CheckIfBlocked, UnblockUser
from nespresso.bot.lib.message.io import ContextIO, SendMessage
from nespresso.bot.lifecycle.creator import bot
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

router = Router()


class BlockingPanelAction(str, Enum):
    BlockUser = "🚫 Block User"
    UnblockUser = "✅ Unblock User"


class BlockingPanelCallbackData(CallbackData, prefix="blocking_panel"):
    action: BlockingPanelAction


class BlockingConfirmAction(str, Enum):
    Block = "Block"
    Unblock = "Unblock"
    Leave = "Leave as is"


class BlockingConfirmCallbackData(CallbackData, prefix="blocking_confirm"):
    action: BlockingConfirmAction
    chat_id: int


class BlockingPanelStates(StatesGroup):
    BlockUsername = State()
    UnblockUsername = State()


def BlockingPanelKeyboard() -> InlineKeyboardMarkup:
    def Button(action: BlockingPanelAction) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=action.value,
            callback_data=BlockingPanelCallbackData(action=action).pack(),
        )

    back_button = InlineKeyboardButton(
        text="⬅️ Back",
        callback_data=BackToAdminPanelCallbackData().pack(),
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [Button(BlockingPanelAction.BlockUser), Button(BlockingPanelAction.UnblockUser)],
            [back_button],
        ]
    )


def BlockingConfirmKeyboard(
    actions: list[BlockingConfirmAction], chat_id: int
) -> InlineKeyboardMarkup:
    def Button(action: BlockingConfirmAction) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=action.value,
            callback_data=BlockingConfirmCallbackData(action=action, chat_id=chat_id).pack(),
        )

    buttons: list[InlineKeyboardButton] = [Button(a) for a in actions]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


async def _GetBlockedUserDisplayName(chat_id: int) -> str:
    try:
        chat = await bot.get_chat(chat_id)
        if chat.username:
            return f"@{chat.username}"
    except Exception:
        pass

    try:
        ctx = await GetUserContextService()
        username = await ctx.GetTgUser(chat_id=chat_id, column=TgUser.username)
        if username:
            return f"@{username}"
    except Exception:
        pass

    return str(chat_id)


async def BuildBlockingPanelText() -> str:
    ctx = await GetUserContextService()
    blocked_ids = await ctx.GetTgUsersOnCondition(
        condition=TgUser.blocked,
        column=TgUser.chat_id,
    )

    if not blocked_ids:
        blocked_section = "No blocked users."
    else:
        lines = [await _GetBlockedUserDisplayName(chat_id) for chat_id in blocked_ids]
        blocked_section = "\n".join(f"• {line}" for line in lines)

    return f"🚫 Blocking Panel\n\nCurrently blocked users:\n{blocked_section}"


async def ShowBlockingPanel(chat_id: int) -> None:
    text = await BuildBlockingPanelText()
    await SendMessage(chat_id=chat_id, text=text, reply_markup=BlockingPanelKeyboard())


# --- Block User ---


@router.callback_query(
    BlockingPanelCallbackData.filter(F.action == BlockingPanelAction.BlockUser)
)
async def BlockingPanelBlock(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text="Enter Telegram username of the user to block (e.g. @vbalab):",
    )
    await state.set_state(BlockingPanelStates.BlockUsername)


@router.message(StateFilter(BlockingPanelStates.BlockUsername), F.content_type == "text")
async def BlockingPanelBlockUsername(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    username = message.text.replace("@", "").strip()
    ctx = await GetUserContextService()
    chat_id = await ctx.GetTgChatIdBy(tg_username=username)

    if chat_id is None:
        await SendMessage(
            chat_id=message.chat.id,
            text=f"No user @{username} found. They need to start the bot first.",
            context=ContextIO.UserFailed,
        )
        await state.clear()
        return

    blocked = await CheckIfBlocked(chat_id)
    await state.clear()

    if blocked:
        await SendMessage(
            chat_id=message.chat.id,
            text=f"@{username} is already blocked.",
        )
        await ShowBlockingPanel(message.chat.id)
        return

    await BlockUser(chat_id)
    await SendMessage(
        chat_id=message.chat.id,
        text=f"@{username} has been blocked.",
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
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text="Enter Telegram username of the user to unblock (e.g. @vbalab):",
    )
    await state.set_state(BlockingPanelStates.UnblockUsername)


@router.message(StateFilter(BlockingPanelStates.UnblockUsername), F.content_type == "text")
async def BlockingPanelUnblockUsername(message: types.Message, state: FSMContext) -> None:
    assert message.text is not None

    username = message.text.replace("@", "").strip()
    ctx = await GetUserContextService()
    chat_id = await ctx.GetTgChatIdBy(tg_username=username)

    if chat_id is None:
        await SendMessage(
            chat_id=message.chat.id,
            text=f"No user @{username} found. They need to start the bot first.",
            context=ContextIO.UserFailed,
        )
        await state.clear()
        return

    blocked = await CheckIfBlocked(chat_id)
    await state.clear()

    if not blocked:
        await SendMessage(
            chat_id=message.chat.id,
            text=f"@{username} is not blocked.",
        )
        await ShowBlockingPanel(message.chat.id)
        return

    await UnblockUser(chat_id)
    await SendMessage(
        chat_id=message.chat.id,
        text=f"@{username} has been unblocked.",
    )
    await ShowBlockingPanel(message.chat.id)
