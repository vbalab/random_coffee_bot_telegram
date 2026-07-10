from aiogram import types
from aiogram.filters import Filter

from nespresso.db.services.admin import IsAdmin


class AdminFilter(Filter):
    async def __call__(self, event: types.Message | types.CallbackQuery) -> bool:
        if isinstance(event, types.Message):
            return await IsAdmin(event.chat.id)
        if isinstance(event, types.CallbackQuery):
            return await IsAdmin(event.from_user.id)
        return False
