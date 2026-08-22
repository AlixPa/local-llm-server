import uuid
from datetime import datetime

from sqlalchemy import UUID, DateTime, Integer, func, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class BatchInputFileChunk(Base):
    __tablename__ = "batch_input_file_chunks"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    batch_input_file_chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
        init=False,
    )

    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)

    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, init=False
    )
