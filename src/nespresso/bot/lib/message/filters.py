from aiogram import types
from aiogram.filters import Filter

from nespresso.core.configs.admin_store import admin_store


class AdminFilter(Filter):
    async def __call__(self, event: types.Message | types.CallbackQuery) -> bool:
        if isinstance(event, types.Message):
            return admin_store.Contains(event.chat.id)
        if isinstance(event, types.CallbackQuery):
            return admin_store.Contains(event.from_user.id)
        return False
