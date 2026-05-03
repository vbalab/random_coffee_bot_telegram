"""Importing all models here ensures they register with Base.metadata."""

from nespresso.db.models.match import (
    FeedbackResponse,
    MatchAssignment,
    MatchFeedback,
    MatchRound,
)
from nespresso.db.models.message import Message, MessageSide
from nespresso.db.models.nes_user import NesUser
from nespresso.db.models.tg_user import TgUser

__all__ = [
    "FeedbackResponse",
    "MatchAssignment",
    "MatchFeedback",
    "MatchRound",
    "Message",
    "MessageSide",
    "NesUser",
    "TgUser",
]
