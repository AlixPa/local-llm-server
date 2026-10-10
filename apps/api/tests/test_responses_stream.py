import asyncio
import json
from collections.abc import Callable
from typing import Any

from db.models import RequestStatus, ResponseContent, ResponseRecord
from fastapi import FastAPI
from httpx import AsyncClient, Response
from ollama_fakes import OllamaMock, hanging_stream, ndjson, stream_lines
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MODEL = "qwen3.5:9b"
STREAM = {"model": MODEL, "input": "Hi", "stream": True}
TOOL = {
    "type": "function",
    "name": "f",
    "parameters": {"type": "object"},
    "strict": False,
}

type Schema = Callable[[Any, str], None]


def _frames(text: str) -> list[tuple[str, dict[str, Any]]]:
    assert text.endswith("\n\n")
    frames: list[tuple[str, dict[str, Any]]] = []
    for part in text[:-2].split("\n\n"):
        event_line, data_line = part.split("\n")
        assert event_line.startswith("event: ")
        assert data_line.startswith("data: ")
        frames.append(
            (event_line.removeprefix("event: "), json.loads(data_line[len("data: ") :]))
        )
    return frames


def _types(text: str) -> list[str]:
    return [event for event, _ in _frames(text)]


async def _records(session: AsyncSession) -> list[ResponseRecord]:
    return list((await session.execute(select(ResponseRecord))).scalars())


async def _wait_for_record(session: AsyncSession) -> ResponseRecord:
    for _ in range(50):
        records = await _records(session)
        if records:
            return records[0]
        await asyncio.sleep(0.05)
    raise AssertionError("no record was written")


async def _content(session: AsyncSession, record: ResponseRecord) -> ResponseContent:
    return (
        await session.execute(
            select(ResponseContent).where(ResponseContent.record_id == record.id)
        )
    ).scalar_one()


async def test_text_stream_wire_format_order_and_record(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    session: AsyncSession,
    validate_schema: Schema,
) -> None:
    ollama_mock.handler = lambda _: ndjson(stream_lines(["Hel", "lo"]))

    response = await client.post("/v1/responses", json=STREAM)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "[DONE]" not in response.text
    frames = _frames(response.text)
    for event, payload in frames:
        validate_schema(payload, "ResponseStreamEvent")
        assert payload["type"] == event
    assert [payload["sequence_number"] for _, payload in frames] == list(
        range(len(frames))
    )
    assert _types(response.text) == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.completed",
    ]
    assert frames[0][1]["response"]["status"] == "in_progress"
    assert frames[0][1]["response"]["output"] == []
    assert [p["delta"] for e, p in frames if e == "response.output_text.delta"] == [
        "Hel",
        "lo",
    ]
    completed = frames[-1][1]["response"]
    assert completed["status"] == "completed"
    assert completed["output"][0]["content"][0]["text"] == "Hello"
    assert completed["usage"]["input_tokens"] == 5
    assert completed["usage"]["total_tokens"] == 8
    [record] = await _records(session)
    assert record.external_id == completed["id"]
    assert record.status == RequestStatus.SUCCEEDED
    assert record.stream is True
    assert record.time_to_first_token_ms is not None
    assert (record.prompt_tokens, record.completion_tokens) == (5, 3)
    content = await _content(session, record)
    assert content.response is not None
    assert content.response["output"][0]["content"][0]["text"] == "Hello"


async def test_function_call_events(
    client: AsyncClient, ollama_mock: OllamaMock, validate_schema: Schema
) -> None:
    lines = stream_lines([])
    lines.insert(
        0,
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "f", "arguments": {"x": 1}}}],
            },
            "done": False,
        },
    )
    ollama_mock.handler = lambda _: ndjson(lines)

    response = await client.post("/v1/responses", json={**STREAM, "tools": [TOOL]})

    frames = _frames(response.text)
    for _, payload in frames:
        validate_schema(payload, "ResponseStreamEvent")
    assert _types(response.text) == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.completed",
    ]
    delta = next(p for e, p in frames if e.endswith("arguments.delta"))
    assert json.loads(delta["delta"]) == {"x": 1}
    output = frames[-1][1]["response"]["output"]
    assert [item["type"] for item in output] == ["function_call"]


