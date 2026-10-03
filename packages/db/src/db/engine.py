from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from db.config import get_settings


@lru_cache
def get_async_engine() -> AsyncEngine:
    return create_async_engine(get_settings().async_url)


@lru_cache
def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_async_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_async_session_factory()() as session:
        yield session


@lru_cache
def get_sync_engine() -> Engine:
    return create_engine(get_settings().sync_url)


@lru_cache
def get_sync_session_factory() -> sessionmaker[Session]:
    return sessionmaker(get_sync_engine(), expire_on_commit=False)


def clear_caches() -> None:
    for cached in (
        get_settings,
        get_async_engine,
        get_async_session_factory,
        get_sync_engine,
        get_sync_session_factory,
    ):
        cached.cache_clear()
