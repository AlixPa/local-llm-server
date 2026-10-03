import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
from llm.client import (
    OllamaClient,
    OllamaModelNotFoundError,
    OllamaServerError,
    OllamaUnreachableError,
)
from llm.config import OllamaSettings
from llm.schemas import OllamaChatRequest, OllamaMessage

REQUEST = OllamaChatRequest(
    model="qwen3.5:9b", messages=[OllamaMessage(role="user", content="hi")]
)

FINAL = {
    "model": "qwen3.5:9b",
    "message": {"role": "assistant", "content": ""},
    "done": True,
    "done_reason": "stop",
    "total_duration": 3_000_000_000,
    "load_duration": 1_000_000_000,
    "prompt_eval_count": 5,
    "prompt_eval_duration": 500_000_000,
    "eval_count": 7,
    "eval_duration": 1_500_000_000,
}


def _client(handler: httpx.MockTransport) -> OllamaClient:
    return OllamaClient(httpx.AsyncClient(transport=handler), OllamaSettings())


async def test_chat_parses_response_with_timings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is False
        assert body["model"] == "qwen3.5:9b"
        assert request.url.path == "/api/chat"
        return httpx.Response(
            200, json={**FINAL, "message": {"role": "assistant", "content": "hello"}}
        )

    response = await _client(httpx.MockTransport(handler)).chat(REQUEST)

    assert response.message is not None
    assert response.message.content == "hello"
    assert response.done_reason == "stop"
    assert response.load_duration == 1_000_000_000
    assert response.eval_duration == 1_500_000_000
    assert (response.prompt_eval_count, response.eval_count) == (5, 7)


async def test_chat_stream_parses_ndjson() -> None:
    lines = [
        {"message": {"role": "assistant", "content": "he"}, "done": False},
        {"message": {"role": "assistant", "content": "llo"}, "done": False},
        FINAL,
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200, content="".join(json.dumps(line) + "\n" for line in lines).encode()
        )

    chunks = [
        c async for c in _client(httpx.MockTransport(handler)).chat_stream(REQUEST)
    ]

    assert [c.message.content for c in chunks if c.message] == ["he", "llo", ""]
    assert [c.done for c in chunks] == [False, False, True]
    assert chunks[-1].eval_count == 7


async def test_unknown_model_maps_to_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'x' not found"})

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(OllamaModelNotFoundError, match="not found"):
        await client.chat(REQUEST)
    with pytest.raises(OllamaModelNotFoundError):
        [c async for c in client.chat_stream(REQUEST)]


async def test_server_error_maps_to_server_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(OllamaServerError, match="boom"):
        await _client(httpx.MockTransport(handler)).chat(REQUEST)


async def test_mid_stream_error_body_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        first = json.dumps({"message": {"role": "assistant", "content": "a"}})
        return httpx.Response(
            200, content=f'{first}\n{{"error": "out of memory"}}\n'.encode()
        )

    client = _client(httpx.MockTransport(handler))
    received = []
    with pytest.raises(OllamaServerError, match="out of memory"):
        async for chunk in client.chat_stream(REQUEST):
            received.append(chunk)
    assert len(received) == 1


async def test_connect_error_maps_to_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(OllamaUnreachableError):
        await client.chat(REQUEST)
    with pytest.raises(OllamaUnreachableError):
        [c async for c in client.chat_stream(REQUEST)]


class _TrackedStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for text in ("a", "b", "c"):
            line = json.dumps({"message": {"role": "assistant", "content": text}})
            yield f"{line}\n".encode()
            await asyncio.sleep(0)

    async def aclose(self) -> None:
        self.closed = True


async def test_early_close_closes_upstream_response() -> None:
    stream = _TrackedStream()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    chunks = _client(httpx.MockTransport(handler)).chat_stream(REQUEST)
    first = await anext(chunks)
    assert first.message is not None
    assert not stream.closed

    await chunks.aclose()

    assert stream.closed


async def test_no_read_timeout() -> None:
    seen: dict[str, httpx.Timeout] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = httpx.Timeout(**request.extensions["timeout"])
        return httpx.Response(200, json=FINAL)

    await _client(httpx.MockTransport(handler)).chat(REQUEST)

    assert seen["timeout"].read is None
    assert seen["timeout"].connect == 5.0


async def test_slow_response_beyond_default_timeout_succeeds() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5.3)
        return httpx.Response(200, json=FINAL)

    response = await _client(httpx.MockTransport(handler)).chat(REQUEST)

    assert response.done
