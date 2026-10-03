from typing import Annotated

from db.engine import get_session
from db.repositories import models as models_repo
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.schemas import ListModelsResponse, Model

router = APIRouter()


@router.get("/models")
async def list_models(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ListModelsResponse:
    records = await models_repo.list_models(session)
    return ListModelsResponse(
        object="list", data=[Model.from_record(record) for record in records]
    )
