from enum import StrEnum

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nespresso.bot.handlers.admin.commands.back import BackToAdminPanelCallbackData
from nespresso.bot.lib.hub_state import HUB_MESSAGES
from nespresso.bot.lib.message.file import SendTemporaryXlsxFile
from nespresso.bot.lib.message.i18n import GetUserLanguage, t
from nespresso.bot.lib.message.io import SendMessage
from nespresso.bot.lifecycle.creator import bot
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.analytics import GetAnalyticsService
from nespresso.db.services.user_context import GetUserContextService

router = Router()


class StatisticsAction(StrEnum):
    Users = "users"
    Alumni = "alumni"
    Activity = "activity"
    Matching = "matching"
    DownloadDB = "download_db"


class StatisticsCallbackData(CallbackData, prefix="stats"):
    action: StatisticsAction


class BackToStatisticsCallbackData(CallbackData, prefix="back_to_stats"):
    pass


class DownloadDBAction(StrEnum):
    TgUser = "tg_user"
    NesUser = "nes_user"
    Message = "message"


class DownloadDBCallbackData(CallbackData, prefix="stats_db"):
    action: DownloadDBAction


def StatisticsKeyboard(lang: str) -> InlineKeyboardMarkup:
    def Button(action: StatisticsAction, label_key: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=t(lang, label_key),
            callback_data=StatisticsCallbackData(action=action).pack(),
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                Button(StatisticsAction.Users, "admin.stats_button_users"),
                Button(StatisticsAction.Alumni, "admin.stats_button_alumni"),
            ],
            [
                Button(StatisticsAction.Activity, "admin.stats_button_activity"),
                Button(StatisticsAction.Matching, "admin.stats_button_matching"),
            ],
            [Button(StatisticsAction.DownloadDB, "admin.stats_button_download_db")],
            [
                InlineKeyboardButton(
                    text=t(lang, "admin.button_back"),
                    callback_data=BackToAdminPanelCallbackData().pack(),
                )
            ],
        ]
    )


def DownloadDBKeyboard(lang: str) -> InlineKeyboardMarkup:
    def Button(action: DownloadDBAction, label_key: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=t(lang, label_key),
            callback_data=DownloadDBCallbackData(action=action).pack(),
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [Button(DownloadDBAction.TgUser, "admin.stats_db_button_tg_user")],
            [Button(DownloadDBAction.NesUser, "admin.stats_db_button_nes_user")],
            [Button(DownloadDBAction.Message, "admin.stats_db_button_message")],
            [
                InlineKeyboardButton(
                    text=t(lang, "admin.button_back"),
                    callback_data=BackToStatisticsCallbackData().pack(),
                )
            ],
        ]
    )


async def ShowStatisticsPanel(chat_id: int) -> None:
    """Edit the hub message to display the statistics sub-panel."""
    lang = await GetUserLanguage(chat_id)
    text = t(lang, "admin.stats_header")
    keyboard = StatisticsKeyboard(lang)

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


async def ShowDownloadDBPanel(chat_id: int) -> None:
    """Edit the hub message to display the Download DB sub-panel."""
    lang = await GetUserLanguage(chat_id)
    text = t(lang, "admin.stats_db_header")
    keyboard = DownloadDBKeyboard(lang)

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


# --- Stats builders ---


def _pct(part: int, total: int) -> str:
    if total == 0:
        return "0.0%"
    return f"{part / total * 100:.1f}%"


def _top_list(items: list[tuple[str, int]]) -> str:
    if not items:
        return "  —"
    return "\n".join(
        f"  {i + 1}. {name} — {count}" for i, (name, count) in enumerate(items)
    )


async def _BuildUsersStatsText(lang: str) -> str:
    svc = await GetAnalyticsService()
    s = await svc.GetTgUserStats()
    total = s["total"]
    verified = s["verified"]
    return t(
        lang,
        "admin.stats_users",
        total=total,
        verified=verified,
        verified_pct=_pct(verified, total),
        unverified=s["unverified"],
        unverified_pct=_pct(s["unverified"], total),
        blocked=s["blocked"],
        blocked_pct=_pct(s["blocked"], total),
        lang_en=s["lang_en"],
        lang_en_pct=_pct(s["lang_en"], verified or 1),
        lang_ru=s["lang_ru"],
        lang_ru_pct=_pct(s["lang_ru"], verified or 1),
        with_username=s["with_username"],
        with_username_pct=_pct(s["with_username"], total),
        with_about=s["with_about"],
        with_about_pct=_pct(s["with_about"], total),
        new_week=s["new_week"],
        new_month=s["new_month"],
    )


