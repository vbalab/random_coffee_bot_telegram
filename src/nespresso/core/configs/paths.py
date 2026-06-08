from pathlib import Path

_DIR_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_DIR_DATA = _DIR_ROOT / "data"
_DIR_LOGS = _DIR_DATA / "logs"
_DIR_BOT_LOGS = _DIR_LOGS / "bot"
_DIR_RECSYS = _DIR_DATA / "recsys"
_DIR_TITLE = _DIR_DATA / "title"

DIR_TEMP = _DIR_DATA / "temp"
DIR_EMBEDDING = _DIR_RECSYS / "embedding" / "model"

_dirs = [
    _DIR_DATA,
    _DIR_LOGS,
    _DIR_BOT_LOGS,
    DIR_TEMP,
    _DIR_RECSYS,
    DIR_EMBEDDING,
    _DIR_TITLE,
]

PATH_ENV = _DIR_ROOT / ".env"
# "debug" logs: full structured JSON at DEBUG. "quick" logs: concise terminal-style
# at INFO (same layout as the console). Both downloadable from the admin Logs panel.
PATH_BOT_LOGS = _DIR_BOT_LOGS / "bot.log"
PATH_BOT_QUICK_LOGS = _DIR_BOT_LOGS / "quick.log"
PATH_API_LOGS = _DIR_LOGS / "api" / "api.log"
PATH_TITLE_STORE = _DIR_TITLE / "title.json"

PATH_TERMS_OF_USE = _DIR_ROOT / "docs" / "papers" / "terms_of_service.pdf"


def EnsurePaths() -> None:
    for directory in _dirs:
        directory.mkdir(parents=True, exist_ok=True)

    if not PATH_ENV.exists():
        raise FileNotFoundError("`.env` file not found")
