from collections.abc import AsyncIterator
from functools import lru_cache
from sqlite3 import Connection

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from db.config import get_settings


def _enable_foreign_keys(engine: Engine) -> Engine:
    # SQLite ignores foreign keys unless enabled on every new connection
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Connection, _: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


@lru_cache
def get_async_engine() -> AsyncEngine:
    engine = create_async_engine(get_settings().async_url)
    _enable_foreign_keys(engine.sync_engine)
    return engine


@lru_cache
def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_async_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_async_session_factory()() as session:
        yield session


@lru_cache
def get_sync_engine() -> Engine:
    return _enable_foreign_keys(create_engine(get_settings().sync_url))


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
