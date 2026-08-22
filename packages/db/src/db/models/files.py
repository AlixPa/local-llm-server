import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import UUID, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Purpose(StrEnum):
    """
    Ref: https://developers.openai.com/api/reference/resources/files#(resource)%20files%20%3E%20(model)%20file_object%20%3E%20(schema)%20%3E%20(property)%20purpose
    Note that for now we only support batches files.
    The values are lowercase to respect openai contract.
    """

    BATCH = "batch"


class Format(StrEnum):
    JSONL = "JSONL"


class File(Base):
    __tablename__ = "files"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, init=False
    )

    original_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    format: Mapped[Format] = mapped_column(String, nullable=False)
    purpose: Mapped[Purpose] = mapped_column(String, nullable=False)
