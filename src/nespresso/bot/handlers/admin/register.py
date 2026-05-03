from aiogram import Dispatcher

from nespresso.bot.handlers.admin.commands import (
    admin,
    admins,
    blocking,
    logs,
    matching,
    messages,
    send,
    senda,
    statistics,
    title,
)
from nespresso.bot.lib.message.filters import AdminFilter


def RegisterAdminHandlers(dp: Dispatcher) -> None:
    routers = [
        admin.router,
        admins.router,
        logs.router,
        messages.router,
        send.router,
        senda.router,
        blocking.router,
        matching.router,
        statistics.router,
        title.router,
    ]
    # Gate every admin handler so non-admins can't trigger admin actions
    # even if they reverse-engineer the callback data format.
    for router in routers:
        router.message.filter(AdminFilter())
        router.callback_query.filter(AdminFilter())

    dp.include_routers(*routers)
