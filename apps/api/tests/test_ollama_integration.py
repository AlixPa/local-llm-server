import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from api.dependencies import get_ollama_client
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from llm.client import OllamaClient
from llm.config import OllamaSettings

pytestmark = pytest.mark.integration

MODEL = "qwen3.5:9b"
NUM_CTX = 2048
BASE: dict[str, Any] = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "Reply with one short word."}],
    "max_tokens": 50,
}


@pytest.fixture
async def live_client(test_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with httpx.AsyncClient() as ollama_http:
        ollama = OllamaClient(ollama_http, OllamaSettings(num_ctx=NUM_CTX))
        test_app.dependency_overrides[get_ollama_client] = lambda: ollama
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            yield client


async def test_non_stream_sanity(
    live_client: AsyncClient, validate_contract: Any
) -> None:
    response = await live_client.post("/v1/chat/completions", json=BASE)

    validate_contract(response)
    body = response.json()
    assert body["choices"][0]["message"]["content"]
    assert body["usage"]["completion_tokens"] > 0


async def test_stream_sanity(live_client: AsyncClient, validate_schema: Any) -> None:
    response = await live_client.post(
        "/v1/chat/completions",
        json={**BASE, "stream": True, "stream_options": {"include_usage": True}},
    )

    assert response.status_code == 200
    events = [e.removeprefix("data: ") for e in response.text.strip().split("\n\n")]
    assert events[-1] == "[DONE]"
    chunks = [json.loads(e) for e in events[:-1]]
    for chunk in chunks:
        validate_schema(chunk, "CreateChatCompletionStreamResponse")
    assert "".join(
        c["choices"][0]["delta"].get("content") or "" for c in chunks if c["choices"]
    )
    assert chunks[-1]["usage"]["completion_tokens"] > 0


async def test_tools(live_client: AsyncClient, validate_contract: Any) -> None:
    response = await live_client.post(
        "/v1/chat/completions",
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": "What is the weather in Paris?"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the weather for a city",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                        },
                    },
                }
            ],
            "tool_choice": "required",
        },
    )

    validate_contract(response)
    choice = response.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "get_weather"


async def test_n_two(live_client: AsyncClient, validate_contract: Any) -> None:
    response = await live_client.post("/v1/chat/completions", json={**BASE, "n": 2})

    validate_contract(response)
    assert len(response.json()["choices"]) == 2


async def test_context_overflow(live_client: AsyncClient) -> None:
    prompt = " ".join(f"w{i}" for i in range(3000))

    response = await live_client.post(
        "/v1/chat/completions",
        json={**BASE, "messages": [{"role": "user", "content": prompt}]},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "context_length_exceeded"
