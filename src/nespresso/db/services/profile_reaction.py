from nespresso.db.repositories.profile_reaction import ProfileReactionRepository


class ProfileReactionService:
    """Business-facing wrapper over ProfileReactionRepository (per-user profile
    like/dislike + hidden profiles)."""

    def __init__(self, profile_reaction_repo: ProfileReactionRepository):
        self.profile_reaction_repo = profile_reaction_repo

        # --- Write ---
        self.SetProfileReaction = self.profile_reaction_repo.SetReaction
        self.SetProfileBlocked = self.profile_reaction_repo.SetBlocked

        # --- Read ---
        self.GetProfileReaction = self.profile_reaction_repo.GetReaction
        self.GetBlockedTargetNesIds = self.profile_reaction_repo.GetBlockedNesIds
        self.GetBlockedChatIdPairs = self.profile_reaction_repo.GetBlockedChatIdPairs
        self.GetProfileReactionsForUser = self.profile_reaction_repo.GetReactionsForUser

        # --- Delete ---
        self.DeleteProfileReactionsForUser = self.profile_reaction_repo.DeleteForUser
