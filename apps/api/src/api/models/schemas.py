from typing import Literal

from db.models import Model as ModelRecord
from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    created: int
    object: Literal["model"]
    owned_by: str

    @classmethod
    def from_record(cls, record: ModelRecord) -> Model:
        return cls(
            id=record.external_id,
            created=int(record.created_at.timestamp()),
            object="model",
            owned_by=record.owned_by,
        )


class ListModelsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    object: Literal["list"]
    data: list[Model]
