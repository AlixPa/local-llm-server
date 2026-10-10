import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from db.models import RequestStatus, ResponseContent, ResponseRecord
from fastapi import FastAPI
from httpx import AsyncClient, Request, Response
from ollama_fakes import OllamaMock, chat_response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MODEL = "qwen3.5:9b"
MINIMAL = {"model": MODEL, "input": "Say hi"}
PIXEL = "data:image/png;base64,iVBORw0KGgo="
WEATHER = {
    "type": "function",
    "name": "get_weather",
    "description": "Weather",
    "parameters": {"type": "object", "properties": {}},
    "strict": False,
}

type Contract = Callable[[Response], None]


async def _records(session: AsyncSession) -> list[ResponseRecord]:
    return list((await session.execute(select(ResponseRecord))).scalars())


async def _content(session: AsyncSession, record: ResponseRecord) -> ResponseContent:
    return (
        await session.execute(
            select(ResponseContent).where(ResponseContent.record_id == record.id)
        )
    ).scalar_one()


def _sent(ollama_mock: OllamaMock) -> dict[str, Any]:
    sent: dict[str, Any] = json.loads(ollama_mock.requests[-1].content)
    return sent


async def test_string_input_success(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    session: AsyncSession,
    validate_contract: Contract,
) -> None:
    ollama_mock.handler = lambda _: chat_response("Hi there", prompt=7, completion=4)

    response = await client.post("/v1/responses", json=MINIMAL)

    validate_contract(response)
    assert response.status_code == 200
    body = response.json()
    assert re.fullmatch(r"resp_[0-9a-f]{24}", body["id"])
    assert body["status"] == "completed"
    assert body["incomplete_details"] is None
    assert body["error"] is None
    [message] = body["output"]
    assert message["type"] == "message"
    assert message["content"][0]["text"] == "Hi there"
    assert body["usage"] == {
        "input_tokens": 7,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": 4,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 11,
    }
    sent = _sent(ollama_mock)
    assert sent["messages"] == [{"role": "user", "content": "Say hi"}]
    assert sent["think"] is False
    [record] = await _records(session)
    assert record.external_id == body["id"]
    assert record.status == RequestStatus.SUCCEEDED
    assert record.stream is False
    assert (record.prompt_tokens, record.completion_tokens) == (7, 4)
    assert record.finish_reason == "stop"
    content = await _content(session, record)
    assert content.request["input"] == "Say hi"
    assert content.response is not None
    assert content.response["id"] == body["id"]


async def test_message_list_images_and_instructions(
    client: AsyncClient, ollama_mock: OllamaMock, validate_contract: Contract
) -> None:
    ollama_mock.handler = lambda _: chat_response()

    response = await client.post(
        "/v1/responses",
        json={
            "model": MODEL,
            "instructions": "Be brief.",
            "input": [
                {"role": "developer", "content": "Rules"},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "What is this?"},
                        {
                            "type": "input_image",
                            "image_url": PIXEL,
                            "detail": "auto",
                        },
                    ],
                },
            ],
        },
    )

    validate_contract(response)
    assert response.status_code == 200
    assert _sent(ollama_mock)["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "system", "content": "Rules"},
        {
            "role": "user",
            "content": "What is this?",
            "images": [PIXEL.split(",")[1]],
        },
    ]
    assert response.json()["instructions"] == "Be brief."


async def test_function_call_round_trip(
    client: AsyncClient, ollama_mock: OllamaMock, validate_contract: Contract
) -> None:
    ollama_mock.handler = lambda _: chat_response(
        "Checking",
        tool_calls=[{"function": {"name": "get_weather", "arguments": {"c": "Paris"}}}],
    )

    response = await client.post("/v1/responses", json={**MINIMAL, "tools": [WEATHER]})

    validate_contract(response)
    body = response.json()
    message, call = body["output"]
    assert message["type"] == "message"
    assert call["type"] == "function_call"
    assert call["id"].startswith("fc_")
    assert call["call_id"].startswith("call_")
    assert json.loads(call["arguments"]) == {"c": "Paris"}
    sent_tools = _sent(ollama_mock)["tools"]
    assert sent_tools[0]["function"]["name"] == "get_weather"

    ollama_mock.handler = lambda _: chat_response("Sunny")
    follow_up = await client.post(
        "/v1/responses",
        json={
            "model": MODEL,
            "tools": [WEATHER],
            "input": [
                {"role": "user", "content": "Weather?"},
                {
                    "type": "function_call",
                    "call_id": call["call_id"],
                    "name": call["name"],
                    "arguments": call["arguments"],
                },
                {
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": "20C",
                },
            ],
        },
    )

    validate_contract(follow_up)
    messages = _sent(ollama_mock)["messages"]
    assert messages[1]["role"] == "assistant"
    assert messages[1]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert messages[2] == {"role": "tool", "content": "20C", "tool_name": "get_weather"}


async def test_tool_call_without_text_has_no_message_item(
    client: AsyncClient, ollama_mock: OllamaMock, validate_contract: Contract
) -> None:
    ollama_mock.handler = lambda _: chat_response(
        "", tool_calls=[{"function": {"name": "get_weather", "arguments": {}}}]
    )

    response = await client.post("/v1/responses", json={**MINIMAL, "tools": [WEATHER]})

    validate_contract(response)
    assert [item["type"] for item in response.json()["output"]] == ["function_call"]


