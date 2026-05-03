import logging

from cachetools import TTLCache

from nespresso.bot.lifecycle.creator import bot
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

# Cache live usernames briefly to avoid hammering Telegram + DB on every
# inbound/outbound message (GetChatUserLoggingPart fires per message).
_USERNAME_CACHE: TTLCache[int, str | None] = TTLCache(maxsize=10000, ttl=300)


async def GetTgUsername(chat_id: int) -> str | None:
    if chat_id in _USERNAME_CACHE:
        return _USERNAME_CACHE[chat_id]

    try:
        chat = await bot.get_chat(chat_id)
        username = chat.username

        ctx = await GetUserContextService()
        db_username = await ctx.GetTgUser(
            chat_id=chat_id,
            column=TgUser.username,
        )

        if username != db_username:
            try:
                await ctx.UpdateTgUser(
                    chat_id=chat_id,
                    column=TgUser.username,
                    value=username,
                )
            except Exception:
                # User may not exist in DB yet (e.g. first /start before insert)
                logging.debug(
                    f"Could not persist username for chat_id={chat_id}",
                    exc_info=True,
                )

        _USERNAME_CACHE[chat_id] = username
        return username

    except Exception as e:
        logging.warning(f"Failed to get chat info for chat_id={chat_id}: {e}")
        return None


async def GetChatUserLoggingPart(chat_id: int) -> str:
    username = await GetTgUsername(chat_id) or "-/-"
    username = "(" + username + ")"

    return f"chat_id={chat_id:<10} {username:<25}"
