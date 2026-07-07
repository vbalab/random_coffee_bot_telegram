import logging

from aiogram import types

from nespresso.bot.lib.message.io import SendDocument, SendMessage
from nespresso.core.configs.admin_store import GetAdminIds
from nespresso.core.configs.paths import PATH_BOT_LOGS


async def NotifyOnStartup() -> None:
    logging.info("# Bot started.")

    for admin in await GetAdminIds():
        await SendMessage(chat_id=admin, text="# Bot started.")


async def NotifyOnShutdown() -> None:
    for admin in await GetAdminIds():
        await SendDocument(
            chat_id=admin,
            document=types.FSInputFile(PATH_BOT_LOGS),
            caption="# Bot stopped.",
        )

    logging.info("# Bot stopped.")


async def NotifyOnLLMOutage(message: str) -> None:
    """Broadcast an LLM-outage alert (e.g. Claude API out of credits) to all
    admins. Wired as the alert hook in `recsys.searching.llm.alerts` at startup."""
    for admin in await GetAdminIds():
        await SendMessage(chat_id=admin, text=message)