async def _BuildAlumniStatsText(lang: str) -> str:
    svc = await GetAnalyticsService()
    s = await svc.GetNesUserStats()
    top_countries = s["top_countries"]
    top_cities = s["top_cities"]
    top_programs = s["top_programs"]
    top_industries = s["top_industries"]
    top_professional = s["top_professional"]
    assert isinstance(top_countries, list)
    assert isinstance(top_cities, list)
    assert isinstance(top_programs, list)
    assert isinstance(top_industries, list)
    assert isinstance(top_professional, list)
    return t(
        lang,
        "admin.stats_alumni",
        total=s["total"],
        top_countries=_top_list(top_countries),
        top_cities=_top_list(top_cities),
        top_programs=_top_list(top_programs),
        top_industries=_top_list(top_industries),
        top_professional=_top_list(top_professional),
    )


async def _BuildActivityStatsText(lang: str) -> str:
    svc = await GetAnalyticsService()
    s = await svc.GetActivityStats()
    total = s["total"]
    bot_msgs = s["bot"]
    user_msgs = s["user"]
    top_users_raw = s["top_users"]
    assert isinstance(total, int)
    assert isinstance(bot_msgs, int)
    assert isinstance(user_msgs, int)
    assert isinstance(top_users_raw, list)

    ctx = await GetUserContextService()
    top_lines = []
    for i, (chat_id, cnt) in enumerate(top_users_raw):
        username = await ctx.GetTgUser(chat_id=chat_id, column=TgUser.username)
        display = f"@{username}" if username else str(chat_id)
        top_lines.append(f"  {i + 1}. {display} — {cnt}")
    top_users_str = "\n".join(top_lines) if top_lines else "  —"

    return t(
        lang,
        "admin.stats_activity",
        total=total,
        bot=bot_msgs,
        bot_pct=_pct(bot_msgs, total),
        user=user_msgs,
        user_pct=_pct(user_msgs, total),
        today=s["today"],
        week=s["week"],
        top_users=top_users_str,
    )


async def _BuildMatchingStatsText(lang: str) -> str:
    ctx = await GetUserContextService()
    verified_ids = await ctx.GetVerifiedTgUsersChatId()
    eligible_ids = await ctx.GetTgUsersOnCondition(
        condition=TgUser.verified
        & ~TgUser.blocked
        & ~TgUser.matching_paused
        & TgUser.nes_id.isnot(None),
        column=TgUser.chat_id,
    )

    svc = await GetAnalyticsService()
    ms = await svc.GetMatchingStats()

    return t(
        lang,
        "admin.stats_matching",
        eligible=len(eligible_ids),
        verified=len(verified_ids),
        opted_out=ms["opted_out"],
        total_rounds=ms["total_rounds"],
        last_round_date=ms["last_round_date"],
        last_round_assignments=ms["last_round_assignments"],
    )


# --- DB export builders (one per table) ---


async def _ExportTgUser(chat_id: int) -> None:
    svc = await GetAnalyticsService()
    users = await svc.GetAllTgUsers()
    headers = [
        "chat_id",
        "nes_id",
        "nes_email",
        "username",
        "language",
        "about",
        "panel_message_id",
        "verified",
        "blocked",
        "matching_paused",
        "is_admin",
        "created_at",
        "updated_at",
    ]
    rows: list[list[str]] = [
        [
            str(u.chat_id),
            str(u.nes_id or ""),
            str(u.nes_email or ""),
            str(u.username or ""),
            str(u.language or ""),
            str(u.about or ""),
            str(u.panel_message_id or ""),
            str(u.verified),
            str(u.blocked),
            str(u.matching_paused),
            str(u.is_admin),
            str(u.created_at),
            str(u.updated_at),
        ]
        for u in users
    ]
    await SendTemporaryXlsxFile(
        chat_id=chat_id, sheets=[("tg_user", headers, rows)], filename="tg_user"
    )


