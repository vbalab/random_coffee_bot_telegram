import logging
from enum import Enum
from typing import Any

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from cachetools import TTLCache

from nespresso.bot.lib.hub_state import HUB_MESSAGES
from nespresso.bot.lib.message.checks import CheckVerified
from nespresso.bot.lib.message.file import SendTemporaryXlsxFile
from nespresso.bot.lib.message.i18n import GetUserLanguage, SetUserLanguage, t
from nespresso.bot.lib.message.io import EditPanel, SendMessage
from nespresso.core.configs.title_store import GetTitle
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.profile import Profile
from nespresso.recsys.searching.document import DeleteUserOpenSearch

router = Router()

# Per-chat cooldown on help requests. Each "Ask for help" (button OR the
# unverified /help path) fans out a DM to EVERY admin, so without this one user
# could flood the whole admin team. A short window is enough to stop a flood
# while still letting a genuine follow-up through soon after.
_HELP_COOLDOWN_SECONDS = 5 * 60
_help_cooldown: TTLCache[int, bool] = TTLCache(maxsize=10000, ttl=_HELP_COOLDOWN_SECONDS)

# A single user's own data is tiny; this cap just bounds the self-export.
_EXPORT_MESSAGE_LIMIT = 1_000_000


class SettingsAction(str, Enum):
    ToggleMatching = "toggle_matching"
    ChangeLanguage = "change_language"
    Help = "help"
    Privacy = "privacy"
    HiddenProfiles = "hidden_profiles"
    Back = "back"


class SettingsCallbackData(CallbackData, prefix="settings"):
    action: SettingsAction


class PrivacyAction(str, Enum):
    Export = "export"
    Delete = "delete"
    DeleteConfirm = "delete_confirm"
    DeleteCancel = "delete_cancel"
    Back = "back"  # back to the Settings panel


class PrivacyCallbackData(CallbackData, prefix="privacy"):
    action: PrivacyAction


class HiddenProfilesAction(str, Enum):
    Prev = "prev"
    Next = "next"
    Unblock = "unblock"
    Back = "back"  # back to the Settings panel


class HiddenProfilesCallbackData(CallbackData, prefix="hidden_profiles"):
    action: HiddenProfilesAction
    # Target index into the user's blocked-profile list (most-recent-first). The
    # list is re-fetched from the DB on every tap, so no session state is kept.
    index: int = 0


class HelpAction(str, Enum):
    AskHelp = "ask"
    Back = "back"
    BackToHub = "back_hub"


class HelpCallbackData(CallbackData, prefix="help"):
    action: HelpAction


def BuildSettingsPanelContent(
    lang: str, matching_paused: bool
) -> tuple[str, InlineKeyboardMarkup]:
    matching_label = (
        t(lang, "hub.matching_paused")
        if matching_paused
        else t(lang, "hub.matching_active")
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=matching_label,
                    callback_data=SettingsCallbackData(
                        action=SettingsAction.ToggleMatching
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "settings.button_language"),
                    callback_data=SettingsCallbackData(
                        action=SettingsAction.ChangeLanguage
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "settings.button_help"),
                    callback_data=SettingsCallbackData(
                        action=SettingsAction.Help
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "settings.button_privacy"),
                    callback_data=SettingsCallbackData(
                        action=SettingsAction.Privacy
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "settings.button_back"),
                    callback_data=SettingsCallbackData(
                        action=SettingsAction.Back
                    ).pack(),
                )
            ],
        ]
    )
    return t(lang, "settings.panel_header"), keyboard


def BuildPrivacyPanelContent(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    """The 'My data & privacy' sub-panel: hidden profiles, self-service export,
    and account deletion grouped together."""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "settings.button_hidden"),
                    callback_data=SettingsCallbackData(
                        action=SettingsAction.HiddenProfiles
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "settings.button_export"),
                    callback_data=PrivacyCallbackData(action=PrivacyAction.Export).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "settings.button_delete"),
                    callback_data=PrivacyCallbackData(action=PrivacyAction.Delete).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "settings.button_back"),
                    callback_data=PrivacyCallbackData(action=PrivacyAction.Back).pack(),
                )
            ],
        ]
    )
    return t(lang, "settings.privacy_header"), keyboard


