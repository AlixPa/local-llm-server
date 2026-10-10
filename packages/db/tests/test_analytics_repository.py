import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from db.models import ChatCompletionRecord, RequestStatus, ResponseRecord
from db.repositories.analytics import (
    RequestFilters,
    RequestSummary,
    UnknownCursorError,
    get_request_summary,
    list_request_metadata,
)
from db.repositories.chat_completions import create_chat_completion
from db.repositories.responses import create_response
from sqlalchemy.ext.asyncio import AsyncSession

BASE = datetime(2026, 1, 1, tzinfo=UTC)
NO_FILTERS = RequestFilters()


async def _chat(
    session: AsyncSession,
    external_id: str,
    created_at: datetime,
    status: RequestStatus = RequestStatus.SUCCEEDED,
    **overrides: Any,
) -> None:
    values: dict[str, Any] = {
        "external_id": external_id,
        "created_at": created_at,
        "model": "qwen3.5:9b",
        "status": status,
        "stream": False,
        "n": 1,
        "prompt_tokens": 5,
        "completion_tokens": 7,
        "duration_ms": 100,
        "time_to_first_token_ms": None,
        "generation_duration_ms": 50,
        "load_duration_ms": None,
        "finish_reason": "stop",
        "error_type": None,
        "error_code": None,
        "request": {"messages": [{"role": "user", "content": "SECRET"}]},
        "response": None,
        "error_message": None,
    }
    await create_chat_completion(session, **{**values, **overrides})


async def _resp(
    session: AsyncSession,
    external_id: str,
    created_at: datetime,
    status: RequestStatus = RequestStatus.SUCCEEDED,
    **overrides: Any,
) -> None:
    values: dict[str, Any] = {
        "external_id": external_id,
        "created_at": created_at,
        "model": "qwen3.5:9b",
        "status": status,
        "stream": True,
        "prompt_tokens": 5,
        "completion_tokens": 7,
        "duration_ms": 100,
        "time_to_first_token_ms": None,
        "generation_duration_ms": 50,
        "load_duration_ms": None,
        "finish_reason": "stop",
        "error_type": None,
        "error_code": None,
        "request": {"input": "SECRET"},
        "response": None,
        "error_message": None,
    }
    await create_response(session, **{**values, **overrides})


async def _ids(session: AsyncSession, filters: RequestFilters) -> list[str]:
    records, _ = await list_request_metadata(
        session, limit=100, after=None, filters=filters
    )
    return [r.external_id for r in records]


async def test_orders_across_both_tables_with_external_id_tiebreak(
    session: AsyncSession,
) -> None:
    await _chat(session, "chatcmpl-a", BASE)
    await _resp(session, "resp_b", BASE)
    await _chat(session, "chatcmpl-c", BASE + timedelta(seconds=1))
    await _resp(session, "resp_a", BASE - timedelta(seconds=1))

    records, has_more = await list_request_metadata(
        session, limit=10, after=None, filters=NO_FILTERS
    )

    assert [r.external_id for r in records] == [
        "chatcmpl-c",
        "resp_b",
        "chatcmpl-a",
        "resp_a",
    ]
    assert [r.endpoint for r in records] == [
        "/v1/chat/completions",
        "/v1/responses",
        "/v1/chat/completions",
        "/v1/responses",
    ]
    assert has_more is False
    assert records[0].created_at == BASE + timedelta(seconds=1)
    assert records[0].status is RequestStatus.SUCCEEDED


async def test_cursor_pagination_across_union(session: AsyncSession) -> None:
    for i in range(5):
        if i % 2:
            await _resp(session, f"resp_{i}", BASE + timedelta(seconds=i))
        else:
            await _chat(session, f"chatcmpl-{i}", BASE + timedelta(seconds=i))

    first, more1 = await list_request_metadata(
        session, limit=2, after=None, filters=NO_FILTERS
    )
    second, more2 = await list_request_metadata(
        session, limit=2, after=first[-1].external_id, filters=NO_FILTERS
    )
    third, more3 = await list_request_metadata(
        session, limit=2, after=second[-1].external_id, filters=NO_FILTERS
    )

    assert [r.external_id for r in first] == ["chatcmpl-4", "resp_3"]
    assert [r.external_id for r in second] == ["chatcmpl-2", "resp_1"]
    assert [r.external_id for r in third] == ["chatcmpl-0"]
    assert (more1, more2, more3) == (True, True, False)


