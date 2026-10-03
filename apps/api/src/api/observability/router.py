import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated

import anyio
from db.engine import get_session
from db.models import TraceOutcome
from db.repositories import tracing as repo
from db.repositories.chat_completions import UnknownCursorError
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette import EventSourceResponse, ServerSentEvent

from api.errors import ApiError
from api.observability.schemas import (
    RequestEvent,
    TracedRequestItem,
    TracedRequestList,
)
from api.observability.tracing import hub

KEEP_ALIVE_SECONDS = 15


def _keep_alive() -> ServerSentEvent:
    return ServerSentEvent(comment="keep-alive")


router = APIRouter(prefix="/observability")


def _utc(seconds: int | None) -> datetime | None:
    return None if seconds is None else datetime.fromtimestamp(seconds, UTC)


@router.get("/requests")
async def list_requests(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    after: int | None = None,
    endpoint: str | None = None,
    outcome: Annotated[list[TraceOutcome] | None, Query()] = None,
    since: int | None = None,
    until: int | None = None,
) -> TracedRequestList:
    filters = repo.RequestFilters(
        endpoint=endpoint, outcomes=outcome, since=_utc(since), until=_utc(until)
    )
    try:
        records, has_more = await repo.list_requests(
            session, filters, limit=limit, after=after
        )
    except UnknownCursorError:
        raise ApiError(
            404, "invalid_request_error", "not_found", "after", f"No such id: {after}"
        ) from None
    items = [TracedRequestItem.from_record(record) for record in records]
    return TracedRequestList(
        object="list",
        data=items,
        first_id=items[0].id if items else None,
        last_id=items[-1].id if items else None,
        has_more=has_more,
    )


async def _event_stream(shutdown: anyio.Event) -> AsyncGenerator[ServerSentEvent]:
    # Lets the client see the connection open before any event exists
    yield ServerSentEvent(comment="keep-alive")
    events = hub.subscribe()
    stop = asyncio.ensure_future(shutdown.wait())
    pending = asyncio.ensure_future(anext(events, None))
    try:
        while True:
            await asyncio.wait({stop, pending}, return_when=asyncio.FIRST_COMPLETED)
            if stop.done() or (event := pending.result()) is None:
                return
            payload = RequestEvent(type=event.type, id=event.id)
            yield ServerSentEvent(event=payload.type, data=payload.data_json())
            pending = asyncio.ensure_future(anext(events, None))
    finally:
        stop.cancel()
        pending.cancel()
        await asyncio.gather(stop, pending, return_exceptions=True)
        await events.aclose()


@router.get("/events")
async def stream_events() -> EventSourceResponse:
    # Ending the generator on uvicorn's shutdown signal completes the response,
    # so open streams don't block the lifespan shutdown that drains the writer
    shutdown = anyio.Event()
    return EventSourceResponse(
        _event_stream(shutdown),
        ping=KEEP_ALIVE_SECONDS,
        ping_message_factory=_keep_alive,
        shutdown_event=shutdown,
        shutdown_grace_period=1,
    )
