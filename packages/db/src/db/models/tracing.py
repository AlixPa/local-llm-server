from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base
from db.types import UtcDateTime


class TraceOutcome(StrEnum):
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    ERROR = "error"
    CANCELED = "canceled"
    INTERRUPTED = "interrupted"


class StepKind(StrEnum):
    REQUEST_RECEIVED = "request_received"
    SENT_TO_OLLAMA = "sent_to_ollama"
    RECEIVED_FROM_OLLAMA = "received_from_ollama"
    RESPONSE_RETURNED = "response_returned"
    ERROR = "error"


class StepStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    INTERRUPTED = "interrupted"


class Participant(StrEnum):
    CLIENT = "client"
    API = "api"
    OLLAMA = "ollama"


def _string_enum[E: StrEnum](enum: type[E]) -> Enum:
    return Enum(
        enum,
        native_enum=False,
        create_constraint=False,
        length=24,
        values_callable=lambda e: [member.value for member in e],
    )


class TracedRequest(Base):
    __tablename__ = "traced_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str]
    method: Mapped[str]
    started_at: Mapped[datetime] = mapped_column(UtcDateTime)
    duration_ms: Mapped[int | None]
    http_status: Mapped[int | None]
    outcome: Mapped[TraceOutcome] = mapped_column(_string_enum(TraceOutcome))
    summary: Mapped[str | None]
    # Value link to chat_completion_records.external_id or
    # response_records.external_id; no FK because the usage
    # record is inserted after the trace row exists (and not at all on rejection)
    response_id: Mapped[str | None]
    error_message: Mapped[str | None]


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (UniqueConstraint("request_id", "position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("traced_requests.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    kind: Mapped[StepKind] = mapped_column(_string_enum(StepKind))
    source: Mapped[Participant] = mapped_column(_string_enum(Participant))
    destination: Mapped[Participant] = mapped_column(_string_enum(Participant))
    status: Mapped[StepStatus] = mapped_column(_string_enum(StepStatus))
    started_at: Mapped[datetime] = mapped_column(UtcDateTime)
    duration_ms: Mapped[int | None]
    content: Mapped[Any] = mapped_column(JSON(none_as_null=True), nullable=True)
    error_message: Mapped[str | None]
