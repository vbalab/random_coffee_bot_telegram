import logging
import re
from logging import StreamHandler
from logging.handlers import QueueHandler, QueueListener, TimedRotatingFileHandler
from pathlib import Path
from queue import Queue
from typing import Any

from colorlog import ColoredFormatter
from pythonjsonlogger.json import JsonFormatter

logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("aiogram").setLevel(logging.INFO)
logging.getLogger("opensearch").setLevel(logging.INFO)
logging.getLogger("filelock").setLevel(logging.INFO)
logging.getLogger("apscheduler.scheduler").setLevel(logging.INFO)


class _DemoteSuccessfulHttpx(logging.Filter):
    """
    httpx logs every request at INFO ('HTTP Request: ... "HTTP/1.1 200 OK"').
    Successful (2xx) responses are noise — demote them to DEBUG so they stay out
    of the INFO console but remain in the DEBUG file log. Non-2xx requests keep
    their INFO level so real failures stay visible.

    Attached to the `httpx` logger (not a handler) so the level change happens
    before the QueueListener's per-handler level check.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        status = next(
            (a for a in record.args if isinstance(a, int) and 100 <= a < 600),
            None,
        ) if isinstance(record.args, tuple) else None
        if status is not None and 200 <= status < 300:
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
        return True


logging.getLogger("httpx").addFilter(_DemoteSuccessfulHttpx())

_CONSOLE_FORMAT = ColoredFormatter(
    "%(log_color)s%(levelname)-8s%(reset)s :: %(asctime)s.%(msecs)03d :: %(message)s",
    datefmt="%m-%d %H:%M:%S",
    reset=True,
    log_colors={
        "DEBUG": "cyan",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "red,bg_white",
    },
)


_FILE_FORMAT = JsonFormatter(
    fmt="%(levelname)s %(asctime)s %(message)s %(name)s %(filename)s %(lineno)d",
    json_ensure_ascii=False,
    json_indent=4,
)

# "Quick" logs: the same concise layout as the colored console, but plain (no ANSI)
# so the downloaded file is readable. Written to its own file at INFO.
_QUICK_FILE_FORMAT = logging.Formatter(
    "%(levelname)-8s :: %(asctime)s.%(msecs)03d :: %(message)s",
    datefmt="%m-%d %H:%M:%S",
)


class FilterOutLogs(logging.Filter):
    def __init__(self, startswith: str, level: int = 100):  # 100 - block of any logs
        super().__init__()

        self.startswith = startswith
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return not (
            record.levelno < self.level and record.name.startswith(self.startswith)
        )


class RemoveColorCodesFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.RemoveColorCodes(str(record.msg))
        return True

    @staticmethod
    def RemoveColorCodes(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", text)


def CreateFileHandler(
    path: Path,
    level: int,
    filters: list[logging.Filter] | None = None,
    formatter: logging.Formatter | None = None,
) -> TimedRotatingFileHandler:
    handler = TimedRotatingFileHandler(
        filename=path,
        when="midnight",
        interval=1,
        backupCount=365 * 3,
        encoding="utf-8",
        utc=True,
    )
    handler.setLevel(level)
    handler.setFormatter(formatter if formatter is not None else _FILE_FORMAT)

    handler.addFilter(RemoveColorCodesFilter())

    if filters:
        for filt in filters:
            handler.addFilter(filt)

    return handler


def CreateQuickFileHandler(
    path: Path, level: int, filters: list[logging.Filter] | None = None
) -> TimedRotatingFileHandler:
    """File handler mirroring the console layout (plain, no ANSI), for 'quick' logs."""
    return CreateFileHandler(path, level, filters, _QUICK_FILE_FORMAT)


def CreateConsoleHandler(
    level: int, filters: list[logging.Filter] | None = None
) -> StreamHandler[Any]:
    handler = StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(_CONSOLE_FORMAT)

    if filters:
        for filt in filters:
            handler.addFilter(filt)

    return handler


def CreateListener(*handlers: logging.Handler) -> QueueListener:
    que: Queue[Any] = Queue()

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(QueueHandler(que))

    listener = QueueListener(que, *handlers, respect_handler_level=True)

    return listener
