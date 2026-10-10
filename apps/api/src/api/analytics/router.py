from datetime import UTC, datetime
from typing import Annotated

from db.engine import get_session
from db.models import RequestStatus
from db.repositories import analytics as repo
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.analytics.schemas import (
    AnalyticsRequestItem,
    AnalyticsRequestList,
    AnalyticsRequestSummary,
)
from api.errors import ApiError

router = APIRouter(prefix="/analytics/requests")


def _filters(
    endpoint: repo.Endpoint | None = None,
    status: RequestStatus | None = None,
    since: int | None = None,
    until: int | None = None,
) -> repo.RequestFilters:
    return repo.RequestFilters(
        endpoint=endpoint,
        status=status,
        since=None if since is None else datetime.fromtimestamp(since, UTC),
        until=None if until is None else datetime.fromtimestamp(until, UTC),
    )


Filters = Annotated[repo.RequestFilters, Depends(_filters)]


@router.get("")
async def list_requests(
    session: Annotated[AsyncSession, Depends(get_session)],
    filters: Filters,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    after: str | None = None,
) -> AnalyticsRequestList:
    try:
        records, has_more = await repo.list_request_metadata(
            session, limit=limit, after=after, filters=filters
        )
    except repo.UnknownCursorError:
        raise ApiError(
            404, "invalid_request_error", "not_found", "after", f"No such id: {after}"
        ) from None
    items = [AnalyticsRequestItem.from_metadata(record) for record in records]
    return AnalyticsRequestList(
        object="list",
        data=items,
        first_id=items[0].id if items else None,
        last_id=items[-1].id if items else None,
        has_more=has_more,
    )


@router.get("/summary")
async def get_requests_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    filters: Filters,
) -> AnalyticsRequestSummary:
    return AnalyticsRequestSummary.from_summary(
        await repo.get_request_summary(session, filters=filters)
    )
