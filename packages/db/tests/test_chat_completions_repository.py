from datetime import UTC, datetime

import pytest
from db.models import (
    ChatCompletionContent,
    ChatCompletionRecord,
    ChatCompletionStatus,
)
from db.repositories.chat_completions import create_chat_completion
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
