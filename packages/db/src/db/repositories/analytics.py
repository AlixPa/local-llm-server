from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import ColumnElement, Select, case, func, literal_column, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Subquery

from db.models import ChatCompletionRecord, RequestStatus, ResponseRecord

type Endpoint = Literal["/v1/chat/completions", "/v1/responses"]


class UnknownCursorError(Exception):
    pass


@dataclass(frozen=True)
class RequestFilters:
    endpoint: Endpoint | None = None
    status: RequestStatus | None = None
    since: datetime | None = None
    until: datetime | None = None


@dataclass(frozen=True)
class RequestMetadata:
    external_id: str
    endpoint: Endpoint
    created_at: datetime
    model: str
    status: RequestStatus
    stream: bool
    prompt_tokens: int | None
    completion_tokens: int | None
    duration_ms: int
    time_to_first_token_ms: int | None
    generation_duration_ms: int | None
    load_duration_ms: int | None
    finish_reason: str | None
    error_type: str | None
    error_code: str | None


@dataclass(frozen=True)
class RequestSummary:
    request_count: int
    error_count: int
    prompt_tokens: int
    completion_tokens: int
    avg_duration_ms: float | None
    avg_time_to_first_token_ms: float | None
    avg_generation_duration_ms: float | None


def _branch(
    model: type[ChatCompletionRecord] | type[ResponseRecord], endpoint: Endpoint
) -> Select[tuple[object, ...]]:
    return select(
        model.external_id,
        literal_column(f"'{endpoint}'").label("endpoint"),
        model.created_at,
        model.model,
        model.status,
        model.stream,
        model.prompt_tokens,
        model.completion_tokens,
        model.duration_ms,
        model.time_to_first_token_ms,
        model.generation_duration_ms,
        model.load_duration_ms,
        model.finish_reason,
        model.error_type,
        model.error_code,
    )


def _combined() -> Subquery:
    return (
        _branch(ChatCompletionRecord, "/v1/chat/completions")
        .union_all(_branch(ResponseRecord, "/v1/responses"))
        .subquery("requests")
    )


def _conditions(
    combined: Subquery, filters: RequestFilters
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if filters.endpoint is not None:
        conditions.append(combined.c.endpoint == filters.endpoint)
    if filters.status is not None:
        conditions.append(combined.c.status == filters.status)
    if filters.since is not None:
        conditions.append(combined.c.created_at >= filters.since)
    if filters.until is not None:
        conditions.append(combined.c.created_at <= filters.until)
    return conditions


async def list_request_metadata(
    session: AsyncSession,
    *,
    limit: int,
    after: str | None,
    filters: RequestFilters,
) -> tuple[list[RequestMetadata], bool]:
    combined = _combined()
    statement = select(combined).where(*_conditions(combined, filters))
    if after is not None:
        cursor = (
            await session.execute(
                select(combined.c.created_at, combined.c.external_id).where(
                    combined.c.external_id == after
                )
            )
        ).first()
        if cursor is None:
            raise UnknownCursorError(after)
        statement = statement.where(
            tuple_(combined.c.created_at, combined.c.external_id)
            < tuple_(cursor.created_at, cursor.external_id)
        )
    statement = statement.order_by(
        combined.c.created_at.desc(), combined.c.external_id.desc()
    ).limit(limit + 1)
    rows = (await session.execute(statement)).all()
    items = [RequestMetadata(**row._asdict()) for row in rows]
    return items[:limit], len(items) > limit


async def get_request_summary(
    session: AsyncSession, *, filters: RequestFilters
) -> RequestSummary:
    combined = _combined()
    row = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(
                    func.sum(
                        case((combined.c.status == RequestStatus.FAILED, 1), else_=0)
                    ),
                    0,
                ),
                func.coalesce(func.sum(combined.c.prompt_tokens), 0),
                func.coalesce(func.sum(combined.c.completion_tokens), 0),
                func.avg(combined.c.duration_ms),
                func.avg(combined.c.time_to_first_token_ms),
                func.avg(combined.c.generation_duration_ms),
            ).where(*_conditions(combined, filters))
        )
    ).one()
    return RequestSummary(*row)
