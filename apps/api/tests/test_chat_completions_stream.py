import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
from api.errors import ErrorResponse
from db.models import ChatCompletionContent, ChatCompletionRecord, ChatCompletionStatus
from fastapi import FastAPI
from httpx import AsyncClient, Request, Response
from ollama_fakes import OllamaMock, hanging_stream, ndjson, stream_lines
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MODEL = "qwen3.5:9b"
STREAM = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "Hi"}],
    "stream": True,
}

type Schema = Callable[[Any, str], None]


def _events(text: str) -> list[str]:
    assert text.endswith("\n\n")
    parts = text[:-2].split("\n\n")
    assert all(part.startswith("data: ") for part in parts)
    return [part.removeprefix("data: ") for part in parts]


def _chunks(text: str) -> list[dict[str, Any]]:
    events = _events(text)
    assert events[-1] == "[DONE]"
    return [json.loads(event) for event in events[:-1]]


async def _records(session: AsyncSession) -> list[ChatCompletionRecord]:
    result = await session.execute(select(ChatCompletionRecord))
    return list(result.scalars())


async def _wait_until(condition: Callable[[], bool]) -> None:
    for _ in range(100):
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met")


async def _wait_for_record(session: AsyncSession) -> ChatCompletionRecord:
    for _ in range(40):
        records = await _records(session)
        if records:
            return records[0]
        await asyncio.sleep(0.05)
    raise AssertionError("no record was written")


async def test_stream_wire_format_and_record(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    session: AsyncSession,
    validate_schema: Schema,
) -> None:
    ollama_mock.handler = lambda _: ndjson(stream_lines(["Hel", "lo"]))

    response = await client.post("/v1/chat/completions", json=STREAM)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    chunks = _chunks(response.text)
    for chunk in chunks:
        validate_schema(chunk, "CreateChatCompletionStreamResponse")
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    text = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks)
    assert text == "Hello"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert all("usage" not in chunk for chunk in chunks)
    assert {chunk["id"] for chunk in chunks} == {chunks[0]["id"]}
    [record] = await _records(session)
    assert record.external_id == chunks[0]["id"]
    assert record.status == ChatCompletionStatus.SUCCEEDED
    assert record.stream is True
    assert record.time_to_first_token_ms is not None
    assert (record.prompt_tokens, record.completion_tokens) == (5, 3)
    content = (
        await session.execute(
            select(ChatCompletionContent).where(
                ChatCompletionContent.record_id == record.id
            )
        )
    ).scalar_one()
    assert content.response is not None
    assert content.response["choices"][0]["message"]["content"] == "Hello"


async def test_usage_chunk_only_when_requested(
    client: AsyncClient, ollama_mock: OllamaMock, validate_schema: Schema
) -> None:
    ollama_mock.handler = lambda _: ndjson(stream_lines(["Hi"]))

    response = await client.post(
        "/v1/chat/completions",
        json={**STREAM, "stream_options": {"include_usage": True}},
    )

    chunks = _chunks(response.text)
    for chunk in chunks:
        validate_schema(chunk, "CreateChatCompletionStreamResponse")
    assert chunks[-1]["choices"] == []
    assert chunks[-1]["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 3,
        "total_tokens": 8,
    }
    assert all("usage" not in chunk for chunk in chunks[:-1])


async def test_n_streams_choices_sequentially(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    session: AsyncSession,
    validate_schema: Schema,
) -> None:
    ollama_mock.handler = lambda _: ndjson(stream_lines(["a"], prompt=4, completion=2))

    response = await client.post(
        "/v1/chat/completions",
        json={**STREAM, "n": 2, "stream_options": {"include_usage": True}},
    )

    chunks = _chunks(response.text)
    for chunk in chunks:
        validate_schema(chunk, "CreateChatCompletionStreamResponse")
    indices = [c["choices"][0]["index"] for c in chunks if c["choices"]]
    assert indices == sorted(indices)
    assert set(indices) == {0, 1}
    assert chunks[-1]["usage"]["total_tokens"] == 12
    assert len(ollama_mock.requests) == 2
    [record] = await _records(session)
    assert record.n == 2


