import logging

from nespresso.bot.lib.chat.block import CheckIfBlocked
from nespresso.bot.lib.message.io import ContextIO, ReceiveMessage, SendMessage
from nespresso.bot.lifecycle.creator import bot


async def ProcessPendingUpdates() -> None:
    """
    Notifies users with pending updates when the bot becomes active again.
    Retrieves any pending updates, logs the messages, and prompts users to try again.
    """
    notified_users = set()

    while True:
        updates = await bot.get_updates(offset=None, timeout=1)

        for update in updates:
            # One malformed / mishandled pending update must not crash the whole
            # startup drain — log it and move on to the next update.
            try:
                message = update.message

                if message is None:
                    continue

                chat_id = message.chat.id

                # Mirror MessageLoggingMiddleware: blocked (admin- or spam-blocked)
                # users are skipped entirely. The old code replied to them
                # directly, bypassing that gate.
                if await CheckIfBlocked(chat_id):
                    continue

                await ReceiveMessage(
                    message=message,
                    context=ContextIO.Pending,
                )

                if chat_id not in notified_users:
                    await SendMessage(
                        chat_id=chat_id,
                        text="Bot has been inactive.\nPlease try again!",
                        context=ContextIO.Pending,
                    )

                    notified_users.add(chat_id)
            except Exception:
                logging.warning(
                    "Failed to process a pending update.", exc_info=True
                )
                continue

        if updates:
            await bot.get_updates(offset=updates[-1].update_id + 1)
        else:
            break