async def test_unknown_cursor_raises(session: AsyncSession) -> None:
    with pytest.raises(UnknownCursorError):
        await list_request_metadata(session, limit=5, after="nope", filters=NO_FILTERS)


async def test_filters(session: AsyncSession) -> None:
    await _chat(session, "chatcmpl-1", BASE)
    await _resp(session, "resp_1", BASE + timedelta(seconds=10), RequestStatus.FAILED)
    await _chat(
        session, "chatcmpl-2", BASE + timedelta(seconds=20), RequestStatus.CANCELLED
    )
    await _resp(session, "resp_2", BASE + timedelta(seconds=30))

    assert await _ids(session, RequestFilters(endpoint="/v1/responses")) == [
        "resp_2",
        "resp_1",
    ]
    assert await _ids(session, RequestFilters(status=RequestStatus.FAILED)) == [
        "resp_1"
    ]
    assert await _ids(session, RequestFilters(since=BASE + timedelta(seconds=20))) == [
        "resp_2",
        "chatcmpl-2",
    ]
    assert await _ids(session, RequestFilters(until=BASE + timedelta(seconds=10))) == [
        "resp_1",
        "chatcmpl-1",
    ]
    assert await _ids(
        session,
        RequestFilters(
            endpoint="/v1/chat/completions",
            status=RequestStatus.SUCCEEDED,
            since=BASE,
            until=BASE + timedelta(seconds=5),
        ),
    ) == ["chatcmpl-1"]


async def test_no_content_fields(session: AsyncSession) -> None:
    await _chat(session, "chatcmpl-1", BASE)
    await _resp(session, "resp_1", BASE, error_message="SECRET")

    records, _ = await list_request_metadata(
        session, limit=5, after=None, filters=NO_FILTERS
    )

    for record in records:
        assert not {"request", "response", "error_message", "n"} & set(vars(record))


async def test_empty_db(session: AsyncSession) -> None:
    assert await list_request_metadata(
        session, limit=5, after=None, filters=NO_FILTERS
    ) == ([], False)
    assert await get_request_summary(session, filters=NO_FILTERS) == RequestSummary(
        0, 0, 0, 0, None, None, None
    )


async def test_summary_covers_both_tables_and_follows_filters(
    session: AsyncSession,
) -> None:
    await _chat(session, "chatcmpl-1", BASE, time_to_first_token_ms=100)
    await _resp(
        session,
        "resp_1",
        BASE + timedelta(seconds=1),
        RequestStatus.FAILED,
        prompt_tokens=None,
        completion_tokens=None,
        duration_ms=300,
        generation_duration_ms=None,
    )
    await _resp(session, "resp_2", BASE + timedelta(seconds=2), RequestStatus.CANCELLED)

    assert await get_request_summary(session, filters=NO_FILTERS) == RequestSummary(
        request_count=3,
        error_count=1,
        prompt_tokens=10,
        completion_tokens=14,
        avg_duration_ms=500 / 3,
        avg_time_to_first_token_ms=100.0,
        avg_generation_duration_ms=50.0,
    )
    assert await get_request_summary(
        session, filters=RequestFilters(endpoint="/v1/responses")
    ) == RequestSummary(2, 1, 5, 7, 200.0, None, 50.0)


async def test_page_query_is_fast_with_10k_rows(session: AsyncSession) -> None:
    session.add_all(
        ChatCompletionRecord(
            external_id=f"chatcmpl-{i}",
            created_at=BASE + timedelta(seconds=2 * i),
            model="m",
            status=RequestStatus.SUCCEEDED,
            stream=False,
            n=1,
            prompt_tokens=1,
            completion_tokens=1,
            duration_ms=1,
        )
        for i in range(5_000)
    )
    session.add_all(
        ResponseRecord(
            external_id=f"resp_{i}",
            created_at=BASE + timedelta(seconds=2 * i + 1),
            model="m",
            status=RequestStatus.SUCCEEDED,
            stream=False,
            prompt_tokens=1,
            completion_tokens=1,
            duration_ms=1,
        )
        for i in range(5_000)
    )
    await session.commit()

    start = time.perf_counter()
    records, has_more = await list_request_metadata(
        session, limit=100, after="resp_2500", filters=NO_FILTERS
    )
    elapsed = time.perf_counter() - start

    assert len(records) == 100
    assert has_more is True
    assert elapsed < 0.5