def BuildDeleteConfirmContent(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "settings.button_delete_confirm"),
                    callback_data=PrivacyCallbackData(
                        action=PrivacyAction.DeleteConfirm
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "settings.button_delete_cancel"),
                    callback_data=PrivacyCallbackData(
                        action=PrivacyAction.DeleteCancel
                    ).pack(),
                )
            ],
        ]
    )
    return t(lang, "settings.delete_confirm_header"), keyboard


def BuildHelpPanelContent(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "help.button_ask"),
                    callback_data=HelpCallbackData(action=HelpAction.AskHelp).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "help.button_back"),
                    callback_data=HelpCallbackData(action=HelpAction.Back).pack(),
                )
            ],
        ]
    )
    return t(lang, "help.panel_header"), keyboard


def BuildHelpCommandPanelContent(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    """Help panel for use with the /help command (Back returns to hub)."""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "help.button_ask"),
                    callback_data=HelpCallbackData(action=HelpAction.AskHelp).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "help.button_back"),
                    callback_data=HelpCallbackData(action=HelpAction.BackToHub).pack(),
                )
            ],
        ]
    )
    return t(lang, "help.panel_header"), keyboard


@router.callback_query(
    SettingsCallbackData.filter(F.action == SettingsAction.ToggleMatching)
)
async def SettingsToggleMatching(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()

    current = await ctx.GetTgUser(chat_id, TgUser.matching_paused) or False
    new_value = not current
    await ctx.UpdateTgUser(chat_id, TgUser.matching_paused, new_value)

    _, keyboard = BuildSettingsPanelContent(lang, matching_paused=new_value)
    try:
        await callback_query.message.edit_reply_markup(reply_markup=keyboard)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.warning(
                f"Failed to update matching toggle keyboard for chat_id={chat_id}: {e}"
            )


@router.callback_query(
    SettingsCallbackData.filter(F.action == SettingsAction.ChangeLanguage)
)
async def SettingsChangeLanguage(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)

    new_lang = "ru" if lang == "en" else "en"
    await SetUserLanguage(chat_id, new_lang)

    ctx = await GetUserContextService()
    matching_paused = await ctx.GetTgUser(chat_id, TgUser.matching_paused) or False

    text, keyboard = BuildSettingsPanelContent(
        new_lang, matching_paused=matching_paused
    )
    await EditPanel(callback_query, text, reply_markup=keyboard)


@router.callback_query(SettingsCallbackData.filter(F.action == SettingsAction.Help))
async def SettingsHelpCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)

    text, keyboard = BuildHelpPanelContent(lang)
    await EditPanel(callback_query, text, reply_markup=keyboard)


# --- My data & privacy sub-panel ---


@router.callback_query(SettingsCallbackData.filter(F.action == SettingsAction.Privacy))
async def SettingsPrivacyCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    text, keyboard = BuildPrivacyPanelContent(lang)
    await EditPanel(callback_query, text, reply_markup=keyboard)


@router.callback_query(PrivacyCallbackData.filter(F.action == PrivacyAction.Back))
async def PrivacyBackCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()
    matching_paused = await ctx.GetTgUser(chat_id, TgUser.matching_paused) or False

    text, keyboard = BuildSettingsPanelContent(lang, matching_paused=matching_paused)
    await EditPanel(callback_query, text, reply_markup=keyboard)


