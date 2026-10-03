import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from db.models import (
    ChatCompletionContent,
    ChatCompletionRecord,
    ChatCompletionStatus,
)
from db.repositories.chat_completions import (
    ChatCompletionSummary,
    UnknownCursorError,
    create_chat_completion,
    get_chat_completion_summary,
    list_chat_completion_metadata,
)
from sqlalchemy import select
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession


async def _create(
    session: AsyncSession, created_at: datetime | None = None
) -> ChatCompletionRecord:
    return await create_chat_completion(
        session,
        external_id="chatcmpl-abc",
        created_at=created_at or datetime(2026, 1, 1, 12, tzinfo=UTC),
        model="qwen3.5:9b",
        status=ChatCompletionStatus.SUCCEEDED,
        stream=False,
        n=1,
        prompt_tokens=5,
        completion_tokens=7,
        duration_ms=120,
        time_to_first_token_ms=None,
        generation_duration_ms=80,
        load_duration_ms=10,
        finish_reason="stop",
        error_type=None,
        error_code=None,
        request={"messages": [{"role": "user", "content": "hi"}]},
        response=None,
        error_message=None,
    )


async def test_create_persists_record_and_content(session: AsyncSession) -> None:
    record = await _create(session)

    stored = (await session.execute(select(ChatCompletionRecord))).scalar_one()
    content = (await session.execute(select(ChatCompletionContent))).scalar_one()
    assert stored.id == record.id
    assert stored.external_id == "chatcmpl-abc"
    assert stored.status is ChatCompletionStatus.SUCCEEDED
    assert stored.prompt_tokens == 5
    assert content.record_id == record.id
    assert content.request == {"messages": [{"role": "user", "content": "hi"}]}
    assert content.response is None


async def test_content_cascades_on_record_delete(session: AsyncSession) -> None:
    record = await _create(session)

    await session.delete(record)
    await session.commit()

    assert (await session.execute(select(ChatCompletionContent))).first() is None


async def test_naive_datetime_is_rejected(session: AsyncSession) -> None:
    with pytest.raises(StatementError, match="naive"):
        await _create(session, created_at=datetime(2026, 1, 1, 12))


async def test_created_at_is_restored_as_utc(session: AsyncSession) -> None:
    created_at = datetime(2026, 1, 1, 12, tzinfo=UTC)
    await _create(session, created_at=created_at)
    session.expunge_all()

    stored = (await session.execute(select(ChatCompletionRecord))).scalar_one()

    assert stored.created_at == created_at
    assert stored.created_at.tzinfo == UTC


async def _seed(
    session: AsyncSession,
    external_id: str,
    created_at: datetime,
    status: ChatCompletionStatus = ChatCompletionStatus.SUCCEEDED,
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


async def test_list_orders_newest_first_with_id_tiebreak(
    session: AsyncSession,
) -> None:
    same = datetime(2026, 1, 1, 12, tzinfo=UTC)
    await _seed(session, "a", same)
    await _seed(session, "b", same)
    await _seed(session, "c", same + timedelta(seconds=1))

    records, has_more = await list_chat_completion_metadata(
        session, limit=10, after=None
    )

    assert [r.external_id for r in records] == ["c", "b", "a"]
    assert has_more is False


async def test_list_pages_with_cursor(session: AsyncSession) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(5):
        await _seed(session, f"id-{i}", base + timedelta(seconds=i))

    first, more1 = await list_chat_completion_metadata(session, limit=2, after=None)
    second, more2 = await list_chat_completion_metadata(
        session, limit=2, after=first[-1].external_id
    )
    third, more3 = await list_chat_completion_metadata(
        session, limit=2, after=second[-1].external_id
    )

    assert [r.external_id for r in first] == ["id-4", "id-3"]
    assert [r.external_id for r in second] == ["id-2", "id-1"]
    assert [r.external_id for r in third] == ["id-0"]
    assert (more1, more2, more3) == (True, True, False)


async def test_list_unknown_cursor_raises(session: AsyncSession) -> None:
    with pytest.raises(UnknownCursorError):
        await list_chat_completion_metadata(session, limit=5, after="nope")


async def test_list_returns_no_content_fields(session: AsyncSession) -> None:
    await _seed(session, "a", datetime(2026, 1, 1, tzinfo=UTC))

    [record], _ = await list_chat_completion_metadata(session, limit=5, after=None)

    assert not {"request", "response", "error_message"} & set(vars(record))


async def test_empty_db(session: AsyncSession) -> None:
    assert await list_chat_completion_metadata(session, limit=5, after=None) == (
        [],
        False,
    )
    assert await get_chat_completion_summary(session) == ChatCompletionSummary(
        0, 0, 0, 0, None, None, None
    )


async def test_summary_figures(session: AsyncSession) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await _seed(session, "a", base, time_to_first_token_ms=100, duration_ms=100)
    await _seed(
        session,
        "b",
        base + timedelta(seconds=1),
        ChatCompletionStatus.FAILED,
        prompt_tokens=None,
        completion_tokens=None,
        duration_ms=300,
        generation_duration_ms=None,
    )
    await _seed(
        session, "c", base + timedelta(seconds=2), ChatCompletionStatus.CANCELLED
    )

    summary = await get_chat_completion_summary(session)

    assert summary == ChatCompletionSummary(
        request_count=3,
        error_count=1,
        prompt_tokens=10,
        completion_tokens=14,
        avg_duration_ms=500 / 3,
        avg_time_to_first_token_ms=100.0,
        avg_generation_duration_ms=50.0,
    )


async def test_page_query_is_fast_with_10k_rows(session: AsyncSession) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        ChatCompletionRecord(
            external_id=f"id-{i}",
            created_at=base + timedelta(seconds=i),
            model="m",
            status=ChatCompletionStatus.SUCCEEDED,
            stream=False,
            n=1,
            prompt_tokens=1,
            completion_tokens=1,
            duration_ms=1,
        )
        for i in range(10_000)
    ]
    session.add_all(rows)
    await session.commit()
    cursor = "id-5000"

    start = time.perf_counter()
    records, has_more = await list_chat_completion_metadata(
        session, limit=100, after=cursor
    )
    elapsed = time.perf_counter() - start

    assert len(records) == 100
    assert has_more is True
    assert elapsed < 0.5
