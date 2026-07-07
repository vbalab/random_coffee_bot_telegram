from nespresso.db.models.tg_user import TgUser
from nespresso.db.repositories.nes_user import NesUserRepository
from nespresso.db.repositories.tg_user import TgUserRepository


class UserService:
    def __init__(
        self, tg_user_repo: TgUserRepository, nes_user_repo: NesUserRepository
    ):
        self.tg_user_repo = tg_user_repo
        self.nes_user_repo = nes_user_repo

        # --- Create ---
        # - Tg -
        self.RegisterTgUser = self.tg_user_repo.CreateTgUser

        # - Nes -
        self.UpsertNesUser = self.nes_user_repo.UpsertNesUsers
        self.SyncUpsertNesUsers = self.nes_user_repo.SyncUpsertNesUsers
        self.DelistMissingNesUsers = self.nes_user_repo.DelistMissingNesUsers

        # --- Read ---
        # - Tg -
        self.GetTgUsersOnCondition = self.tg_user_repo.GetTgUsersOnCondition
        self.GetTgUser = self.tg_user_repo.GetTgUser
        self.GetTgChatIdBy = self.tg_user_repo.GetChatIdBy
        self.GetAboutByNesIds = self.tg_user_repo.GetAboutByNesIds

        # - Nes -
        self.GetNesUsersOnCondition = self.nes_user_repo.GetNesUsersOnCondition
        self.GetNesUser = self.nes_user_repo.GetNesUser
        self.GetNesUserByEmail = self.nes_user_repo.GetNesUserByEmail
        self.GetNesUserHashes = self.nes_user_repo.GetNesUserHashes

        # --- Update ---
        # - Tg -
        self.UpdateTgUser = self.tg_user_repo.UpdateTgUser

        # --- Delete ---

    # --- Create ---

    # --- Read ---
    # - Tg -
    async def CheckTgUserExists(self, chat_id: int) -> bool:
        result = await self.GetTgUser(
            chat_id=chat_id,
            column=TgUser.chat_id,
        )

        return result is not None

    async def GetVerifiedTgUsersChatId(self) -> list[int]:
        result = await self.GetTgUsersOnCondition(
            condition=TgUser.verified,
            column=TgUser.chat_id,
        )

        return result

    async def GetAdminChatIds(self) -> list[int]:
        result = await self.GetTgUsersOnCondition(
            condition=TgUser.is_admin,
            column=TgUser.chat_id,
        )

        return result

    # --- Update ---

    # --- Delete ---
