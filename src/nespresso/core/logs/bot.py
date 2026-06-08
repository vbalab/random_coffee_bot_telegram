import logging
from logging.handlers import QueueListener

from nespresso.core.configs.paths import PATH_BOT_LOGS, PATH_BOT_QUICK_LOGS
from nespresso.core.logs.settings import (
    CreateConsoleHandler,
    CreateFileHandler,
    CreateListener,
    CreateQuickFileHandler,
    FilterOutLogs,
)


async def LoggerSetup() -> QueueListener:
    # Same noise-filtering for the console and the "quick" file, so they match.
    quick_filters: list[logging.Filter] = [
        FilterOutLogs("sqlalchemy.engine", logging.WARNING),
        FilterOutLogs("aiogram", logging.WARNING),
        FilterOutLogs("opensearch", logging.WARNING),
        FilterOutLogs("apscheduler.scheduler", logging.WARNING),
    ]

    # Console (terminal) — INFO, colored.
    console_handler = CreateConsoleHandler(logging.INFO, filters=quick_filters)
    # "quick" logs — same INFO terminal layout, saved to a plain-text file.
    quick_file_handler = CreateQuickFileHandler(
        PATH_BOT_QUICK_LOGS, logging.INFO, filters=quick_filters
    )
    # "debug" logs — full structured JSON at DEBUG (everything).
    bot_file_handler = CreateFileHandler(PATH_BOT_LOGS, logging.DEBUG)

    listener: QueueListener = CreateListener(
        console_handler, quick_file_handler, bot_file_handler
    )

    return listener