async def test_max_output_tokens_is_incomplete(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    session: AsyncSession,
    validate_contract: Contract,
) -> None:
    ollama_mock.handler = lambda _: chat_response("Cut", done_reason="length")

    response = await client.post(
        "/v1/responses", json={**MINIMAL, "max_output_tokens": 16}
    )

    validate_contract(response)
    body = response.json()
    assert body["status"] == "incomplete"
    assert body["incomplete_details"] == {"reason": "max_output_tokens"}
    assert _sent(ollama_mock)["options"]["num_predict"] == 16
    [record] = await _records(session)
    assert record.status == RequestStatus.SUCCEEDED
    assert record.finish_reason == "length"


async def test_unsupported_parameter(
    client: AsyncClient,
    session: AsyncSession,
    validate_contract: Contract,
) -> None:
    response = await client.post(
        "/v1/responses", json={**MINIMAL, "previous_response_id": "resp_abc"}
    )

    validate_contract(response)
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["type"] == "invalid_request_error"
    assert error["code"] == "unsupported_parameter"
    assert error["param"] == "previous_response_id"
    [record] = await _records(session)
    assert record.status == RequestStatus.FAILED
    assert record.error_code == "unsupported_parameter"
    assert record.prompt_tokens is None


async def test_unknown_model(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    session: AsyncSession,
    validate_contract: Contract,
) -> None:
    response = await client.post("/v1/responses", json={**MINIMAL, "model": "gpt-4o"})

    validate_contract(response)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_found"
    assert ollama_mock.requests == []
    [record] = await _records(session)
    assert record.model == "gpt-4o"
    assert record.status == RequestStatus.FAILED


async def test_ollama_unreachable(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    session: AsyncSession,
    validate_contract: Contract,
) -> None:
    def refuse(request: Request) -> Response:
        raise httpx.ConnectError("refused", request=request)

    ollama_mock.handler = refuse

    response = await client.post("/v1/responses", json=MINIMAL)

    validate_contract(response)
    assert response.status_code == 503
    error = response.json()["error"]
    assert (error["type"], error["code"]) == ("server_error", None)
    [record] = await _records(session)
    assert record.status == RequestStatus.FAILED


async def test_ollama_server_error(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    validate_schema: Callable[[Any, str], None],
) -> None:
    ollama_mock.handler = lambda _: Response(500, json={"error": "boom"})

    response = await client.post("/v1/responses", json=MINIMAL)

    # The spec documents no 500 for this operation, only the shared envelope
    validate_schema(response.json(), "ErrorResponse")
    assert response.status_code == 500
    assert response.json()["error"]["type"] == "server_error"


async def test_context_overflow(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    session: AsyncSession,
    validate_contract: Contract,
) -> None:
    ollama_mock.handler = lambda _: chat_response(prompt=32768 // 2 + 2)

    response = await client.post(
        "/v1/responses", json={**MINIMAL, "truncation": "disabled"}
    )

    validate_contract(response)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "context_length_exceeded"
    [record] = await _records(session)
    assert record.status == RequestStatus.FAILED
    assert record.prompt_tokens == 32768 // 2 + 2


@pytest.mark.parametrize(
    "body",
    [
        {"model": MODEL, "temperature": 5},
        {"model": MODEL, "max_output_tokens": 1},
        {"model": MODEL, "input": 5},
        {"model": MODEL, "include": ["nope"]},
    ],
)
async def test_schema_validation_failure_is_not_recorded(
    client: AsyncClient, session: AsyncSession, body: dict[str, Any]
) -> None:
    response = await client.post("/v1/responses", json=body)

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert await _records(session) == []


async def test_missing_model(client: AsyncClient) -> None:
    response = await client.post("/v1/responses", json={"input": "hi"})

    assert response.status_code == 400
    assert response.json()["error"]["param"] == "model"


async def test_other_responses_routes_use_standard_errors(
    client: AsyncClient, validate_schema: Callable[[Any, str], None]
) -> None:
    response = await client.get("/v1/responses/resp_x")

    assert response.status_code == 404
    validate_schema(response.json(), "ErrorResponse")
    assert response.json()["error"]["code"] == "not_found"


async def test_non_stream_disconnect_records_cancelled(
    test_app: FastAPI, ollama_mock: OllamaMock, session: AsyncSession
) -> None:
    async def hang(_: Request) -> Response:
        await asyncio.sleep(3600)
        raise AssertionError

    ollama_mock.handler = hang
    payload = json.dumps(MINIMAL).encode()
    disconnect = asyncio.Event()
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        return None

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
    task = asyncio.create_task(test_app(scope, receive, send))  # type: ignore[arg-type]
    for _ in range(100):
        if ollama_mock.requests:
            break
        await asyncio.sleep(0.02)

    disconnect.set()
    await asyncio.wait_for(task, 1)

    [record] = await _records(session)
    assert record.status == RequestStatus.CANCELLED
    assert record.prompt_tokens is None
