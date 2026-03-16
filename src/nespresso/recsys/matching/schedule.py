from nespresso.recsys.matching.assign import MatchingPipeline


async def RunMatching(triggered_by: int) -> int:
    """
    Manually trigger a matching round.
    Returns the number of users who received at least one match.
    """
    return await MatchingPipeline(triggered_by=triggered_by)
