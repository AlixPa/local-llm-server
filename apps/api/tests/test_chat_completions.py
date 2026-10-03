import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from db.models import ChatCompletionContent, ChatCompletionRecord, ChatCompletionStatus
from httpx import AsyncClient, Request, Response
from ollama_fakes import OllamaMock, chat_response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MODEL = "qwen3.5:9b"
MINIMAL = {"model": MODEL, "messages": [{"role": "user", "content": "Hi"}]}

type Contract = Callable[[Response], None]


async def _records(session: AsyncSession) -> list[ChatCompletionRecord]:
    result = await session.execute(select(ChatCompletionRecord))
    return list(result.scalars())


async def _content(session: AsyncSession, record_id: int) -> ChatCompletionContent:
    result = await session.execute(
        select(ChatCompletionContent).where(
            ChatCompletionContent.record_id == record_id
        )
    )
    return result.scalar_one()


def _sent(ollama_mock: OllamaMock, index: int = 0) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(ollama_mock.requests[index].content)
    return body


async def test_minimal_success(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    session: AsyncSession,
    validate_contract: Contract,
) -> None:
    ollama_mock.handler = lambda _: chat_response("Hello there")

    response = await client.post("/v1/chat/completions", json=MINIMAL)

    validate_contract(response)
    body = response.json()
    assert body["id"].startswith("chatcmpl-")
    assert body["model"] == MODEL
    message = body["choices"][0]["message"]
    assert (message["role"], message["content"]) == ("assistant", "Hello there")
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 3,
        "total_tokens": 8,
    }
    sent = _sent(ollama_mock)
    assert sent["stream"] is False
    assert sent["think"] is False
    assert sent["options"]["num_ctx"] == 32768
    [record] = await _records(session)
    assert record.external_id == body["id"]
    assert record.status == ChatCompletionStatus.SUCCEEDED
    assert (record.prompt_tokens, record.completion_tokens) == (5, 3)
    assert record.generation_duration_ms == 2000
    assert record.load_duration_ms == 1000
    assert record.finish_reason == "stop"
    content = await _content(session, record.id)
    assert content.request["messages"][0]["content"] == "Hi"
    assert content.response is not None
    assert content.response["choices"][0]["message"]["content"] == "Hello there"


async def test_served_model_and_unknown_fields_are_accepted(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    ollama_mock.handler = lambda _: chat_response()

    response = await client.post(
        "/v1/chat/completions", json={**MINIMAL, "something_new": {"a": 1}}
    )

    assert response.status_code == 200


async def test_tool_calls_response(
    client: AsyncClient, ollama_mock: OllamaMock, validate_contract: Contract
) -> None:
    ollama_mock.handler = lambda _: chat_response(
        "",
        tool_calls=[
            {"function": {"name": "get_weather", "arguments": {"city": "Paris"}}}
        ],
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Weather",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    response = await client.post(
        "/v1/chat/completions", json={**MINIMAL, "tools": tools}
    )

    validate_contract(response)
    choice = response.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    [call] = choice["message"]["tool_calls"]
    assert call["id"].startswith("call_")
    assert call["function"] == {
        "name": "get_weather",
        "arguments": json.dumps({"city": "Paris"}),
    }
    assert _sent(ollama_mock)["tools"] == tools


async def test_response_format_and_logprobs_success(
    client: AsyncClient, ollama_mock: OllamaMock, validate_contract: Contract
) -> None:
    ollama_mock.handler = lambda _: chat_response(
        '{"a": 1}',
        logprobs=[
            {
                "token": "{",
                "logprob": -0.1,
                "bytes": [123],
                "top_logprobs": [{"token": "{", "logprob": -0.1, "bytes": [123]}],
            }
        ],
    )

    response = await client.post(
        "/v1/chat/completions",
        json={
            **MINIMAL,
            "response_format": {"type": "json_object"},
            "logprobs": True,
            "top_logprobs": 1,
        },
    )

    validate_contract(response)
    logprobs = response.json()["choices"][0]["logprobs"]
    assert logprobs["content"][0]["token"] == "{"
    assert logprobs["content"][0]["top_logprobs"][0]["logprob"] == -0.1
    sent = _sent(ollama_mock)
    assert sent["format"] == "json"
    assert sent["logprobs"] is True
    assert sent["top_logprobs"] == 1


async def test_n_sums_usage(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    session: AsyncSession,
    validate_contract: Contract,
) -> None:
    ollama_mock.handler = lambda _: chat_response(prompt=4, completion=2)

    response = await client.post("/v1/chat/completions", json={**MINIMAL, "n": 2})

    validate_contract(response)
    body = response.json()
    assert [c["index"] for c in body["choices"]] == [0, 1]
    assert body["usage"] == {
        "prompt_tokens": 8,
        "completion_tokens": 4,
        "total_tokens": 12,
    }
    assert len(ollama_mock.requests) == 2
    [record] = await _records(session)
    assert (record.n, record.prompt_tokens, record.completion_tokens) == (2, 8, 4)
    assert record.generation_duration_ms == 4000


async def test_length_finish_reason(
    client: AsyncClient, ollama_mock: OllamaMock, validate_contract: Contract
) -> None:
    ollama_mock.handler = lambda _: chat_response(done_reason="length")

    response = await client.post("/v1/chat/completions", json=MINIMAL)

    validate_contract(response)
    assert response.json()["choices"][0]["finish_reason"] == "length"


async def test_unsupported_option_is_rejected_and_recorded(
    client: AsyncClient,
    session: AsyncSession,
    validate_contract: Contract,
) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json={**MINIMAL, "audio": {"voice": "alloy", "format": "mp3"}},
    )

    validate_contract(response)
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["type"] == "invalid_request_error"
    assert error["code"] == "unsupported_parameter"
    assert error["param"] == "audio"
    [record] = await _records(session)
    assert record.status == ChatCompletionStatus.FAILED
    assert record.error_code == "unsupported_parameter"
    assert record.prompt_tokens is None


