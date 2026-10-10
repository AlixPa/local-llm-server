import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from db.engine import get_async_session_factory
from db.models import Participant, StepKind, StepStatus, TracedRequest, TraceOutcome
from db.repositories import tracing as repo
from httpx import AsyncClient
from ollama_fakes import OllamaMock, chat_response
from sqlalchemy.ext.asyncio import AsyncSession
from test_observability_tracing import MINIMAL, ReadTraces

ITEM_FIELDS = (
    "id",
    "endpoint",
    "method",
    "started_at",
    "started_at_ms",
    "duration_ms",
    "http_status",
    "outcome",
    "summary",
    "response_id",
    "error_message",
)
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


async def _seed_mixed(session: AsyncSession) -> dict[str, int]:
    specs = [
        ("a", "/v1/chat/completions", TraceOutcome.SUCCESS),
        ("b", "/v1/chat/completions", TraceOutcome.ERROR),
        ("c", "/v1/other", TraceOutcome.ERROR),
        ("d", "/v1/chat/completions", TraceOutcome.CANCELED),
    ]
    ids: dict[str, int] = {}
    for index, (name, endpoint, outcome) in enumerate(specs):
        request = await repo.create_request(
            session,
            endpoint=endpoint,
            method="POST",
            started_at=datetime(2026, 1, 1, 0, 0, index * 10, tzinfo=UTC),
        )
        await repo.finish_request(
            session,
            request.id,
            outcome=outcome,
            duration_ms=1,
            http_status=200,
            summary=None,
            response_id=None,
            error_message=None,
        )
        ids[name] = request.id
    return ids


async def _ids(
    client: AsyncClient, params: dict[str, int | str | list[str]]
) -> list[int]:
    response = await client.get("/v1/observability/requests", params=params)
    assert response.status_code == 200
    return [item["id"] for item in response.json()["data"]]


async def test_endpoint_filter_is_exact_match(
    client: AsyncClient, session: AsyncSession
) -> None:
    ids = await _seed_mixed(session)

    assert await _ids(client, {"endpoint": "/v1/other"}) == [ids["c"]]
    assert await _ids(client, {"endpoint": "/v1/chat"}) == []


async def test_endpoint_filter_returns_only_responses_entries(
    client: AsyncClient, session: AsyncSession
) -> None:
    ids = await _seed_mixed(session)
    request = await repo.create_request(
        session,
        endpoint="/v1/responses",
        method="POST",
        started_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert await _ids(client, {"endpoint": "/v1/responses"}) == [request.id]
    assert request.id not in await _ids(client, {"endpoint": "/v1/other"})
    assert ids["c"] in await _ids(client, {})


async def test_outcome_filter_is_repeatable(
    client: AsyncClient, session: AsyncSession
) -> None:
    ids = await _seed_mixed(session)

    assert await _ids(client, {"outcome": "error"}) == [ids["c"], ids["b"]]
    both = await _ids(client, {"outcome": ["error", "canceled"]})
    assert both == [ids["d"], ids["c"], ids["b"]]


async def test_since_is_inclusive_and_until_is_exclusive(
    client: AsyncClient, session: AsyncSession
) -> None:
    ids = await _seed_mixed(session)
    base = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())

    # b starts at +10s and c at +20s
    window = await _ids(client, {"since": base + 10, "until": base + 30})
    assert window == [ids["c"], ids["b"]]
    assert await _ids(client, {"until": base + 10}) == [ids["a"]]
    assert await _ids(client, {"since": base + 31}) == []


async def test_filters_combine_with_cursor_pagination(
    client: AsyncClient, session: AsyncSession
) -> None:
    ids = await _seed_mixed(session)
    params: dict[str, int | str] = {"endpoint": "/v1/chat/completions", "limit": 1}

    first = (await client.get("/v1/observability/requests", params=params)).json()
    second = (
        await client.get(
            "/v1/observability/requests",
            params={**params, "after": first["last_id"]},
        )
    ).json()
    third = (
        await client.get(
            "/v1/observability/requests",
            params={**params, "after": second["last_id"]},
        )
    ).json()

    assert [first["data"][0]["id"], second["data"][0]["id"]] == [ids["d"], ids["b"]]
    assert first["has_more"] is True
    assert [item["id"] for item in third["data"]] == [ids["a"]]
    assert third["has_more"] is False


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


async def test_detail_shape_and_step_order(
    client: AsyncClient, session: AsyncSession
) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    request = await repo.create_request(
        session, endpoint="/v1/chat/completions", method="POST", started_at=start
    )
    plan = [
        (StepKind.REQUEST_RECEIVED, Participant.CLIENT, Participant.API, 0, None),
        (StepKind.SENT_TO_OLLAMA, Participant.API, Participant.OLLAMA, 4, None),
        (StepKind.RECEIVED_FROM_OLLAMA, Participant.OLLAMA, Participant.API, 4, 3100),
        (StepKind.RESPONSE_RETURNED, Participant.API, Participant.CLIENT, 3110, None),
    ]
    await repo.add_steps(
        session,
        request.id,
        [
            repo.NewStep(
                position=position,
                kind=kind,
                source=source,
                destination=destination,
                status=StepStatus.COMPLETED,
                started_at=start + timedelta(milliseconds=offset),
                duration_ms=duration,
                content={"position": position},
            )
            for position, (kind, source, destination, offset, duration) in enumerate(
                plan
            )
        ],
    )

    response = await client.get(f"/v1/observability/requests/{request.id}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {*ITEM_FIELDS, "steps"}
    steps = body["steps"]
    assert [s["position"] for s in steps] == [0, 1, 2, 3]
    assert [s["kind"] for s in steps] == [kind.value for kind, *_ in plan]
    assert [(s["source"], s["destination"]) for s in steps] == [
        (source.value, destination.value) for _, source, destination, *_ in plan
    ]
    for step in steps:
        assert set(step) == {
            "position",
            "kind",
            "source",
            "destination",
            "status",
            "offset_ms",
            "duration_ms",
            "content",
            "error_message",
        }
    assert [s["offset_ms"] for s in steps] == [0, 4, 4, 3110]
    assert [s["duration_ms"] for s in steps] == [None, None, 3100, None]
    assert steps[2]["content"] == {"position": 2}
    assert steps[2]["error_message"] is None


async def test_detail_in_progress_step_has_null_duration_and_content(
    client: AsyncClient, session: AsyncSession
) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    request = await repo.create_request(
        session, endpoint="/v1/chat/completions", method="POST", started_at=start
    )
    await repo.add_steps(
        session,
        request.id,
        [
            repo.NewStep(
                position=0,
                kind=StepKind.RECEIVED_FROM_OLLAMA,
                source=Participant.OLLAMA,
                destination=Participant.API,
                status=StepStatus.IN_PROGRESS,
                started_at=start,
            )
        ],
    )

    body = (await client.get(f"/v1/observability/requests/{request.id}")).json()

    [step] = body["steps"]
    assert step["status"] == "in_progress"
    assert step["duration_ms"] is None
    assert step["content"] is None


async def test_detail_of_unknown_id_is_not_found(client: AsyncClient) -> None:
    response = await client.get("/v1/observability/requests/999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_detail_with_non_integer_id_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/v1/observability/requests/abc")

    assert response.status_code == 422
