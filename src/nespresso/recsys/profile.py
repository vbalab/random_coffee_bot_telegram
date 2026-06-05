from __future__ import annotations

from dataclasses import dataclass

from nespresso.bot.lib.chat.username import GetTgUsername
from nespresso.db.services.user_context import GetUserContextService


@dataclass
class Profile:
    nes_id: int
    username: str | None
    email: str | None
    about: str | None
    nes_self: str | None
    nes_work: str | None

    @classmethod
    async def FromNesId(cls, nes_id: int) -> Profile:
        username = None
        email = None
        about = None
        nes_self = None
        nes_work = None

        ctx = await GetUserContextService()
        chat_id = await ctx.GetTgChatIdBy(nes_id=nes_id)

        if chat_id:
            if tg := await GetTgUsername(chat_id):
                username = tg

            if tg_user := await ctx.GetTgUser(chat_id=chat_id):
                if tg_user.about:
                    about = tg_user.about

                if tg_user.nes_email:
                    email = tg_user.nes_email

        if nes_user := await ctx.GetNesUser(nes_id=nes_id):
            nes_self = nes_user.SelfDescription()
            nes_work = nes_user.WorkDescription()

            if email is None and nes_user.nes_email:
                email = nes_user.nes_email

        # TODO: add programm'year and format.

        return cls(
            nes_id=nes_id,
            username=username,
            email=email,
            about=about,
            nes_self=nes_self,
            nes_work=nes_work,
        )

    def DescribeProfile(self) -> str:
        text = ""
        text += f"{self.nes_self}\n\n" if self.nes_self else ""

        text += f"@{self.username}\n" if self.username else ""
        text += f"{self.email}\n" if self.email else ""
        text += "\n" if self.username or self.email else ""

        text += f"About:\n{self.about}\n\n" if self.about else ""

        text += f"{self.nes_work}" if self.nes_work else ""

        return text
