import logging
import random
from dataclasses import dataclass

from nespresso.bot.lib.message.io import PersonalMsg, SendMessagesToGroup
from nespresso.db.models.tg_user import TgUser
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.matching.emoji import RandomEmoji
from nespresso.recsys.profile import Profile


@dataclass
class User:
    chat_id: int
    emoji: str


@dataclass
class Pair:
    user: User
    assigned: User


def MatchUsers(chat_ids: list[int]) -> list[Pair]:
    users: list[User] = [User(chat_id, RandomEmoji()) for chat_id in chat_ids]
    assigned = users.copy()

    if not assigned:
        return []

    # 1/3 chance of success
    while True:
        random.shuffle(assigned)

        pairs = zip(users, assigned, strict=True)

        if all(u is not v for u, v in pairs):
            break

    return [Pair(user=u, assigned=v) for u, v in zip(users, assigned, strict=True)]


async def CreateMatching() -> list[Pair]:
    ctx = await GetUserContextService()

    chat_ids = await ctx.GetVerifiedTgUsersChatId()

    return MatchUsers(chat_ids)


async def SendMatchingInfo(pairs: list[Pair]) -> None:
    ctx = await GetUserContextService()

    messages: list[PersonalMsg] = []
    for pair in pairs:
        assigned_nes_id = await ctx.GetTgUser(
            chat_id=pair.assigned.chat_id,
            column=TgUser.nes_id,
        )
        assert assigned_nes_id is not None

        if assigned_nes_id is None:
            logging.error(
                f"chat_id={pair.assigned.chat_id} doesn't have nes_id while participating in matching"
            )
            continue

        profile = await Profile.FromNesId(assigned_nes_id)
        description = profile.DescribeProfile()

        # TODO: add explanation
        text = f"Hi! You emoji is {pair.user.emoji}\n\n[Explain]\n\n{description}"

        message = PersonalMsg(chat_id=pair.user.chat_id, text=text)
        messages.append(message)

    await SendMessagesToGroup(messages)


async def MatchingPipeline() -> None:
    logging.info("MatchingPipeline: Actualizing Users")
    # TODO: send info about matching and that soon there will be matching. this way you'll get data of who have blocked bot
    # TODO: actualize users

    logging.info("MatchingPipeline: Creating Matching")
    pairs = await CreateMatching()
    logging.info("MatchingPipeline: Sending Matching Info")
    await SendMatchingInfo(pairs)
