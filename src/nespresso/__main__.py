import asyncio
import logging

from nespresso.api.request import CloseMyNesClient
from nespresso.api.sync import SyncFromMyNES
from nespresso.bot.handlers.admin.register import RegisterAdminHandlers
from nespresso.bot.handlers.client.email.verification import TestEmail  # TODO
from nespresso.bot.handlers.client.register import RegisterClientHandlers
from nespresso.bot.handlers.common.register import (
    RegisterHandlerCancel,
    RegisterHandlerZeroMessage,
)
from nespresso.bot.lib.message.middleware import SetBotMiddleware
from nespresso.bot.lib.notifications import admin
from nespresso.bot.lib.notifications.erroring import SetExceptionHandlers
from nespresso.bot.lib.notifications.pending import ProcessPendingUpdates
from nespresso.bot.lifecycle.creator import bot, dp
from nespresso.recsys.searching.llm.client import CloseLLMClient
from nespresso.bot.lifecycle.menu import SetMenu
from nespresso.bot.lifecycle.sync_scheduler import (
    StartSyncScheduler,
    StopSyncScheduler,
)
from nespresso.core.configs.paths import EnsurePaths
from nespresso.core.logs import flow as logs
from nespresso.core.logs.bot import LoggerSetup
from nespresso.db.session import EnsureDB, engine
from nespresso.recsys.searching.client import CloseOpenSearchClient
from nespresso.recsys.searching.index import EnsureOpenSearchIndex
from nespresso.recsys.searching.search_pipeline import EnsureSearchPipeline


async def EnsureDependencies() -> None:
    await EnsureDB()
    await EnsureOpenSearchIndex()
    await EnsureSearchPipeline()


async def OnStartup() -> None:
    await SetMenu()
    RegisterHandlerCancel(dp)
    RegisterAdminHandlers(dp)
    RegisterClientHandlers(dp)
    RegisterHandlerZeroMessage(dp)
    SetBotMiddleware(dp)

    await admin.NotifyOnStartup()
    await ProcessPendingUpdates()

    StartSyncScheduler()


async def OnShutdown() -> None:
    await StopSyncScheduler()

    await admin.NotifyOnShutdown()

    await CloseOpenSearchClient()
    await CloseMyNesClient()
    await CloseLLMClient()
    await engine.dispose()

    await logs.LoggerShutdown()


async def main() -> None:
    EnsurePaths()
    await logs.LoggerStart(LoggerSetup)

    await EnsureDependencies()

    dp.startup.register(OnStartup)
    dp.shutdown.register(OnShutdown)

    SetExceptionHandlers()

    await TestEmail()

    # Block until the directory is mirrored so the bot only starts serving users
    # once Find/matching data is fully populated. On an intact index this is a
    # few seconds (nothing changed); on a wiped/first-run index it is the full
    # re-index and can take a while — that is the intended trade-off.
    logging.info("Startup MyNES sync running; bot will start serving once it's done.")
    startup_report = await SyncFromMyNES(trigger="startup")
    if not startup_report.ok:
        logging.warning(
            "Startup MyNES sync did not complete cleanly "
            f"(error={startup_report.error}); starting the bot anyway."
        )

    await dp.start_polling(bot, drop_pending_updates=True)


# $ python -m nespresso
if __name__ == "__main__":
    asyncio.run(main())
