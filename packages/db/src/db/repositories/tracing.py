from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Participant,
    StepKind,
    StepStatus,
    TracedRequest,
    TraceOutcome,
    WorkflowStep,
)
from db.repositories.analytics import UnknownCursorError


@dataclass(frozen=True)
class NewStep:
    position: int
    kind: StepKind
    source: Participant
    destination: Participant
    status: StepStatus
    started_at: datetime
    duration_ms: int | None = None
    content: Any | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class RequestFilters:
    endpoint: str | None = None
    outcomes: Sequence[TraceOutcome] | None = None
    since: datetime | None = None
    until: datetime | None = None


async def create_request(
    session: AsyncSession, *, endpoint: str, method: str, started_at: datetime
) -> TracedRequest:
    request = TracedRequest(
        endpoint=endpoint,
        method=method,
        started_at=started_at,
        outcome=TraceOutcome.IN_PROGRESS,
    )
    session.add(request)
    await session.commit()
    return request


async def add_steps(
    session: AsyncSession, request_id: int, steps: Sequence[NewStep]
) -> list[int]:
    rows = [
        WorkflowStep(
            request_id=request_id,
            position=step.position,
            kind=step.kind,
            source=step.source,
            destination=step.destination,
            status=step.status,
            started_at=step.started_at,
            duration_ms=step.duration_ms,
            content=step.content,
            error_message=step.error_message,
        )
        for step in steps
    ]
    session.add_all(rows)
    await session.commit()
    return [row.id for row in rows]


async def finish_step(
    session: AsyncSession,
    step_id: int,
    *,
    status: StepStatus,
    duration_ms: int | None,
    content: Any | None,
    error_message: str | None,
) -> None:
    await session.execute(
        update(WorkflowStep)
        .where(WorkflowStep.id == step_id)
        .values(
            status=status,
            duration_ms=duration_ms,
            content=content,
            error_message=error_message,
        )
    )
    await session.commit()


async def update_request(
    session: AsyncSession,
    request_id: int,
    *,
    summary: str | None = None,
    response_id: str | None = None,
) -> None:
    values: dict[str, str] = {}
    if summary is not None:
        values["summary"] = summary
    if response_id is not None:
        values["response_id"] = response_id
    if not values:
        return
    await session.execute(
        update(TracedRequest).where(TracedRequest.id == request_id).values(**values)
    )
    await session.commit()


async def finish_request(
    session: AsyncSession,
    request_id: int,
    *,
    outcome: TraceOutcome,
    duration_ms: int,
    http_status: int | None,
    summary: str | None,
    response_id: str | None,
    error_message: str | None,
) -> None:
    await session.execute(
        update(TracedRequest)
        .where(TracedRequest.id == request_id)
        .values(
            outcome=outcome,
            duration_ms=duration_ms,
            http_status=http_status,
            summary=summary,
            response_id=response_id,
            error_message=error_message,
        )
    )
    await session.commit()


async def list_requests(
    session: AsyncSession,
    filters: RequestFilters,
    *,
    limit: int,
    after: int | None,
) -> tuple[list[TracedRequest], bool]:
    statement = select(TracedRequest)
    if filters.endpoint is not None:
        statement = statement.where(TracedRequest.endpoint == filters.endpoint)
    if filters.outcomes:
        statement = statement.where(TracedRequest.outcome.in_(filters.outcomes))
    if filters.since is not None:
        statement = statement.where(TracedRequest.started_at >= filters.since)
    if filters.until is not None:
        statement = statement.where(TracedRequest.started_at < filters.until)
    if after is not None:
        exists = await session.execute(
            select(TracedRequest.id).where(TracedRequest.id == after)
        )
        if exists.first() is None:
            raise UnknownCursorError(str(after))
        statement = statement.where(TracedRequest.id < after)
    statement = statement.order_by(TracedRequest.id.desc()).limit(limit + 1)
    rows = list((await session.execute(statement)).scalars())
    return rows[:limit], len(rows) > limit


async def get_request_with_steps(
    session: AsyncSession, request_id: int
) -> tuple[TracedRequest, list[WorkflowStep]] | None:
    request = await session.get(TracedRequest, request_id)
    if request is None:
        return None
    steps = (
        await session.execute(
            select(WorkflowStep)
            .where(WorkflowStep.request_id == request_id)
            .order_by(WorkflowStep.position)
        )
    ).scalars()
    return request, list(steps)


async def mark_in_progress_interrupted(session: AsyncSession) -> None:
    await session.execute(
        update(TracedRequest)
        .where(TracedRequest.outcome == TraceOutcome.IN_PROGRESS)
        .values(outcome=TraceOutcome.INTERRUPTED)
    )
    await session.execute(
        update(WorkflowStep)
        .where(WorkflowStep.status == StepStatus.IN_PROGRESS)
        .values(status=StepStatus.INTERRUPTED)
    )
    await session.commit()
