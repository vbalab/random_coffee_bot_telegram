from nespresso.core.configs.admin_store import IsAdmin
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService


async def CheckVerified(chat_id: int) -> bool:
    if await IsAdmin(chat_id):
        return True

    ctx = await GetUserContextService()

    verified = await ctx.GetTgUser(
        chat_id=chat_id,
        column=TgUser.verified,
    )

    return verified if verified else False
