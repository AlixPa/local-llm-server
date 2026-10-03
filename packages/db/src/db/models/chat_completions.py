from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, Index, desc
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base
from db.types import UtcDateTime


class ChatCompletionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ChatCompletionRecord(Base):
    __tablename__ = "chat_completion_records"
    __table_args__ = (
        Index(
            "ix_chat_completion_records_created_at_id", desc("created_at"), desc("id")
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    model: Mapped[str]
    status: Mapped[ChatCompletionStatus] = mapped_column(
        Enum(
            ChatCompletionStatus,
            native_enum=False,
            create_constraint=False,
            length=16,
            values_callable=lambda e: [member.value for member in e],
        )
    )
    stream: Mapped[bool]
    n: Mapped[int]
    prompt_tokens: Mapped[int | None]
    completion_tokens: Mapped[int | None]
    duration_ms: Mapped[int]
    time_to_first_token_ms: Mapped[int | None]
    generation_duration_ms: Mapped[int | None]
    load_duration_ms: Mapped[int | None]
    finish_reason: Mapped[str | None]
    error_type: Mapped[str | None]
    error_code: Mapped[str | None]


class ChatCompletionContent(Base):
    __tablename__ = "chat_completion_contents"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("chat_completion_records.id", ondelete="CASCADE"), unique=True
    )
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    error_message: Mapped[str | None]
