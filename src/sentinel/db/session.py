"""Async engine and session factory, created once per process."""

from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sentinel.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(str(get_settings().database_url), pool_size=5, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)
