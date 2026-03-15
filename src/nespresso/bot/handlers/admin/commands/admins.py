from enum import Enum

from aiogram import F, Router, types
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.bot.handlers.admin.commands.back import BackToAdminPanelCallbackData
from nespresso.bot.lib.message.io import ContextIO, SendMessage
from nespresso.bot.lifecycle.creator import bot
from nespresso.core.configs.admin_store import admin_store
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

router = Router()


class AdminsAction(str, Enum):
    AddAdmin = "➕ Add Admin"
    RemoveAdmin = "➖ Remove Admin"


class AdminsCallbackData(CallbackData, prefix="admins_panel"):
    action: AdminsAction


class AdminsStates(StatesGroup):
    AddUsername = State()
    RemoveUsername = State()


def AdminsKeyboard() -> InlineKeyboardMarkup:
    def Button(action: AdminsAction) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=action.value,
            callback_data=AdminsCallbackData(action=action).pack(),
        )

    back_button = InlineKeyboardButton(
        text="⬅️ Back",
        callback_data=BackToAdminPanelCallbackData().pack(),
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [Button(AdminsAction.AddAdmin), Button(AdminsAction.RemoveAdmin)],
            [back_button],
        ]
    )


async def _GetAdminDisplayName(chat_id: int) -> str:
    """
    Fetch the freshest username for a given admin chat_id.
    First tries Telegram API (bot.get_chat) and updates DB if username changed.
    Falls back to DB, then bare ID.
    """
    try:
        chat = await bot.get_chat(chat_id)
        if chat.username:
            try:
                ctx = await GetUserContextService()
                await ctx.UpdateTgUser(
                    chat_id=chat_id,
                    column=TgUser.username,
                    value=chat.username,
                )
            except Exception:
                pass
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


async def BuildAdminsPanelText() -> str:
    ids = admin_store.GetIds()
    if not ids:
        admins_section = "No admins configured."
    else:
        lines = [await _GetAdminDisplayName(chat_id) for chat_id in ids]
        admins_section = "\n".join(f"• {line}" for line in lines)

    return f"👥 Admins Panel\n\nCurrent admins:\n{admins_section}"


async def ShowAdminsPanel(chat_id: int) -> None:
    text = await BuildAdminsPanelText()
    await SendMessage(chat_id=chat_id, text=text, reply_markup=AdminsKeyboard())


# --- Add Admin ---


@router.callback_query(AdminsCallbackData.filter(F.action == AdminsAction.AddAdmin))
async def AdminsPanelAdd(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text="Enter Telegram username of the new admin (e.g. @vbalab):",
    )
    await state.set_state(AdminsStates.AddUsername)


@router.message(StateFilter(AdminsStates.AddUsername), F.content_type == "text")
async def AdminsPanelAddUsername(message: types.Message, state: FSMContext) -> None:
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

    added = admin_store.Add(chat_id)
    await state.clear()

    if not added:
        await SendMessage(
            chat_id=message.chat.id,
            text=f"@{username} is already an admin.",
        )
        return

    await SendMessage(
        chat_id=message.chat.id,
        text=f"@{username} has been added as admin.",
    )
    await ShowAdminsPanel(message.chat.id)


# --- Remove Admin ---


@router.callback_query(AdminsCallbackData.filter(F.action == AdminsAction.RemoveAdmin))
async def AdminsPanelRemove(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await SendMessage(
        chat_id=callback_query.message.chat.id,
        text="Enter Telegram username of the admin to remove (e.g. @vbalab):",
    )
    await state.set_state(AdminsStates.RemoveUsername)


@router.message(StateFilter(AdminsStates.RemoveUsername), F.content_type == "text")
async def AdminsPanelRemoveUsername(message: types.Message, state: FSMContext) -> None:
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

    removed = admin_store.Remove(chat_id)
    await state.clear()

    if not removed:
        await SendMessage(
            chat_id=message.chat.id,
            text=f"@{username} is not an admin.",
        )
        return

    await SendMessage(
        chat_id=message.chat.id,
        text=f"@{username} has been removed from admins.",
    )
    await ShowAdminsPanel(message.chat.id)
