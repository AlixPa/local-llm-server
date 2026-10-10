import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from db.models import ChatCompletionRecord, RequestStatus, ResponseRecord
from db.repositories.chat_completions import create_chat_completion
from db.repositories.responses import create_response
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

SENTINEL = "SENTINEL-PROMPT-TEXT"
BASE = datetime(2026, 1, 1, tzinfo=UTC)

type Schema = Callable[[Any, str], None]


async def _seed(
    session: AsyncSession,
    index: int,
    status: RequestStatus = RequestStatus.SUCCEEDED,
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


async def _seed_response(
    session: AsyncSession,
    index: int,
    status: RequestStatus = RequestStatus.SUCCEEDED,
    **overrides: Any,
) -> None:
    values: dict[str, Any] = {
        "external_id": f"resp_{index}",
        "created_at": BASE + timedelta(seconds=index),
        "model": "qwen3.5:9b",
        "status": status,
        "stream": False,
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "duration_ms": 500,
        "time_to_first_token_ms": None,
        "generation_duration_ms": 400,
        "load_duration_ms": None,
        "finish_reason": "stop",
        "error_type": None,
        "error_code": None,
        "request": {"input": SENTINEL},
        "response": {"output": SENTINEL},
        "error_message": SENTINEL,
    }
    await create_response(session, **{**values, **overrides})


LIST = "/v1/analytics/requests"
SUMMARY = "/v1/analytics/requests/summary"


def _ts(index: int) -> int:
    return int((BASE + timedelta(seconds=index)).timestamp())


async def test_combined_list_shape(client: AsyncClient, session: AsyncSession) -> None:
    await _seed(session, 1)
    await _seed_response(session, 2)

    response = await client.get(LIST)

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert body["first_id"] == "resp_2"
    assert body["last_id"] == "chatcmpl-1"
    assert body["has_more"] is False
    assert body["data"][0] == {
        "id": "resp_2",
        "endpoint": "/v1/responses",
        "created": _ts(2),
        "model": "qwen3.5:9b",
        "status": "succeeded",
        "stream": False,
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
        "duration_ms": 500,
        "time_to_first_token_ms": None,
        "generation_duration_ms": 400,
        "load_duration_ms": None,
        "finish_reason": "stop",
        "error_type": None,
        "error_code": None,
    }
    assert body["data"][1]["endpoint"] == "/v1/chat/completions"
    assert "n" not in body["data"][1]


async def test_failed_request_has_null_tokens(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed(
        session,
        1,
        RequestStatus.FAILED,
        prompt_tokens=None,
        completion_tokens=None,
        error_type="invalid_request_error",
        error_code="model_not_found",
    )

    [item] = (await client.get(LIST)).json()["data"]

    assert item["total_tokens"] is None
    assert item["error_code"] == "model_not_found"


async def test_pagination_across_endpoints(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed(session, 0)
    await _seed_response(session, 1)
    await _seed(session, 2)

    page1 = (await client.get(f"{LIST}?limit=2")).json()
    page2 = (await client.get(f"{LIST}?limit=2&after={page1['last_id']}")).json()

    assert [d["id"] for d in page1["data"]] == ["chatcmpl-2", "resp_1"]
    assert page1["has_more"] is True
    assert [d["id"] for d in page2["data"]] == ["chatcmpl-0"]
    assert page2["has_more"] is False


async def test_filters(client: AsyncClient, session: AsyncSession) -> None:
    await _seed(session, 1)
    await _seed_response(session, 2, RequestStatus.FAILED)
    await _seed(session, 3, RequestStatus.CANCELLED)
    await _seed_response(session, 4)

    async def ids(query: str) -> list[str]:
        return [d["id"] for d in (await client.get(f"{LIST}?{query}")).json()["data"]]

    assert await ids("endpoint=/v1/responses") == ["resp_4", "resp_2"]
    assert await ids("status=failed") == ["resp_2"]
    assert await ids(f"since={_ts(3)}") == ["resp_4", "chatcmpl-3"]
    assert await ids(f"until={_ts(2)}") == ["resp_2", "chatcmpl-1"]
    assert await ids(f"endpoint=/v1/responses&since={_ts(3)}") == ["resp_4"]
    summary = (await client.get(f"{SUMMARY}?endpoint=/v1/responses")).json()
    assert summary["request_count"] == 2
    assert summary["error_count"] == 1


async def test_invalid_params_are_422(
    client: AsyncClient, validate_schema: Schema
) -> None:
    for query in ("limit=0", "limit=101", "status=bogus", "endpoint=/v1/x"):
        response = await client.get(f"{LIST}?{query}")

        assert response.status_code == 422
        validate_schema(response.json(), "ErrorResponse")
        assert response.json()["error"]["code"] == "unprocessable_content"


async def test_unknown_after_is_404(
    client: AsyncClient, validate_schema: Schema
) -> None:
    response = await client.get(f"{LIST}?after=nope")

    assert response.status_code == 404
    validate_schema(response.json(), "ErrorResponse")
    assert response.json()["error"]["code"] == "not_found"


async def test_removed_chat_only_routes_are_not_found(
    client: AsyncClient, validate_schema: Schema
) -> None:
    for path in (
        "/v1/analytics/chat-completions",
        "/v1/analytics/chat-completions/summary",
    ):
        response = await client.get(path)

        assert response.status_code == 404
        validate_schema(response.json(), "ErrorResponse")
        assert response.json()["error"]["code"] == "not_found"


async def test_empty_state(client: AsyncClient) -> None:
    listing = (await client.get(LIST)).json()
    summary = (await client.get(SUMMARY)).json()

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
        RequestStatus.FAILED,
        prompt_tokens=None,
        completion_tokens=None,
        duration_ms=2000,
        time_to_first_token_ms=None,
        generation_duration_ms=None,
    )
    await _seed_response(session, 3, RequestStatus.CANCELLED)

    listing = await client.get(LIST)
    summary = await client.get(SUMMARY)

    assert summary.json() == {
        "request_count": 3,
        "error_count": 1,
        "prompt_tokens": 11,
        "completion_tokens": 22,
        "avg_duration_ms": 3500 / 3,
        "avg_time_to_first_token_ms": 100.0,
        "avg_generation_duration_ms": 600.0,
    }
    assert SENTINEL not in listing.text
    assert SENTINEL not in summary.text


async def test_list_is_fast_with_10k_rows(
    client: AsyncClient, session: AsyncSession
) -> None:
    session.add_all(
        ChatCompletionRecord(
            external_id=f"chatcmpl-{i}",
            created_at=BASE + timedelta(seconds=2 * i),
            model="m",
            status=RequestStatus.SUCCEEDED,
            stream=False,
            n=1,
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
            duration_ms=1,
        )
        for i in range(5_000)
    )
    await session.commit()

    start = time.perf_counter()
    listing = await client.get(f"{LIST}?limit=100&after=resp_2500")
    summary = await client.get(SUMMARY)
    elapsed = time.perf_counter() - start

    assert listing.status_code == 200
    assert summary.json()["request_count"] == 10_000
    assert elapsed < 2
