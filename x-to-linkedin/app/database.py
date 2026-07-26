from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from .config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migraciones para columnas agregadas en versiones posteriores
        for stmt in [
            "ALTER TABLE scheduled_posts ADD COLUMN source VARCHAR(20) DEFAULT 'manual'",
            "ALTER TABLE scheduled_posts ADD COLUMN generated_image_path TEXT",
            "ALTER TABLE scheduled_posts ADD COLUMN manual_edited_at DATETIME",
            "ALTER TABLE scheduled_posts ADD COLUMN manual_edited_via VARCHAR(30)",
            "ALTER TABLE scheduled_posts ADD COLUMN editorial_revision_notes TEXT",
            "ALTER TABLE scheduled_posts ADD COLUMN li_clicks INTEGER",
            "ALTER TABLE scheduled_posts ADD COLUMN li_shares INTEGER",
            "ALTER TABLE linkedin_tokens ADD COLUMN refresh_token TEXT",
            "ALTER TABLE linkedin_tokens ADD COLUMN refresh_token_expires_at DATETIME",
        ]:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass  # La columna ya existe
