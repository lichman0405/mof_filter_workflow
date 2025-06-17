# mcp_service/app/db/session.py
# The module is responsible for managing the database session and initializing the database.
# Author: Shibo Li
# Date: 2026-06-16
# Version: 0.1.0

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlmodel import SQLModel
from typing import AsyncGenerator
from app.core.settings import settings

# The engine is created just as before.
engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)

# The session maker is simplified. The class 'AsyncSession' is inferred.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)

async def init_db():
    """
    Initialize the database and create tables if they don't exist.
    This should be called once on application startup.
    """
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session to an endpoint.
    It ensures the session is always closed after the request is finished.
    """
    async with AsyncSessionLocal() as session:
        yield session

