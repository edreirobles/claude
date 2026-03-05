from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def _get_async_url(url: str) -> str:
    """
    Railway provee DATABASE_URL como postgresql://...
    SQLAlchemy async necesita postgresql+asyncpg://...
    También soporta sqlite+aiosqlite:// para desarrollo local.
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        # Heroku / Railway a veces usa postgres:// en vez de postgresql://
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url  # sqlite+aiosqlite:// ya está bien


_db_url = _get_async_url(settings.database_url)

engine = create_async_engine(
    _db_url,
    echo=False,
    # Pool settings para PostgreSQL en producción
    pool_pre_ping=True,
    pool_recycle=300,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
