from typing import Literal

from db.models.files import Purpose
from pydantic import BaseModel


class FileObject(BaseModel):
    """
    Ref: https://developers.openai.com/api/reference/resources/files#(resource)%20files%20%3E%20(model)%20file_object%20%3E%20(schema)
    """

    id: str
    bytes: int
    created_at: int
    filename: str
    object: Literal["file"]
    purpose: Purpose
