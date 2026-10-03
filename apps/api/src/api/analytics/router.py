from typing import Annotated

from db.engine import get_session
from db.repositories import chat_completions as repo
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.analytics.schemas import (
    ChatCompletionAnalyticsItem,
    ChatCompletionAnalyticsList,
    ChatCompletionAnalyticsSummary,
)
from api.errors import ApiError

router = APIRouter(prefix="/analytics/chat-completions")


@router.get("")
async def list_chat_completions(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    after: str | None = None,
) -> ChatCompletionAnalyticsList:
    try:
        records, has_more = await repo.list_chat_completion_metadata(
            session, limit=limit, after=after
        )
    except repo.UnknownCursorError:
        raise ApiError(
            404, "invalid_request_error", "not_found", "after", f"No such id: {after}"
        ) from None
    items = [ChatCompletionAnalyticsItem.from_record(record) for record in records]
    return ChatCompletionAnalyticsList(
        object="list",
        data=items,
        first_id=items[0].id if items else None,
        last_id=items[-1].id if items else None,
        has_more=has_more,
    )


@router.get("/summary")
async def get_chat_completions_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatCompletionAnalyticsSummary:
    return ChatCompletionAnalyticsSummary.from_summary(
        await repo.get_chat_completion_summary(session)
    )
