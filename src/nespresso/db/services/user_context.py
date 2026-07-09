from nespresso.db.repositories.match import MatchRepository
from nespresso.db.repositories.message import MessageRepository
from nespresso.db.repositories.nes_user import NesUserRepository
from nespresso.db.repositories.profile_reaction import ProfileReactionRepository
from nespresso.db.repositories.tg_user import TgUserRepository
from nespresso.db.services.matching import MatchingService
from nespresso.db.services.message import MessageService
from nespresso.db.services.profile_reaction import ProfileReactionService
from nespresso.db.services.user import UserService
from nespresso.db.session import AsyncSessionLocal


class UserContextService(
    UserService, MessageService, MatchingService, ProfileReactionService
):
    """
    Combines UserService, MessageService, MatchingService, and
    ProfileReactionService into a single context service.
    """

    def __init__(
        self,
        user_service: UserService,
        message_service: MessageService,
        matching_service: MatchingService,
        profile_reaction_service: ProfileReactionService,
    ):
        UserService.__init__(
            self,
            tg_user_repo=user_service.tg_user_repo,
            nes_user_repo=user_service.nes_user_repo,
        )
        MessageService.__init__(self, message_service.message_repo)
        MatchingService.__init__(self, matching_service.match_repo)
        ProfileReactionService.__init__(
            self, profile_reaction_service.profile_reaction_repo
        )

    async def DeleteAccountData(self, chat_id: int, nes_id: int | None) -> None:
        """
        Erase all DB rows for a self-service account deletion (GDPR): the user's
        profile reactions (both directions, via nes_id) plus their TgUser row,
        message audit log, and match assignments/feedback. The caller separately
        drops the OpenSearch document. Deletes are idempotent, so a retry after a
        partial failure completes cleanly.
        """
        await self.DeleteProfileReactionsForUser(chat_id, nes_id)
        await self.DeleteUserAndActivity(chat_id)


async def GetUserContextService() -> UserContextService:
    tg_user_repo = TgUserRepository(AsyncSessionLocal)
    nes_user_repo = NesUserRepository(AsyncSessionLocal)
    message_repo = MessageRepository(AsyncSessionLocal)
    match_repo = MatchRepository(AsyncSessionLocal)
    profile_reaction_repo = ProfileReactionRepository(AsyncSessionLocal)

    user_service = UserService(tg_user_repo=tg_user_repo, nes_user_repo=nes_user_repo)
    message_service = MessageService(message_repo)
    matching_service = MatchingService(match_repo)
    profile_reaction_service = ProfileReactionService(profile_reaction_repo)

    return UserContextService(
        user_service, message_service, matching_service, profile_reaction_service
    )
