from aiogram import Dispatcher

from nespresso.bot.handlers.admin.commands.matching import feedback_router
from nespresso.bot.handlers.client.commands import about, find, hub, settings, start


def RegisterClientHandlers(dp: Dispatcher) -> None:
    dp.include_routers(
        hub.router,
        start.router,
        find.router,
        about.router,
        settings.router,
        # Feedback buttons are DMed to ordinary matched alumni, not admins — this
        # router must stay OUTSIDE RegisterAdminHandlers' AdminFilter gate.
        feedback_router,
    )