async def _ExportMyData(chat_id: int) -> None:
    """Build a single-user xlsx of everything NESpresso stores about the caller
    (account row + their messages, reactions, and match assignments/feedback) and
    send it. Scoped to this one chat_id — NOT the admin all-users export."""
    ctx = await GetUserContextService()
    user = await ctx.GetTgUser(chat_id)
    messages = await ctx.GetRecentMessages(chat_id, limit=_EXPORT_MESSAGE_LIMIT)
    reactions = await ctx.GetProfileReactionsForUser(chat_id)
    matches = await ctx.GetMatchDataForUser(chat_id)

    account_headers = [
        "chat_id",
        "nes_id",
        "nes_email",
        "username",
        "language",
        "about",
        "verified",
        "blocked",
        "matching_paused",
        "is_admin",
        "created_at",
        "updated_at",
    ]
    account_rows: list[list[Any]] = []
    if user is not None:
        account_rows.append(
            [
                str(user.chat_id),
                str(user.nes_id or ""),
                str(user.nes_email or ""),
                str(user.username or ""),
                str(user.language or ""),
                str(user.about or ""),
                str(user.verified),
                str(user.blocked),
                str(user.matching_paused),
                str(user.is_admin),
                str(user.created_at),
                str(user.updated_at),
            ]
        )

    message_headers = ["message_id", "side", "text", "time"]
    message_rows: list[list[Any]] = [
        [str(m.message_id), m.side.value, m.text, str(m.time)] for m in messages
    ]

    reaction_headers = ["target_nes_id", "reaction", "blocked", "created_at", "updated_at"]
    reaction_rows: list[list[Any]] = [
        [
            str(r.target_nes_id),
            str(r.reaction or ""),
            str(r.blocked),
            str(r.created_at),
            str(r.updated_at),
        ]
        for r in reactions
    ]

    match_headers = ["round_id", "role", "other_chat_id", "created_at", "feedback"]
    match_rows: list[list[Any]] = []
    for row in matches:
        if row["assigner_chat_id"] == chat_id:
            role, other = "reached_out_to", row["assigned_chat_id"]
        else:
            role, other = "assigned_to_meet_me", row["assigner_chat_id"]
        match_rows.append(
            [
                str(row["round_id"]),
                role,
                str(other),
                str(row["created_at"]),
                str(row["response"] or ""),
            ]
        )

    await SendTemporaryXlsxFile(
        chat_id=chat_id,
        sheets=[
            ("account", account_headers, account_rows),
            ("messages", message_headers, message_rows),
            ("reactions", reaction_headers, reaction_rows),
            ("matches", match_headers, match_rows),
        ],
        filename="my_data",
    )


@router.callback_query(PrivacyCallbackData.filter(F.action == PrivacyAction.Export))
async def PrivacyExportCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)

    await SendMessage(chat_id=chat_id, text=t(lang, "settings.export_intro"))
    await _ExportMyData(chat_id)


@router.callback_query(PrivacyCallbackData.filter(F.action == PrivacyAction.Delete))
async def PrivacyDeleteCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    text, keyboard = BuildDeleteConfirmContent(lang)
    await EditPanel(callback_query, text, reply_markup=keyboard)


@router.callback_query(
    PrivacyCallbackData.filter(F.action == PrivacyAction.DeleteCancel)
)
async def PrivacyDeleteCancelCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    text, keyboard = BuildPrivacyPanelContent(lang)
    await EditPanel(callback_query, text, reply_markup=keyboard)


