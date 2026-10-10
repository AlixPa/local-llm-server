from datetime import UTC, datetime
from typing import Any

import pytest
from db.models import RequestStatus, ResponseContent, ResponseRecord
from db.repositories.responses import create_response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def _create(
    session: AsyncSession,
    external_id: str = "resp_abc",
    status: RequestStatus = RequestStatus.SUCCEEDED,
    **overrides: Any,
) -> ResponseRecord:
    values: dict[str, Any] = {
        "external_id": external_id,
        "created_at": datetime(2026, 1, 1, 12, tzinfo=UTC),
        "model": "qwen3.5:9b",
        "status": status,
        "stream": False,
        "prompt_tokens": 5,
        "completion_tokens": 7,
        "duration_ms": 120,
        "time_to_first_token_ms": None,
        "generation_duration_ms": 80,
        "load_duration_ms": 10,
        "finish_reason": "stop",
        "error_type": None,
        "error_code": None,
        "request": {"input": "hi"},
        "response": {"id": external_id},
        "error_message": None,
    }
    values.update(overrides)
    return await create_response(session, **values)


async def test_create_persists_record_and_content(session: AsyncSession) -> None:
    record = await _create(session)

    stored = (await session.execute(select(ResponseRecord))).scalar_one()
    content = (await session.execute(select(ResponseContent))).scalar_one()
    assert stored.id == record.id
    assert stored.external_id == "resp_abc"
    assert stored.status is RequestStatus.SUCCEEDED
    assert stored.prompt_tokens == 5
    assert content.record_id == record.id
    assert content.request == {"input": "hi"}
    assert content.response == {"id": "resp_abc"}


@pytest.mark.parametrize("status", [RequestStatus.FAILED, RequestStatus.CANCELLED])
async def test_failed_and_cancelled_keep_nullable_fields_null(
    session: AsyncSession, status: RequestStatus
) -> None:
    await _create(
        session,
        status=status,
        prompt_tokens=None,
        completion_tokens=None,
        generation_duration_ms=None,
        load_duration_ms=None,
        finish_reason=None,
        error_type="server_error" if status is RequestStatus.FAILED else None,
        error_code=None,
        response=None,
        error_message="boom" if status is RequestStatus.FAILED else None,
    )
    session.expunge_all()

    stored = (await session.execute(select(ResponseRecord))).scalar_one()
    content = (await session.execute(select(ResponseContent))).scalar_one()
    assert stored.status is status
    assert stored.prompt_tokens is None
    assert stored.completion_tokens is None
    assert stored.time_to_first_token_ms is None
    assert stored.finish_reason is None
    assert stored.error_code is None
    assert content.response is None


async def test_content_cascades_on_record_delete(session: AsyncSession) -> None:
    record = await _create(session)

    await session.delete(record)
    await session.commit()

    assert (await session.execute(select(ResponseContent))).first() is None


async def test_external_id_is_unique(session: AsyncSession) -> None:
    await _create(session)

    with pytest.raises(IntegrityError):
        await _create(session)
