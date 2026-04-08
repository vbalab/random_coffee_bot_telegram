import time

from aiogram import Router, types
from aiogram.filters.command import Command
from aiogram.fsm.context import FSMContext

from nespresso.bot.handlers.client.commands.start import StartStates
from nespresso.bot.lib.message.i18n import t_user
from nespresso.bot.lib.message.io import SendMessage

router = Router()


@router.message(Command("cancel"))
async def CommandCancel(message: types.Message, state: FSMContext) -> None:
    """
    Handles the /cancel command, allowing users to cancel ongoing interactions
    and removing any active reply keyboards. It also clears the user's state.
    """
    data = await state.get_data()
    cooldown_until = data.get("cooldown_until")

    await SendMessage(
        chat_id=message.chat.id,
        text=await t_user(message.chat.id, "common.canceled"),
        reply_markup=types.ReplyKeyboardRemove(),
    )

    await state.clear()

    if cooldown_until is not None and time.time() < cooldown_until:
        await state.set_state(StartStates.EmailGet)
        await state.set_data({"cooldown_until": cooldown_until})
