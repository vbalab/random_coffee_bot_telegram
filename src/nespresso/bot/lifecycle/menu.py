from aiogram.types import BotCommand

from nespresso.bot.lifecycle.creator import bot


async def SetMenu() -> None:
    commands = [
        BotCommand(command="/start", description="Open menu"),
        BotCommand(command="/cancel", description="Cancel current state"),
    ]

    await bot.set_my_commands(commands)
