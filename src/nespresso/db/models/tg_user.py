from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from nespresso.db.base import Base


class TgUser(Base):
    __tablename__ = "tg_user"

    __table_args__ = (
        # A verified alumnus should map to exactly one account. Partial (only
        # WHERE verified) so an unverified/never-completed row never blocks a
        # different chat_id from later claiming the same nes_id.
        Index(
            "ix_tg_user_nes_id_verified_uniq",
            "nes_id",
            unique=True,
            postgresql_where=text("verified = true"),
        ),
    )

    # --- primary key ---

    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )

    # --- secondary keys ---

    nes_id: Mapped[int | None] = mapped_column(
        BigInteger,
        index=True,
        nullable=True,
    )
    nes_email: Mapped[str | None] = mapped_column(
        String,
        index=True,
        nullable=True,
    )
    username: Mapped[str | None] = mapped_column(
        String,
        index=True,
        nullable=True,
    )
    language: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    # --- description ---

    about: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    # --- hub panel ---

    panel_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    # --- state ---

    verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    blocked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    matching_paused: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # --- time ---

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
