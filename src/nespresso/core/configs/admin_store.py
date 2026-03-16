from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService


async def GetAdminIds() -> list[int]:
    ctx = await GetUserContextService()
    return await ctx.GetAdminChatIds()


async def IsAdmin(chat_id: int) -> bool:
    ctx = await GetUserContextService()
    result = await ctx.GetTgUser(chat_id, TgUser.is_admin)
    return bool(result)


async def AddAdmin(chat_id: int) -> bool:
    """Returns False if already an admin."""
    ctx = await GetUserContextService()
    current = await ctx.GetTgUser(chat_id, TgUser.is_admin)
    if current:
        return False
    await ctx.UpdateTgUser(chat_id, TgUser.is_admin, True)
    return True


async def RemoveAdmin(chat_id: int) -> bool:
    """Returns False if not an admin."""
    ctx = await GetUserContextService()
    current = await ctx.GetTgUser(chat_id, TgUser.is_admin)
    if not current:
        return False
    await ctx.UpdateTgUser(chat_id, TgUser.is_admin, False)
    return True