async def _ExportNesUser(chat_id: int) -> None:
    svc = await GetAnalyticsService()
    users = await svc.GetAllNesUsers()
    headers = [
        "nes_id",
        "name",
        "city",
        "region",
        "country",
        "program",
        "class_name",
        "hobbies",
        "industry_expertise",
        "country_expertise",
        "professional_expertise",
        "main_work",
        "additional_work",
        "pre_nes_education",
        "post_nes_education",
        "mynes_text",
        "about_text",
        "enriched_text",
        "created_at",
        "updated_at",
    ]
    rows: list[list[str]] = [
        [
            str(u.nes_id),
            str(u.name or ""),
            str(u.city or ""),
            str(u.region or ""),
            str(u.country or ""),
            str(u.program or ""),
            str(u.class_name or ""),
            str(u.hobbies or ""),
            str(u.industry_expertise or ""),
            str(u.country_expertise or ""),
            str(u.professional_expertise or ""),
            str(u.main_work or ""),
            str(u.additional_work or ""),
            str(u.pre_nes_education or ""),
            str(u.post_nes_education or ""),
            str(u.mynes_text or ""),
            str(u.about_text or ""),
            str(u.enriched_text or ""),
            str(u.created_at),
            str(u.updated_at),
        ]
        for u in users
    ]
    await SendTemporaryXlsxFile(
        chat_id=chat_id, sheets=[("nes_user", headers, rows)], filename="nes_user"
    )


async def _ExportMessage(chat_id: int) -> None:
    svc = await GetAnalyticsService()
    messages = await svc.GetAllMessages()
    headers = ["message_id", "chat_id", "side", "text", "time"]
    rows: list[list[str]] = [
        [str(m.message_id), str(m.chat_id), m.side.value, m.text, str(m.time)]
        for m in messages
    ]
    await SendTemporaryXlsxFile(
        chat_id=chat_id, sheets=[("message", headers, rows)], filename="message"
    )


# --- Handlers ---


@router.callback_query(
    StatisticsCallbackData.filter(F.action == StatisticsAction.Users)
)
async def StatsUsers(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    lang = await GetUserLanguage(callback_query.from_user.id)
    text = await _BuildUsersStatsText(lang)
    await SendMessage(chat_id=callback_query.message.chat.id, text=text)


@router.callback_query(
    StatisticsCallbackData.filter(F.action == StatisticsAction.Alumni)
)
async def StatsAlumni(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    lang = await GetUserLanguage(callback_query.from_user.id)
    text = await _BuildAlumniStatsText(lang)
    await SendMessage(chat_id=callback_query.message.chat.id, text=text)


@router.callback_query(
    StatisticsCallbackData.filter(F.action == StatisticsAction.Activity)
)
async def StatsActivity(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    lang = await GetUserLanguage(callback_query.from_user.id)
    text = await _BuildActivityStatsText(lang)
    await SendMessage(chat_id=callback_query.message.chat.id, text=text)


@router.callback_query(
    StatisticsCallbackData.filter(F.action == StatisticsAction.Matching)
)
async def StatsMatching(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    lang = await GetUserLanguage(callback_query.from_user.id)
    text = await _BuildMatchingStatsText(lang)
    await SendMessage(chat_id=callback_query.message.chat.id, text=text)


@router.callback_query(
    StatisticsCallbackData.filter(F.action == StatisticsAction.DownloadDB)
)
async def StatsDownloadDB(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await ShowDownloadDBPanel(callback_query.message.chat.id)


@router.callback_query(BackToStatisticsCallbackData.filter())
async def BackToStats(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await ShowStatisticsPanel(callback_query.message.chat.id)


@router.callback_query(
    DownloadDBCallbackData.filter(F.action == DownloadDBAction.TgUser)
)
async def DownloadTgUser(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await _ExportTgUser(callback_query.message.chat.id)


@router.callback_query(
    DownloadDBCallbackData.filter(F.action == DownloadDBAction.NesUser)
)
async def DownloadNesUser(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await _ExportNesUser(callback_query.message.chat.id)


@router.callback_query(
    DownloadDBCallbackData.filter(F.action == DownloadDBAction.Message)
)
async def DownloadMessage(callback_query: types.CallbackQuery) -> None:
    assert isinstance(callback_query.message, types.Message)
    await callback_query.answer()
    await _ExportMessage(callback_query.message.chat.id)
