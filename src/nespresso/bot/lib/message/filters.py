from aiogram import types
from aiogram.filters import Filter

from nespresso.core.configs.admin_store import admin_store


class AdminFilter(Filter):
    async def __call__(self, message: types.Message) -> bool:
        return admin_store.Contains(message.chat.id)
