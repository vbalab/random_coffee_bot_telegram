from nespresso.db.repositories.analytics import AnalyticsRepository
from nespresso.db.session import AsyncSessionLocal


class AnalyticsService:
    def __init__(self, repo: AnalyticsRepository):
        self.GetTgUserStats = repo.GetTgUserStats
        self.GetNesUserStats = repo.GetNesUserStats
        self.GetActivityStats = repo.GetActivityStats
        self.GetAllTgUsers = repo.GetAllTgUsers
        self.GetAllNesUsers = repo.GetAllNesUsers
        self.GetAllMessages = repo.GetAllMessages
        self.GetMatchingStats = repo.GetMatchingStats
        self.GetFeedbackStats = repo.GetFeedbackStats


async def GetAnalyticsService() -> AnalyticsService:
    repo = AnalyticsRepository(AsyncSessionLocal)
    return AnalyticsService(repo)
