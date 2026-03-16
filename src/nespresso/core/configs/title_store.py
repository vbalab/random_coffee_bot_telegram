import json

from nespresso.core.configs.paths import PATH_TITLE_STORE

_DEFAULTS: dict[str, str] = {
    "en": "👋 Welcome!",
    "ru": "👋 Добро пожаловать!",
}


def GetTitle(lang: str) -> str:
    """Return custom title for the language, falling back to the built-in default."""
    if PATH_TITLE_STORE.exists():
        try:
            data: dict[str, str] = json.loads(
                PATH_TITLE_STORE.read_text(encoding="utf-8")
            )
            if lang in data:
                return data[lang]
        except Exception:
            pass
    return _DEFAULTS.get(lang, "👋")


def GetBothTitles() -> tuple[str, str]:
    """Return (en_title, ru_title) using custom overrides where available."""
    return GetTitle("en"), GetTitle("ru")


def SetTitle(lang: str, title: str) -> None:
    """Persist a custom title for the given language."""
    data: dict[str, str] = {}
    if PATH_TITLE_STORE.exists():
        try:
            data = json.loads(PATH_TITLE_STORE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[lang] = title
    PATH_TITLE_STORE.parent.mkdir(parents=True, exist_ok=True)
    PATH_TITLE_STORE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
