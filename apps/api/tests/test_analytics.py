from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from db.models import ChatCompletionStatus
from db.repositories.chat_completions import create_chat_completion
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

SENTINEL = "SENTINEL-PROMPT-TEXT"
BASE = datetime(2026, 1, 1, tzinfo=UTC)

type Schema = Callable[[Any, str], None]


async def _seed(
    session: AsyncSession,
    index: int,
    status: ChatCompletionStatus = ChatCompletionStatus.SUCCEEDED,
    **overrides: Any,
) -> None:
    values: dict[str, Any] = {
        "external_id": f"chatcmpl-{index}",
        "created_at": BASE + timedelta(seconds=index),
        "model": "qwen3.5:9b",
        "status": status,
        "stream": True,
        "n": 1,
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "duration_ms": 1000,
        "time_to_first_token_ms": 100,
        "generation_duration_ms": 800,
        "load_duration_ms": 5,
        "finish_reason": "stop",
        "error_type": None,
        "error_code": None,
        "request": {"messages": [{"role": "user", "content": SENTINEL}]},
        "response": {"choices": [{"message": {"content": SENTINEL}}]},
        "error_message": SENTINEL,
    }
    await create_chat_completion(session, **{**values, **overrides})


async def test_list_shape(client: AsyncClient, session: AsyncSession) -> None:
    await _seed(session, 1)

    response = await client.get("/v1/analytics/chat-completions")

    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "data": [
            {
                "id": "chatcmpl-1",
                "created": int((BASE + timedelta(seconds=1)).timestamp()),
                "model": "qwen3.5:9b",
                "status": "succeeded",
                "stream": True,
                "n": 1,
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
                "duration_ms": 1000,
                "time_to_first_token_ms": 100,
                "generation_duration_ms": 800,
                "load_duration_ms": 5,
                "finish_reason": "stop",
                "error_type": None,
                "error_code": None,
            }
        ],
        "first_id": "chatcmpl-1",
        "last_id": "chatcmpl-1",
        "has_more": False,
    }


async def test_failed_request_has_null_tokens(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed(
        session,
        1,
        ChatCompletionStatus.FAILED,
        prompt_tokens=None,
        completion_tokens=None,
        error_type="invalid_request_error",
        error_code="model_not_found",
    )

    [item] = (await client.get("/v1/analytics/chat-completions")).json()["data"]

    assert item["total_tokens"] is None
    assert item["error_code"] == "model_not_found"


async def test_pagination(client: AsyncClient, session: AsyncSession) -> None:
    for i in range(3):
        await _seed(session, i)

    page1 = (await client.get("/v1/analytics/chat-completions?limit=2")).json()
    page2 = (
        await client.get(
            f"/v1/analytics/chat-completions?limit=2&after={page1['last_id']}"
        )
    ).json()

    assert [d["id"] for d in page1["data"]] == ["chatcmpl-2", "chatcmpl-1"]
    assert page1["has_more"] is True
    assert page1["first_id"] == "chatcmpl-2"
    assert [d["id"] for d in page2["data"]] == ["chatcmpl-0"]
    assert page2["has_more"] is False


async def test_limit_bounds_are_422(
    client: AsyncClient, validate_schema: Schema
) -> None:
    for limit in (0, 101):
        response = await client.get(f"/v1/analytics/chat-completions?limit={limit}")

        assert response.status_code == 422
        validate_schema(response.json(), "ErrorResponse")
        assert response.json()["error"]["code"] == "unprocessable_content"


async def test_unknown_after_is_404(
    client: AsyncClient, validate_schema: Schema
) -> None:
    response = await client.get("/v1/analytics/chat-completions?after=nope")

    assert response.status_code == 404
    validate_schema(response.json(), "ErrorResponse")
    assert response.json()["error"]["code"] == "not_found"


async def test_empty_state(client: AsyncClient) -> None:
    listing = (await client.get("/v1/analytics/chat-completions")).json()
    summary = (await client.get("/v1/analytics/chat-completions/summary")).json()

    assert listing == {
        "object": "list",
        "data": [],
        "first_id": None,
        "last_id": None,
        "has_more": False,
    }
    assert summary == {
        "request_count": 0,
        "error_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "avg_duration_ms": None,
        "avg_time_to_first_token_ms": None,
        "avg_generation_duration_ms": None,
    }


async def test_summary_and_no_content_leak(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed(session, 1)
    await _seed(
        session,
        2,
        ChatCompletionStatus.FAILED,
        prompt_tokens=None,
        completion_tokens=None,
        duration_ms=2000,
        time_to_first_token_ms=None,
        generation_duration_ms=None,
    )
    await _seed(session, 3, ChatCompletionStatus.CANCELLED)

    listing = await client.get("/v1/analytics/chat-completions")
    summary = await client.get("/v1/analytics/chat-completions/summary")

    assert summary.json() == {
        "request_count": 3,
        "error_count": 1,
        "prompt_tokens": 20,
        "completion_tokens": 40,
        "avg_duration_ms": 4000 / 3,
        "avg_time_to_first_token_ms": 100.0,
        "avg_generation_duration_ms": 800.0,
    }
    assert SENTINEL not in listing.text
    assert SENTINEL not in summary.text
