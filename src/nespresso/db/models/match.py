from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from nespresso.db.base import Base


class MatchRound(Base):
    __tablename__ = "match_round"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    triggered_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    # Set the first time "Send Feedback Request" successfully runs for this
    # round, so a repeat tap can be refused instead of re-spamming every
    # matched user with a fresh set of feedback buttons.
    feedback_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class MatchAssignment(Base):
    __tablename__ = "match_assignment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("match_round.id", ondelete="CASCADE"), nullable=False
    )
    assigner_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    assigned_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class FeedbackResponse(str, Enum):
    Met = "met"
    NotMet = "not_met"
    Planning = "planning"


class MatchFeedback(Base):
    __tablename__ = "match_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("match_assignment.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    response: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
