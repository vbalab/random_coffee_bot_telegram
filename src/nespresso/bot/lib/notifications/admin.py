import logging

from aiogram import types

from nespresso.bot.lib.message.io import SendDocument, SendMessage
from nespresso.core.configs.admin_store import admin_store
from nespresso.core.configs.paths import PATH_BOT_LOGS


async def NotifyOnStartup() -> None:
    logging.info("# Bot started.")

    for admin in admin_store.GetIds():
        await SendMessage(chat_id=admin, text="# Bot started.")


async def NotifyOnShutdown() -> None:
    for admin in admin_store.GetIds():
        await SendDocument(
            chat_id=admin,
            document=types.FSInputFile(PATH_BOT_LOGS),
            caption="# Bot stopped.",
        )

    logging.info("# Bot stopped.")
