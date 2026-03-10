from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nespresso.core.configs.settings import settings
from nespresso.db.base import Base

engine = create_async_engine(
    settings.POSTGRES_DSN.get_secret_value(),
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def EnsureDB() -> None:
    """
    Create all SQLAlchemy-mapped tables in the database if they don't already exist.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("ALTER TABLE tg_user ADD COLUMN IF NOT EXISTS language VARCHAR")
        )