async def test_tool_calls_stream(
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

    response = await client.post("/v1/chat/completions", json=STREAM)

    chunks = _chunks(response.text)
    for chunk in chunks:
        validate_schema(chunk, "CreateChatCompletionStreamResponse")
    [call_chunk] = [c for c in chunks if c["choices"][0]["delta"].get("tool_calls")]
    call = call_chunk["choices"][0]["delta"]["tool_calls"][0]
    assert call["index"] == 0
    assert call["function"] == {"name": "f", "arguments": '{"x": 1}'}
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"


async def test_mid_stream_error_becomes_error_event(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    session: AsyncSession,
    validate_schema: Schema,
) -> None:
    lines = [*stream_lines(["Hel"])[:-1], {"error": "model crashed"}]
    ollama_mock.handler = lambda _: ndjson(lines)

    response = await client.post("/v1/chat/completions", json=STREAM)

    assert response.status_code == 200
    events = _events(response.text)
    assert events[-1] == "[DONE]"
    error = json.loads(events[-2])
    validate_schema(error, "ErrorResponse")
    assert error["error"]["type"] == "server_error"
    assert "model crashed" in error["error"]["message"]
    [record] = await _records(session)
    assert record.status == ChatCompletionStatus.FAILED
    content = (
        await session.execute(
            select(ChatCompletionContent).where(
                ChatCompletionContent.record_id == record.id
            )
        )
    ).scalar_one()
    assert content.error_message is not None


async def test_stream_ending_without_done_is_a_failure(
    client: AsyncClient, ollama_mock: OllamaMock, session: AsyncSession
) -> None:
    ollama_mock.handler = lambda _: ndjson(stream_lines(["Hel"])[:-1])

    response = await client.post("/v1/chat/completions", json=STREAM)

    events = _events(response.text)
    assert events[-1] == "[DONE]"
    assert json.loads(events[-2])["error"]["type"] == "server_error"
    [record] = await _records(session)
    assert record.status == ChatCompletionStatus.FAILED


async def test_unexpected_upstream_error_is_recorded(
    client: AsyncClient, ollama_mock: OllamaMock, session: AsyncSession
) -> None:
    def boom(_: Request) -> Response:
        raise httpx.ReadError("connection reset")

    ollama_mock.handler = boom
    body = {**STREAM, "stream": False}

    response = await client.post("/v1/chat/completions", json=body)

    assert response.status_code == 500
    [record] = await _records(session)
    assert record.status == ChatCompletionStatus.FAILED


async def test_context_overflow_is_an_error_event(
    client: AsyncClient, ollama_mock: OllamaMock, session: AsyncSession
) -> None:
    ollama_mock.handler = lambda _: ndjson(stream_lines(["x"], prompt=32768 // 2 + 2))

    response = await client.post("/v1/chat/completions", json=STREAM)

    assert response.status_code == 200
    events = _events(response.text)
    assert events[-1] == "[DONE]"
    assert json.loads(events[-2])["error"]["code"] == "context_length_exceeded"
    [record] = await _records(session)
    assert record.status == ChatCompletionStatus.FAILED
    assert record.error_code == "context_length_exceeded"


async def test_pre_stream_failures_are_real_http_errors(
    client: AsyncClient, ollama_mock: OllamaMock, session: AsyncSession
) -> None:
    def refuse(request: Request) -> Response:
        raise httpx.ConnectError("refused", request=request)

    cases: list[tuple[dict[str, Any], Callable[[Request], Response] | None, int]] = [
        ({"audio": {"voice": "alloy", "format": "wav"}}, None, 400),
        ({"model": "gpt-4o"}, None, 404),
        ({}, refuse, 503),
        ({}, lambda _: Response(404, json={"error": "model not found"}), 404),
        ({}, lambda _: Response(500, json={"error": "boom"}), 500),
    ]
    for extra, handler, status in cases:
        if handler is not None:
            ollama_mock.handler = handler

        response = await client.post("/v1/chat/completions", json={**STREAM, **extra})

        assert response.status_code == status
        assert response.headers["content-type"].startswith("application/json")
        ErrorResponse.model_validate(response.json())
    records = await _records(session)
    assert len(records) == len(cases)
    assert {r.status for r in records} == {ChatCompletionStatus.FAILED}


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
        "path": "/v1/chat/completions",
        "raw_path": b"/v1/chat/completions",
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


async def test_stream_client_disconnect_cancels_upstream_and_records(
    test_app: FastAPI, ollama_mock: OllamaMock, session: AsyncSession
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
    assert record.status == ChatCompletionStatus.CANCELLED
    assert closed == [True]
    content = (
        await session.execute(
            select(ChatCompletionContent).where(
                ChatCompletionContent.record_id == record.id
            )
        )
    ).scalar_one()
    assert content.response is not None
    assert content.response["choices"][0]["message"]["content"] == "Hel"


async def test_non_stream_disconnect_cancels_every_upstream_call(
    test_app: FastAPI, ollama_mock: OllamaMock, session: AsyncSession
) -> None:
    cancelled: list[bool] = []

    async def hang(_: Request) -> Response:
        try:
            await asyncio.sleep(3600)
        finally:
            cancelled.append(True)
        raise AssertionError

    ollama_mock.handler = hang
    disconnect = asyncio.Event()
    task = asyncio.create_task(
        _asgi_post(test_app, {**STREAM, "stream": False, "n": 3}, disconnect, [])
    )
    await _wait_until(lambda: len(ollama_mock.requests) >= 3)

    disconnect.set()
    await asyncio.wait_for(task, 1)

    assert cancelled == [True, True, True]
    [record] = await _records(session)
    assert record.status == ChatCompletionStatus.CANCELLED
