from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from nespresso.bot.lib.message.i18n import t_user
from nespresso.bot.lib.message.io import ContextIO, SendMessage

router = Router()


@router.message(F.content_type == "text")
async def ZeroMessageText(message: types.Message) -> None:
    await SendMessage(
        chat_id=message.chat.id,
        text=await t_user(message.chat.id, "zero.not_in_command"),
        context=ContextIO.ZeroMessage,
    )


@router.message()
async def NoTextMessage(message: types.Message, state: FSMContext) -> None:
    current_state = await state.get_state()

    if current_state is None:
        text = await t_user(message.chat.id, "zero.not_text_idle")
    else:
        text = await t_user(message.chat.id, "zero.not_text_in_state")

    await SendMessage(chat_id=message.chat.id, text=text, context=ContextIO.NoText)
