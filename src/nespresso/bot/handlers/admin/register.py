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
)


def RegisterAdminHandlers(dp: Dispatcher) -> None:
    dp.include_routers(
        admin.router,
        admins.router,
        logs.router,
        messages.router,
        send.router,
        senda.router,
        blocking.router,
        matching.router,
        statistics.router,
    )
