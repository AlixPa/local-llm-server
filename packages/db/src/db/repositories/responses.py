from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import RequestStatus, ResponseContent, ResponseRecord


async def create_response(
    session: AsyncSession,
    *,
    external_id: str,
    created_at: datetime,
    model: str,
    status: RequestStatus,
    stream: bool,
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
) -> ResponseRecord:
    record = ResponseRecord(
        external_id=external_id,
        created_at=created_at,
        model=model,
        status=status,
        stream=stream,
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
        ResponseContent(
            record_id=record.id,
            request=request,
            response=response,
            error_message=error_message,
        )
    )
    await session.commit()
    return record
