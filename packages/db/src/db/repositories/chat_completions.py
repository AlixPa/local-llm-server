from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    ChatCompletionContent,
    ChatCompletionRecord,
    ChatCompletionStatus,
)


async def create_chat_completion(
    session: AsyncSession,
    *,
    external_id: str,
    created_at: datetime,
    model: str,
    status: ChatCompletionStatus,
    stream: bool,
    n: int,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    duration_ms: int,
    time_to_first_token_ms: int | None,
    generation_duration_ms: int | None,
    load_duration_ms: int | None,
    finish_reason: str | None,
    error_type: str | None,
    error_code: str | None,
    request: dict[str, Any],
    response: dict[str, Any] | None,
    error_message: str | None,
) -> ChatCompletionRecord:
    record = ChatCompletionRecord(
        external_id=external_id,
        created_at=created_at,
        model=model,
        status=status,
        stream=stream,
        n=n,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        duration_ms=duration_ms,
        time_to_first_token_ms=time_to_first_token_ms,
        generation_duration_ms=generation_duration_ms,
        load_duration_ms=load_duration_ms,
        finish_reason=finish_reason,
        error_type=error_type,
        error_code=error_code,
    )
    session.add(record)
    await session.flush()
    session.add(
        ChatCompletionContent(
            record_id=record.id,
            request=request,
            response=response,
            error_message=error_message,
        )
    )
    await session.commit()
    return record


class UnknownCursorError(Exception):
    pass


@dataclass(frozen=True)
class ChatCompletionSummary:
    request_count: int
    error_count: int
    prompt_tokens: int
    completion_tokens: int
    avg_duration_ms: float | None
    avg_time_to_first_token_ms: float | None
    avg_generation_duration_ms: float | None


async def list_chat_completion_metadata(
    session: AsyncSession, *, limit: int, after: str | None
) -> tuple[list[ChatCompletionRecord], bool]:
    statement = select(ChatCompletionRecord)
    if after is not None:
        cursor = (
            await session.execute(
                select(ChatCompletionRecord.created_at, ChatCompletionRecord.id).where(
                    ChatCompletionRecord.external_id == after
                )
            )
        ).first()
        if cursor is None:
            raise UnknownCursorError(after)
        statement = statement.where(
            tuple_(ChatCompletionRecord.created_at, ChatCompletionRecord.id)
            < tuple_(cursor.created_at, cursor.id)
        )
    statement = statement.order_by(
        ChatCompletionRecord.created_at.desc(), ChatCompletionRecord.id.desc()
    ).limit(limit + 1)
    rows = list((await session.execute(statement)).scalars())
    return rows[:limit], len(rows) > limit


async def get_chat_completion_summary(
    session: AsyncSession,
) -> ChatCompletionSummary:
    row = (
        await session.execute(
            select(
                func.count(ChatCompletionRecord.id),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                ChatCompletionRecord.status
                                == ChatCompletionStatus.FAILED,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(func.sum(ChatCompletionRecord.prompt_tokens), 0),
                func.coalesce(func.sum(ChatCompletionRecord.completion_tokens), 0),
                func.avg(ChatCompletionRecord.duration_ms),
                func.avg(ChatCompletionRecord.time_to_first_token_ms),
                func.avg(ChatCompletionRecord.generation_duration_ms),
            )
        )
    ).one()
    return ChatCompletionSummary(*row)
