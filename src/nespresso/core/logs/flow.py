import logging
from collections.abc import Awaitable, Callable
from logging.handlers import QueueListener

_LISTENER: QueueListener | None = None


async def LoggerStart(setup: Callable[[], Awaitable[QueueListener]]) -> None:
    global _LISTENER
    listener = await setup()
    listener.start()
    _LISTENER = listener

    logging.info("# Logging started.")


async def LoggerShutdown() -> None:
    global _LISTENER
    logging.info("# Logging stopped.")

    if _LISTENER is not None:
        _LISTENER.stop()  # flushes queue + joins listener thread
        _LISTENER = None

    logging.shutdown()
