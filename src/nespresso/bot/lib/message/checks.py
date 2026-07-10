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


async def IsUnshared(chat_id: int) -> bool:
    """
    True if a VERIFIED user is no longer shared in the MyNES directory — i.e. their
    linked ``NesUser`` is missing or ``listed=False`` because they turned off "Show
    in a class' directory" and the hourly sync delisted them.

    Such users are paused (blocked from using the bot) until they re-enable sharing:
    a re-list flips ``listed`` back on the next sync and this gate lifts
    automatically — no re-registration, no stored flag. Admins and not-yet-verified
    users (still in registration, gated separately at the confirm step) are never
    caught here, so this only pauses fully-registered alumni who opted back out.
    """
    if await IsAdmin(chat_id):
        return False

    ctx = await GetUserContextService()
    tg_user = await ctx.GetTgUser(chat_id=chat_id)
    if tg_user is None or not tg_user.verified or tg_user.nes_id is None:
        return False

    nes_user = await ctx.GetNesUser(nes_id=tg_user.nes_id)
    return nes_user is None or not nes_user.listed
