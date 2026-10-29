from functools import cache

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import get_settings


@cache
def get_engine() -> AsyncEngine:
    # Supabase via session pooler (porta 5432): o transaction pooler quebra prepared statements.
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@cache
def get_sessionmaker() -> async_sessionmaker:
    return async_sessionmaker(get_engine(), expire_on_commit=False)
