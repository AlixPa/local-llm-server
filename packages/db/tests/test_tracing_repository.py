from datetime import UTC, datetime, timedelta

import pytest
from db.models import (
    Participant,
    StepKind,
    StepStatus,
    TracedRequest,
    TraceOutcome,
    WorkflowStep,
)
from db.repositories.analytics import UnknownCursorError
from db.repositories.tracing import (
    NewStep,
    RequestFilters,
    add_steps,
    create_request,
    finish_request,
    finish_step,
    get_request_with_steps,
    list_requests,
    mark_in_progress_interrupted,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)


async def _request(
    session: AsyncSession,
    *,
    endpoint: str = "/v1/chat/completions",
    started_at: datetime = T0,
) -> TracedRequest:
    return await create_request(
        session, endpoint=endpoint, method="POST", started_at=started_at
    )


def _step(position: int, status: StepStatus = StepStatus.COMPLETED) -> NewStep:
    return NewStep(
        position=position,
        kind=StepKind.REQUEST_RECEIVED,
        source=Participant.CLIENT,
        destination=Participant.API,
        status=status,
        started_at=T0,
    )


async def test_create_and_finish_request(session: AsyncSession) -> None:
    request = await _request(session)
    assert request.outcome is TraceOutcome.IN_PROGRESS
    assert request.duration_ms is None

    await finish_request(
        session,
        request.id,
        outcome=TraceOutcome.SUCCESS,
        duration_ms=42,
        http_status=200,
        summary="m · stream",
        response_id="chatcmpl-1",
        error_message=None,
    )
    session.expire_all()

    stored = (await session.execute(select(TracedRequest))).scalar_one()
    assert stored.started_at == T0
    assert stored.outcome is TraceOutcome.SUCCESS
    assert (stored.duration_ms, stored.http_status) == (42, 200)
    assert (stored.summary, stored.response_id) == ("m · stream", "chatcmpl-1")


async def test_add_steps_returns_ids_and_finish_step(session: AsyncSession) -> None:
    request = await _request(session)
    ids = await add_steps(
        session, request.id, [_step(0), _step(1, StepStatus.IN_PROGRESS)]
    )
    assert len(ids) == 2

    await finish_step(
        session,
        ids[1],
        status=StepStatus.FAILED,
        duration_ms=7,
        content={"a": 1},
        error_message="boom",
    )
    session.expire_all()

    open_step = await session.get(WorkflowStep, ids[1])
    assert open_step is not None
    assert open_step.status is StepStatus.FAILED
    assert (open_step.duration_ms, open_step.content) == (7, {"a": 1})
    assert open_step.error_message == "boom"
    first = await session.get(WorkflowStep, ids[0])
    assert first is not None
    assert first.content is None


async def test_list_orders_newest_first_with_cursor(session: AsyncSession) -> None:
    ids = [(await _request(session)).id for _ in range(5)]

    rows, has_more = await list_requests(session, RequestFilters(), limit=2, after=None)
    assert [row.id for row in rows] == [ids[4], ids[3]]
    assert has_more is True

    rows, has_more = await list_requests(
        session, RequestFilters(), limit=2, after=ids[3]
    )
    assert [row.id for row in rows] == [ids[2], ids[1]]
    assert has_more is True

    rows, has_more = await list_requests(
        session, RequestFilters(), limit=2, after=ids[1]
    )
    assert [row.id for row in rows] == [ids[0]]
    assert has_more is False


async def test_list_unknown_cursor(session: AsyncSession) -> None:
    with pytest.raises(UnknownCursorError):
        await list_requests(session, RequestFilters(), limit=5, after=999)


async def test_list_filters(session: AsyncSession) -> None:
    chat = await _request(session)
    other = await _request(session, endpoint="/v1/other", started_at=T0 + timedelta(1))
    late = await _request(session, started_at=T0 + timedelta(2))
    await finish_request(
        session,
        late.id,
        outcome=TraceOutcome.ERROR,
        duration_ms=1,
        http_status=400,
        summary=None,
        response_id=None,
        error_message="bad",
    )

    async def ids(filters: RequestFilters) -> set[int]:
        rows, _ = await list_requests(session, filters, limit=10, after=None)
        return {row.id for row in rows}

    assert await ids(RequestFilters(endpoint="/v1/other")) == {other.id}
    assert await ids(RequestFilters(outcomes=[TraceOutcome.ERROR])) == {late.id}
    assert await ids(
        RequestFilters(outcomes=[TraceOutcome.ERROR, TraceOutcome.IN_PROGRESS])
    ) == {chat.id, other.id, late.id}
    # since is inclusive, until is exclusive
    assert await ids(RequestFilters(since=T0 + timedelta(1))) == {other.id, late.id}
    assert await ids(RequestFilters(until=T0 + timedelta(1))) == {chat.id}


async def test_detail_orders_steps_by_position(session: AsyncSession) -> None:
    request = await _request(session)
    await add_steps(session, request.id, [_step(2), _step(0), _step(1)])

    detail = await get_request_with_steps(session, request.id)

    assert detail is not None
    found, steps = detail
    assert found.id == request.id
    assert [step.position for step in steps] == [0, 1, 2]
    assert await get_request_with_steps(session, 999) is None


async def test_mark_in_progress_interrupted_touches_only_in_progress(
    session: AsyncSession,
) -> None:
    running_id = (await _request(session)).id
    done_id = (await _request(session)).id
    await finish_request(
        session,
        done_id,
        outcome=TraceOutcome.SUCCESS,
        duration_ms=1,
        http_status=200,
        summary=None,
        response_id=None,
        error_message=None,
    )
    step_ids = await add_steps(
        session, running_id, [_step(0), _step(1, StepStatus.IN_PROGRESS)]
    )

    await mark_in_progress_interrupted(session)
    session.expire_all()

    outcomes = (
        await session.execute(select(TracedRequest.id, TracedRequest.outcome))
    ).all()
    assert {row.id: row.outcome for row in outcomes} == {
        running_id: TraceOutcome.INTERRUPTED,
        done_id: TraceOutcome.SUCCESS,
    }
    statuses = (
        await session.execute(
            select(WorkflowStep.id, WorkflowStep.status).where(
                WorkflowStep.id.in_(step_ids)
            )
        )
    ).all()
    assert {row.id: row.status for row in statuses} == {
        step_ids[0]: StepStatus.COMPLETED,
        step_ids[1]: StepStatus.INTERRUPTED,
    }


async def test_position_unique_per_request(session: AsyncSession) -> None:
    request = await _request(session)
    await add_steps(session, request.id, [_step(0)])

    with pytest.raises(IntegrityError):
        await add_steps(session, request.id, [_step(0)])
