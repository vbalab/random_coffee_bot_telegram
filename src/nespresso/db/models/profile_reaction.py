from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nespresso.db.base import Base


class ReactionKind(str, Enum):
    """
    A searcher's search-QUALITY vote on one result profile. Recorded for future
    analytics ONLY — it does NOT influence retrieval, ranking, or the search
    pipeline. `null` (no row value) means "no vote".
    """

    Like = "like"  # this result was a good match for my query
    Dislike = "dislike"  # this result was a bad match for my query


class ProfileReaction(Base):
    """
    One row per (rater, target) profile the searcher interacted with in Find.

    This is DIFFERENT from the admin user-block (`TgUser.blocked` /
    `bot/lib/chat/block.py`), which bars a whole TgUser from the bot. Here a
    normal user privately HIDES an individual alumni profile from their OWN Find
    results and matching rounds. `reaction` (like/dislike) and `blocked` are
    independent columns on one row so a user can rate and hide separately and
    unhide cleanly.
    """

    __tablename__ = "profile_reaction"

    __table_args__ = (
        UniqueConstraint(
            "rater_chat_id",
            "target_nes_id",
            name="uq_profile_reaction_rater_target",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # The reacting user's Telegram chat_id.
    rater_chat_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    # The reacted-to alumni profile's nes_id.
    target_nes_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)

    # "like" / "dislike" / NULL (no vote). Analytics-only signal.
    reaction: Mapped[str | None] = mapped_column(String, nullable=True)
    # True ⇒ this profile is hidden from the rater's Find results + matching.
    blocked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
