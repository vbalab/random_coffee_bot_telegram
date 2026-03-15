from aiogram import Dispatcher

from nespresso.bot.handlers.client.commands import find, hub, start


def RegisterClientHandlers(dp: Dispatcher) -> None:
    dp.include_routers(
        hub.router,
        start.router,
        find.router,
    )
