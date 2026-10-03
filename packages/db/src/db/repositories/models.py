from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Model


async def list_models(session: AsyncSession) -> Sequence[Model]:
    result = await session.execute(select(Model).order_by(Model.id))
    return result.scalars().all()


async def get_model(session: AsyncSession, external_id: str) -> Model | None:
    result = await session.execute(
        select(Model).where(Model.external_id == external_id)
    )
    return result.scalar_one_or_none()