async def test_empty_reply_still_has_a_message_item(
    client: AsyncClient, ollama_mock: OllamaMock, validate_schema: Schema
) -> None:
    ollama_mock.handler = lambda _: ndjson(stream_lines([]))

    response = await client.post("/v1/responses", json=STREAM)

    for _, payload in _frames(response.text):
        validate_schema(payload, "ResponseStreamEvent")
    assert "response.output_item.added" in _types(response.text)
    assert _frames(response.text)[-1][1]["response"]["output"][0]["type"] == "message"


async def test_length_finish_ends_with_incomplete_event(
    client: AsyncClient, ollama_mock: OllamaMock, validate_schema: Schema
) -> None:
    ollama_mock.handler = lambda _: ndjson(stream_lines(["a"], done_reason="length"))

    response = await client.post("/v1/responses", json=STREAM)

    frames = _frames(response.text)
    for _, payload in frames:
        validate_schema(payload, "ResponseStreamEvent")
    event, payload = frames[-1]
    assert event == "response.incomplete"
    assert payload["response"]["status"] == "incomplete"
    assert payload["response"]["incomplete_details"] == {"reason": "max_output_tokens"}
    assert payload["response"]["usage"] is not None


async def test_mid_stream_error_becomes_response_failed(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    session: AsyncSession,
    validate_schema: Schema,
) -> None:
    lines = [*stream_lines(["Hel"])[:-1], {"error": "model crashed"}]
    ollama_mock.handler = lambda _: ndjson(lines)

    response = await client.post("/v1/responses", json=STREAM)

    assert response.status_code == 200
    frames = _frames(response.text)
    for _, payload in frames:
        validate_schema(payload, "ResponseStreamEvent")
    event, payload = frames[-1]
    assert event == "response.failed"
    assert payload["response"]["status"] == "failed"
    assert payload["response"]["error"]["code"] == "server_error"
    assert "model crashed" in payload["response"]["error"]["message"]
    [record] = await _records(session)
    assert record.status == RequestStatus.FAILED
    assert record.error_type == "server_error"
    content = await _content(session, record)
    assert content.error_message is not None
    assert "model crashed" in content.error_message
    assert content.response is not None
    assert content.response["status"] == "failed"


async def test_errors_before_first_event_are_http_errors(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    ollama_mock.handler = lambda _: Response(500, json={"error": "boom"})

    response = await client.post("/v1/responses", json=STREAM)

    assert response.status_code == 500
    assert response.json()["error"]["type"] == "server_error"


async def _asgi_post(
    app: FastAPI,
    body: dict[str, Any],
    disconnect: asyncio.Event,
    sent: list[dict[str, Any]],
) -> None:
    payload = json.dumps(body).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/responses",
        "raw_path": b"/v1/responses",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
        ],
        "client": ("test", 1),
        "server": ("test", 80),
    }
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)  # type: ignore[arg-type]


async def _wait_until(condition: Callable[[], bool]) -> None:
    for _ in range(100):
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met")


async def test_client_disconnect_records_cancelled_with_partial_content(
    test_app: FastAPI,
    ollama_mock: OllamaMock,
    session: AsyncSession,
) -> None:
    closed: list[bool] = []
    ollama_mock.handler = lambda _: Response(
        200, content=hanging_stream(stream_lines(["Hel"])[:-1], closed)
    )
    disconnect = asyncio.Event()
    sent: list[dict[str, Any]] = []
    task = asyncio.create_task(_asgi_post(test_app, STREAM, disconnect, sent))
    await _wait_until(lambda: any(b"Hel" in m.get("body", b"") for m in sent))

    disconnect.set()
    await asyncio.wait_for(task, 1)

    record = await _wait_for_record(session)
    assert record.status == RequestStatus.CANCELLED
    assert closed == [True]
    content = await _content(session, record)
    assert content.response is not None
    assert content.response["status"] == "cancelled"
    assert content.response["output"][0]["content"][0]["text"] == "Hel"


async def test_disconnect_before_first_event_is_cancelled_with_null_tokens(
    test_app: FastAPI, ollama_mock: OllamaMock, session: AsyncSession
) -> None:
    closed: list[bool] = []
    ollama_mock.handler = lambda _: Response(200, content=hanging_stream([], closed))
    disconnect = asyncio.Event()
    task = asyncio.create_task(_asgi_post(test_app, STREAM, disconnect, []))
    await _wait_until(lambda: bool(ollama_mock.requests))
    await asyncio.sleep(0.1)

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    record = await _wait_for_record(session)
    assert record.status == RequestStatus.CANCELLED
    assert (record.prompt_tokens, record.completion_tokens) == (None, None)
