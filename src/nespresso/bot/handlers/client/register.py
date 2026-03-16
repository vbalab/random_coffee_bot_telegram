from aiogram import Dispatcher

from nespresso.bot.handlers.client.commands import about, find, hub, settings, start


def RegisterClientHandlers(dp: Dispatcher) -> None:
    dp.include_routers(
        hub.router,
        start.router,
        find.router,
        about.router,
        settings.router,
    )
