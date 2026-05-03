from aiogram import types

from nespresso.db.models.message import MessageSide
from nespresso.db.repositories.message import MessageRepository


class MessageService:
    def __init__(self, message_repo: MessageRepository):
        self.message_repo = message_repo

        self.GetRecentMessages = self.message_repo.GetRecentMessages

    async def RegisterIncomingMessage(self, message: types.Message) -> None:
        await self.message_repo.AddMessage(
            message_id=message.message_id,
            chat_id=message.chat.id,
            text=message.text or message.caption or "",
            side=MessageSide.User,
        )

    async def RegisterOutgoingMessage(self, message: types.Message) -> None:
        await self.message_repo.AddMessage(
            message_id=message.message_id,
            chat_id=message.chat.id,
            text=message.text or message.caption or "",
            side=MessageSide.Bot,
        )
