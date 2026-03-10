import json
from pathlib import Path

from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = {"en", "ru"}

_TRANSLATIONS_DIR = Path(__file__).resolve().parents[3] / "translations"
_TRANSLATIONS_CACHE: dict[str, dict[str, str]] = {}


def _load_translations(lang: str) -> dict[str, str]:
    if lang in _TRANSLATIONS_CACHE:
        return _TRANSLATIONS_CACHE[lang]

    file_path = _TRANSLATIONS_DIR / f"{lang}.json"
    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    _TRANSLATIONS_CACHE[lang] = data
    return data


def t(lang: str, key: str, **kwargs: int | str) -> str:
    safe_lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE

    lang_map = _load_translations(safe_lang)
    default_map = _load_translations(DEFAULT_LANGUAGE)

    template = lang_map.get(key, default_map.get(key, key))

    if kwargs:
        return template.format(**kwargs)

    return template


async def GetUserLanguage(chat_id: int) -> str:
    ctx = await GetUserContextService()
    lang = await ctx.GetTgUser(chat_id=chat_id, column=TgUser.language)

    if lang is None or lang not in SUPPORTED_LANGUAGES:
        return DEFAULT_LANGUAGE

    return lang


async def GetUserLanguageOrNone(chat_id: int) -> str | None:
    ctx = await GetUserContextService()
    lang = await ctx.GetTgUser(chat_id=chat_id, column=TgUser.language)

    if lang is None:
        return None

    if lang not in SUPPORTED_LANGUAGES:
        return DEFAULT_LANGUAGE

    return lang


async def SetUserLanguage(chat_id: int, lang: str) -> None:
    safe_lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE

    ctx = await GetUserContextService()
    await ctx.UpdateTgUser(
        chat_id=chat_id,
        column=TgUser.language,
        value=safe_lang,
    )


async def t_user(chat_id: int, key: str, **kwargs: int | str) -> str:
    lang = await GetUserLanguage(chat_id)
    return t(lang, key, **kwargs)