@router.callback_query(
    PrivacyCallbackData.filter(F.action == PrivacyAction.DeleteConfirm)
)
async def PrivacyDeleteConfirmCallback(
    callback_query: types.CallbackQuery, state: FSMContext
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    # Read language + nes_id BEFORE deleting the row they live on.
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()
    nes_id = await ctx.GetTgUser(chat_id, TgUser.nes_id)

    # Drop the search document first (recsys-side), then every DB row.
    if nes_id is not None:
        await DeleteUserOpenSearch(nes_id)
    await ctx.DeleteAccountData(chat_id, nes_id)

    # End the session cleanly: clear any FSM state and forget the tracked panel.
    await state.clear()
    HUB_MESSAGES.pop(chat_id, None)
    try:
        await callback_query.message.delete()
    except TelegramBadRequest as e:
        logging.warning(
            f"Failed to delete panel after account deletion for chat_id={chat_id}: {e}"
        )

    await SendMessage(chat_id=chat_id, text=t(lang, "settings.delete_done"))


@router.callback_query(SettingsCallbackData.filter(F.action == SettingsAction.Back))
async def SettingsBackCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.message.chat.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()
    is_admin = await ctx.GetTgUser(chat_id, TgUser.is_admin) or False

    from nespresso.bot.handlers.client.commands.hub import HubKeyboard

    await EditPanel(
        callback_query,
        GetTitle(lang),
        reply_markup=HubKeyboard(lang, is_admin),
    )


# --- Hidden profiles (per-user profile blocks from Find) ---


def _HiddenProfilesKeyboard(
    lang: str, index: int, total: int
) -> InlineKeyboardMarkup:
    """Unblock row, prev/next arrows, and a back-to-settings row."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=t(lang, "settings.hidden_unblock"),
                callback_data=HiddenProfilesCallbackData(
                    action=HiddenProfilesAction.Unblock, index=index
                ).pack(),
            )
        ]
    ]

    arrows: list[InlineKeyboardButton] = []
    if index > 0:
        arrows.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=HiddenProfilesCallbackData(
                    action=HiddenProfilesAction.Prev, index=index - 1
                ).pack(),
            )
        )
    if index < total - 1:
        arrows.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=HiddenProfilesCallbackData(
                    action=HiddenProfilesAction.Next, index=index + 1
                ).pack(),
            )
        )
    if arrows:
        rows.append(arrows)

    rows.append(
        [
            InlineKeyboardButton(
                text=t(lang, "settings.button_back"),
                callback_data=HiddenProfilesCallbackData(
                    action=HiddenProfilesAction.Back
                ).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _HiddenProfilesEmptyKeyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "settings.button_back"),
                    callback_data=HiddenProfilesCallbackData(
                        action=HiddenProfilesAction.Back
                    ).pack(),
                )
            ]
        ]
    )


async def _RenderHiddenProfiles(
    callback_query: types.CallbackQuery, lang: str, index: int
) -> None:
    """
    Edit the panel message to show the blocked profile at `index` (its full Find
    card + an Unblock button), or an empty-state if the user has hidden nobody.
    The blocked list is re-fetched each call so it stays correct after unblocks.
    """
    assert isinstance(callback_query.message, types.Message)
    chat_id = callback_query.from_user.id
    ctx = await GetUserContextService()
    blocked_nes_ids = await ctx.GetBlockedTargetNesIds(chat_id)

    if not blocked_nes_ids:
        await EditPanel(
            callback_query,
            t(lang, "settings.hidden_empty"),
            reply_markup=_HiddenProfilesEmptyKeyboard(lang),
        )
        return

    index = max(0, min(index, len(blocked_nes_ids) - 1))
    nes_id = blocked_nes_ids[index]
    profile = await Profile.FromNesId(nes_id)
    label = f"[{index + 1} / {len(blocked_nes_ids)}]"
    text = (
        f"{t(lang, 'settings.hidden_title')}\n"
        f"<code>{label}</code>\n\n"
        f"{profile.DescribeProfile()}"
    )
    await EditPanel(
        callback_query,
        text,
        reply_markup=_HiddenProfilesKeyboard(lang, index, len(blocked_nes_ids)),
        parse_mode="HTML",
    )


@router.callback_query(
    SettingsCallbackData.filter(F.action == SettingsAction.HiddenProfiles)
)
async def SettingsHiddenProfilesCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    await _RenderHiddenProfiles(callback_query, lang, index=0)


@router.callback_query(
    HiddenProfilesCallbackData.filter(
        F.action.in_({HiddenProfilesAction.Prev, HiddenProfilesAction.Next})
    )
)
async def HiddenProfilesScroll(
    callback_query: types.CallbackQuery,
    callback_data: HiddenProfilesCallbackData,
) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    lang = await GetUserLanguage(callback_query.from_user.id)
    await _RenderHiddenProfiles(callback_query, lang, index=callback_data.index)


@router.callback_query(
    HiddenProfilesCallbackData.filter(F.action == HiddenProfilesAction.Unblock)
)
async def HiddenProfilesUnblock(
    callback_query: types.CallbackQuery,
    callback_data: HiddenProfilesCallbackData,
) -> None:
    assert isinstance(callback_query.message, types.Message)

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()

    blocked_nes_ids = await ctx.GetBlockedTargetNesIds(chat_id)
    index = callback_data.index
    if 0 <= index < len(blocked_nes_ids):
        await ctx.SetProfileBlocked(chat_id, blocked_nes_ids[index], False)
        await callback_query.answer(t(lang, "settings.hidden_unblocked"))
    else:
        await callback_query.answer()

    # Re-render at the same slot: the row below shifts up into it (or we clamp to
    # the new last item / empty-state).
    await _RenderHiddenProfiles(callback_query, lang, index=index)


@router.callback_query(
    HiddenProfilesCallbackData.filter(F.action == HiddenProfilesAction.Back)
)
async def HiddenProfilesBack(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)

    # Hidden profiles now lives under the "My data & privacy" sub-panel, so Back
    # returns there (not straight to the top-level Settings panel).
    text, keyboard = BuildPrivacyPanelContent(lang)
    await EditPanel(callback_query, text, reply_markup=keyboard)


async def _RelayHelpRequestToAdmins(chat_id: int) -> None:
    """Notify every admin that this user asked for help (silent to the user)."""
    ctx = await GetUserContextService()
    user = await ctx.GetTgUser(chat_id)
    username = f"@{user.username}" if user and user.username else str(chat_id)

    for admin_id in await ctx.GetAdminChatIds():
        admin_lang = await GetUserLanguage(admin_id)
        notification = t(
            admin_lang, "help.admin_notification", username=username, chat_id=chat_id
        )
        await SendMessage(chat_id=admin_id, text=notification)


async def _TryRelayHelpRequest(chat_id: int, lang: str) -> None:
    """Rate-limited help relay shared by the button and the /help paths. If the
    user is still within their cooldown window, tell them it was already sent and
    relay nothing; otherwise mark the window, fan out to admins, and confirm."""
    if chat_id in _help_cooldown:
        await SendMessage(chat_id=chat_id, text=t(lang, "help.request_cooldown"))
        return

    _help_cooldown[chat_id] = True
    await _RelayHelpRequestToAdmins(chat_id)
    await SendMessage(chat_id=chat_id, text=t(lang, "help.request_sent"))


@router.callback_query(HelpCallbackData.filter(F.action == HelpAction.AskHelp))
async def HelpAskCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)

    await _TryRelayHelpRequest(chat_id, lang)


@router.callback_query(HelpCallbackData.filter(F.action == HelpAction.Back))
async def HelpBackCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    lang = await GetUserLanguage(chat_id)
    ctx = await GetUserContextService()
    matching_paused = await ctx.GetTgUser(chat_id, TgUser.matching_paused) or False

    text, keyboard = BuildSettingsPanelContent(lang, matching_paused=matching_paused)
    await EditPanel(callback_query, text, reply_markup=keyboard)


@router.callback_query(HelpCallbackData.filter(F.action == HelpAction.BackToHub))
async def HelpBackToHubCallback(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()

    chat_id = callback_query.from_user.id
    try:
        await callback_query.message.delete()
    except TelegramBadRequest as e:
        logging.warning(f"Failed to delete help message for chat_id={chat_id}: {e}")

    from nespresso.bot.handlers.client.commands.hub import SendHub

    await SendHub(chat_id)


@router.message(Command("help"))
async def HelpCommand(message: types.Message) -> None:
    chat_id = message.chat.id
    lang = await GetUserLanguage(chat_id)

    if await CheckVerified(chat_id):
        text, keyboard = BuildHelpCommandPanelContent(lang)
        await SendMessage(chat_id=chat_id, text=text, reply_markup=keyboard)
        return

    # Unverified — typically stuck at the email step (the enter_email copy points
    # a user who lost inbox access to /help). Don't expose the hub-reachable help
    # panel (that would hand an unverified user the hub); just relay the request
    # to admins so they can help, and leave the user's FSM state untouched so
    # they can still finish verifying if they regain access. Same cooldown as the
    # button path so /help spam can't flood admins either.
    await _TryRelayHelpRequest(chat_id, lang)
