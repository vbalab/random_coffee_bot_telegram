from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService

_DEFAULT_ADMIN_IDS = [749410326]


async def GetAdminIds() -> list[int]:
    ctx = await GetUserContextService()
    ids = await ctx.GetAdminChatIds()
    for chat_id in _DEFAULT_ADMIN_IDS:
        if chat_id not in ids:
            ids.append(chat_id)
    return ids


async def IsAdmin(chat_id: int) -> bool:
    if chat_id in _DEFAULT_ADMIN_IDS:
        return True
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
    """Returns False if not an admin or if chat_id is a default admin."""
    if chat_id in _DEFAULT_ADMIN_IDS:
        return False
    ctx = await GetUserContextService()
    current = await ctx.GetTgUser(chat_id, TgUser.is_admin)
    if not current:
        return False
    await ctx.UpdateTgUser(chat_id, TgUser.is_admin, False)
    return True
