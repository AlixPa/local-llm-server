from datetime import datetime, timedelta
from typing import Any, Literal

from db.models import (
    Participant,
    StepKind,
    StepStatus,
    TracedRequest,
    TraceOutcome,
    WorkflowStep,
)
from pydantic import BaseModel, ConfigDict


class TracedRequestItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    endpoint: str
    method: str
    started_at: int
    started_at_ms: int
    duration_ms: int | None
    http_status: int | None
    outcome: TraceOutcome
    summary: str | None
    response_id: str | None
    error_message: str | None

    @classmethod
    def from_record(cls, record: TracedRequest) -> TracedRequestItem:
        return cls(
            id=record.id,
            endpoint=record.endpoint,
            method=record.method,
            started_at=int(record.started_at.timestamp()),
            started_at_ms=_epoch_ms(record.started_at),
            duration_ms=record.duration_ms,
            http_status=record.http_status,
            outcome=record.outcome,
            summary=record.summary,
            response_id=record.response_id,
            error_message=record.error_message,
        )


class TracedRequestList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    object: Literal["list"]
    data: list[TracedRequestItem]
    first_id: int | None
    last_id: int | None
    has_more: bool


class WorkflowStepItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    position: int
    kind: StepKind
    source: Participant
    destination: Participant
    status: StepStatus
    offset_ms: int
    duration_ms: int | None
    content: Any
    error_message: str | None

    @classmethod
    def from_record(
        cls, step: WorkflowStep, request: TracedRequest
    ) -> WorkflowStepItem:
        return cls(
            position=step.position,
            kind=step.kind,
            source=step.source,
            destination=step.destination,
            status=step.status,
            offset_ms=_epoch_ms(step.started_at) - _epoch_ms(request.started_at),
            duration_ms=step.duration_ms,
            content=step.content,
            error_message=step.error_message,
        )


class TracedRequestDetail(TracedRequestItem):
    steps: list[WorkflowStepItem]

    @classmethod
    def from_records(
        cls, request: TracedRequest, steps: list[WorkflowStep]
    ) -> TracedRequestDetail:
        return cls(
            **TracedRequestItem.from_record(request).model_dump(),
            steps=[WorkflowStepItem.from_record(step, request) for step in steps],
        )


class RequestEvent(BaseModel):
    type: Literal["request.created", "request.updated"]
    id: int

    def data_json(self) -> str:
        return self.model_dump_json(include={"id"})


def _epoch_ms(value: datetime) -> int:
    return (value - datetime.fromtimestamp(0, value.tzinfo)) // timedelta(
        milliseconds=1
    )
