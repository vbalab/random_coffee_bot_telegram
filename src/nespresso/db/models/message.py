from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SqlEnum,
    String,
    text as Text,  # noqa: N812
)
from sqlalchemy.orm import Mapped, mapped_column

from nespresso.db.base import Base


class MessageSide(Enum):
    Bot = "bot"
    User = "user"


class Message(Base):
    __tablename__ = "message"

    # Telegram message_id is unique only within a chat; need composite PK
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    side: Mapped[MessageSide] = mapped_column(SqlEnum(MessageSide), nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=Text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
