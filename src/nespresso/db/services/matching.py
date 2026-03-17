from nespresso.db.repositories.match import MatchRepository


class MatchingService:
    def __init__(self, match_repo: MatchRepository):
        self.match_repo = match_repo

        self.CreateRound = self.match_repo.CreateRound
        self.GetLastRound = self.match_repo.GetLastRound
        self.CreateAssignments = self.match_repo.CreateAssignments
        self.GetAssignmentsByRound = self.match_repo.GetAssignmentsByRound
        self.GetRecentExcludedPairs = self.match_repo.GetRecentExcludedPairs
        self.UpsertFeedback = self.match_repo.UpsertFeedback
