from nespresso.db.repositories.match import MatchRepository
from nespresso.db.repositories.message import MessageRepository
from nespresso.db.repositories.nes_user import NesUserRepository
from nespresso.db.repositories.tg_user import TgUserRepository
from nespresso.db.services.matching import MatchingService
from nespresso.db.services.message import MessageService
from nespresso.db.services.user import UserService
from nespresso.db.session import AsyncSessionLocal


class UserContextService(UserService, MessageService, MatchingService):
    """
    Combines UserService, MessageService, and MatchingService into a single context service.
    """

    def __init__(
        self,
        user_service: UserService,
        message_service: MessageService,
        matching_service: MatchingService,
    ):
        UserService.__init__(
            self,
            tg_user_repo=user_service.tg_user_repo,
            nes_user_repo=user_service.nes_user_repo,
        )
        MessageService.__init__(self, message_service.message_repo)
        MatchingService.__init__(self, matching_service.match_repo)


async def GetUserContextService() -> UserContextService:
    tg_user_repo = TgUserRepository(AsyncSessionLocal)
    nes_user_repo = NesUserRepository(AsyncSessionLocal)
    message_repo = MessageRepository(AsyncSessionLocal)
    match_repo = MatchRepository(AsyncSessionLocal)

    user_service = UserService(tg_user_repo=tg_user_repo, nes_user_repo=nes_user_repo)
    message_service = MessageService(message_repo)
    matching_service = MatchingService(match_repo)

    return UserContextService(user_service, message_service, matching_service)
