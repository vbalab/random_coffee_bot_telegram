from nespresso.db.repositories.match import MatchRepository


class MatchingService:
    def __init__(self, match_repo: MatchRepository):
        self.match_repo = match_repo

        self.CreateRoundWithAssignments = self.match_repo.CreateRoundWithAssignments
        self.GetLastRound = self.match_repo.GetLastRound
        self.MarkFeedbackSent = self.match_repo.MarkFeedbackSent
        self.GetAssignmentsByRound = self.match_repo.GetAssignmentsByRound
        self.GetAssignment = self.match_repo.GetAssignment
        self.GetRecentExcludedPairs = self.match_repo.GetRecentExcludedPairs
        self.UpsertFeedback = self.match_repo.UpsertFeedback
