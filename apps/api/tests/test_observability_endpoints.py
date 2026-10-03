import asyncio
from datetime import UTC, datetime

import httpx
from db.engine import get_async_session_factory
from db.models import TracedRequest
from db.repositories import tracing as repo
from httpx import AsyncClient
from ollama_fakes import OllamaMock, chat_response
from sqlalchemy.ext.asyncio import AsyncSession
from test_observability_tracing import MINIMAL, ReadTraces

NULLABLE = (
    "duration_ms",
    "http_status",
    "summary",
    "response_id",
    "error_message",
)


async def _seed(session: AsyncSession, count: int) -> list[int]:
    ids = []
    for index in range(count):
        request = await repo.create_request(
            session,
            endpoint="/v1/chat/completions",
            method="POST",
            started_at=datetime(2026, 1, 1, 0, 0, index, 123000, tzinfo=UTC),
        )
        ids.append(request.id)
    return ids


async def test_list_is_newest_first_with_envelope_and_nulls(
    client: AsyncClient, session: AsyncSession
) -> None:
    ids = await _seed(session, 2)

    response = await client.get("/v1/observability/requests")

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert body["has_more"] is False
    assert [item["id"] for item in body["data"]] == ids[::-1]
    assert (body["first_id"], body["last_id"]) == (ids[1], ids[0])
    first = body["data"][0]
    assert first["endpoint"] == "/v1/chat/completions"
    assert first["method"] == "POST"
    assert first["outcome"] == "in_progress"
    assert first["started_at"] == 1767225601
    assert first["started_at_ms"] == 1767225601123
    for field in NULLABLE:
        assert field in first
        assert first[field] is None


async def test_list_paginates_by_cursor(
    client: AsyncClient, session: AsyncSession
) -> None:
    ids = await _seed(session, 3)

    page = (await client.get("/v1/observability/requests", params={"limit": 2})).json()
    assert page["has_more"] is True
    rest = (
        await client.get(
            "/v1/observability/requests", params={"after": page["last_id"]}
        )
    ).json()

    assert [item["id"] for item in page["data"] + rest["data"]] == ids[::-1]
    assert rest["has_more"] is False


async def test_limit_bounds_are_rejected(client: AsyncClient) -> None:
    for limit in (0, 101):
        response = await client.get(f"/v1/observability/requests?limit={limit}")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "unprocessable_content"


async def test_invalid_outcome_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/v1/observability/requests?outcome=nope")

    assert response.status_code == 422


async def test_unknown_cursor_is_not_found(client: AsyncClient) -> None:
    response = await client.get("/v1/observability/requests?after=999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_empty_list_shape(client: AsyncClient) -> None:
    response = await client.get("/v1/observability/requests")

    assert response.json() == {
        "object": "list",
        "data": [],
        "first_id": None,
        "last_id": None,
        "has_more": False,
    }


async def test_events_stream_created_then_updated_and_own_calls_untracked(
    live_server: str, ollama_mock: OllamaMock, read_traces: ReadTraces
) -> None:
    ollama_mock.handler = lambda _: chat_response("Hello")
    lines: list[str] = []
    ready = asyncio.Event()

    async def listen() -> None:
        async with httpx.AsyncClient(base_url=live_server, timeout=10) as http:
            async with http.stream("GET", "/v1/observability/events") as response:
                assert response.headers["content-type"].startswith("text/event-stream")
                async for line in response.aiter_lines():
                    lines.append(line)
                    if line.startswith(":"):
                        ready.set()
                    if lines.count("event: request.updated") >= 1:
                        return

    listener = asyncio.create_task(listen())
    await asyncio.wait_for(ready.wait(), 5)
    async with httpx.AsyncClient(base_url=live_server) as http:
        await http.post("/v1/chat/completions", json=MINIMAL)
        await asyncio.wait_for(listener, 10)

        assert lines.index("event: request.created") < lines.index(
            "event: request.updated"
        )
        created = lines[lines.index("event: request.created") + 1]
        assert created == 'data: {"id":1}'
        # The list endpoint reads the overridden test session, so check the
        # committed row through the traces DB directly, without draining the writer
        async with get_async_session_factory()() as db_session:
            row = await db_session.get(TracedRequest, 1)
        assert row is not None

    assert len(await read_traces()) == 1
