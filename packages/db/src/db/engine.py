from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.config import POSTGRES_ASYNC_URL

engine = create_async_engine(
    POSTGRES_ASYNC_URL,
    pool_pre_ping=True,
)


session_factory = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


# Usage Fastapi (in router arguments) -> handles the lifetime of session
# session: Annotated[AsyncSession, Depends(get_session)]

# Usage in service -> session is autobegin so transaction is automatically opened/closed when needed
# session.add(obj1)
# session.rollback()
# session.add(obj2)
# session.commit()