async def test_context_overflow(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    session: AsyncSession,
    validate_contract: Contract,
) -> None:
    ollama_mock.handler = lambda _: chat_response(prompt=32768 // 2 + 2)

    response = await client.post("/v1/chat/completions", json=MINIMAL)

    validate_contract(response)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "context_length_exceeded"
    [record] = await _records(session)
    assert record.status == ChatCompletionStatus.FAILED
    assert record.prompt_tokens == 32768 // 2 + 2


async def test_prompt_just_below_overflow_count_succeeds(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    ollama_mock.handler = lambda _: chat_response(prompt=32768 // 2 + 1)

    response = await client.post("/v1/chat/completions", json=MINIMAL)

    assert response.status_code == 200


async def test_unknown_model(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    session: AsyncSession,
    validate_contract: Contract,
) -> None:
    response = await client.post(
        "/v1/chat/completions", json={**MINIMAL, "model": "gpt-4o"}
    )

    validate_contract(response)
    assert response.status_code == 404
    assert response.json()["error"] == {
        "message": "The model `gpt-4o` does not exist or you do not have access to it.",
        "type": "invalid_request_error",
        "param": None,
        "code": "model_not_found",
    }
    assert ollama_mock.requests == []
    [record] = await _records(session)
    assert record.model == "gpt-4o"
    assert record.status == ChatCompletionStatus.FAILED


async def test_model_missing_in_ollama(
    client: AsyncClient, ollama_mock: OllamaMock, validate_contract: Contract
) -> None:
    ollama_mock.handler = lambda _: Response(
        404, json={"error": f"model '{MODEL}' not found"}
    )

    response = await client.post("/v1/chat/completions", json=MINIMAL)

    validate_contract(response)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_found"
    assert MODEL in response.json()["error"]["message"]


async def test_ollama_unreachable(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    session: AsyncSession,
    validate_contract: Contract,
) -> None:
    def refuse(request: Request) -> Response:
        raise httpx.ConnectError("refused", request=request)

    ollama_mock.handler = refuse

    response = await client.post("/v1/chat/completions", json=MINIMAL)

    validate_contract(response)
    assert response.status_code == 503
    error = response.json()["error"]
    assert (error["type"], error["code"]) == ("server_error", None)
    [record] = await _records(session)
    assert record.status == ChatCompletionStatus.FAILED
    assert record.error_type == "server_error"


async def test_ollama_server_error(
    client: AsyncClient, ollama_mock: OllamaMock, validate_contract: Contract
) -> None:
    ollama_mock.handler = lambda _: Response(500, json={"error": "boom"})

    response = await client.post("/v1/chat/completions", json=MINIMAL)

    validate_contract(response)
    assert response.status_code == 500
    assert response.json()["error"]["type"] == "server_error"


@pytest.mark.parametrize(
    "body",
    [
        {"model": MODEL},
        {"model": MODEL, "messages": []},
        {**MINIMAL, "n": 0},
        {**MINIMAL, "temperature": 5},
    ],
)
async def test_schema_validation_failure_is_not_recorded(
    client: AsyncClient,
    session: AsyncSession,
    validate_contract: Contract,
    body: dict[str, Any],
) -> None:
    response = await client.post("/v1/chat/completions", json=body)

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert await _records(session) == []
