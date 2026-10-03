from collections.abc import AsyncIterator

import httpx
import pytest
from llm.client import OllamaClient, OllamaModelNotFoundError
from llm.config import OllamaSettings
from llm.schemas import OllamaChatRequest, OllamaMessage

pytestmark = pytest.mark.integration

MODEL = "qwen3.5:9b"
NUM_CTX = 2048


def _request(
    content: str, *, options: dict[str, object] | None = None
) -> OllamaChatRequest:
    return OllamaChatRequest(
        model=MODEL,
        messages=[OllamaMessage(role="user", content=content)],
        think=False,
        options={"num_predict": 3, **(options or {})},
    )


def _words(count: int) -> str:
    return " ".join(f"w{i}" for i in range(count))


@pytest.fixture
async def ollama() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


async def test_non_stream_call(ollama: httpx.AsyncClient) -> None:
    client = OllamaClient(ollama, OllamaSettings())

    response = await client.chat(_request("Say hi", options={"num_predict": 50}))

    assert response.done
    assert response.message is not None
    assert response.message.content
    assert response.eval_count
    assert response.prompt_eval_count
    assert response.total_duration


async def test_stream_call(ollama: httpx.AsyncClient) -> None:
    client = OllamaClient(ollama, OllamaSettings())

    chunks = [
        c
        async for c in client.chat_stream(
            _request("Say hi", options={"num_predict": 50})
        )
    ]

    assert chunks[-1].done
    assert chunks[-1].eval_count
    assert chunks[-1].prompt_eval_count
    assert any(c.message and c.message.content for c in chunks)


async def test_penalty_options_are_accepted(ollama: httpx.AsyncClient) -> None:
    client = OllamaClient(ollama, OllamaSettings())

    response = await client.chat(
        _request("Say hi", options={"frequency_penalty": 0.5, "presence_penalty": 0.5})
    )

    assert response.done


async def test_tiny_num_predict_reports_length(ollama: httpx.AsyncClient) -> None:
    client = OllamaClient(ollama, OllamaSettings())

    response = await client.chat(
        _request("Count to one hundred", options={"num_predict": 3})
    )

    assert response.done_reason == "length"


async def test_unknown_model_error(ollama: httpx.AsyncClient) -> None:
    client = OllamaClient(ollama, OllamaSettings())
    request = _request("hi").model_copy(update={"model": "nope:1b"})

    with pytest.raises(OllamaModelNotFoundError, match="not found"):
        await client.chat(request)

    raw = await ollama.post(
        "http://localhost:11434/api/chat",
        json={"model": "nope:1b", "messages": [], "stream": False},
    )
    assert raw.status_code == 404
    assert raw.json() == {"error": "model 'nope:1b' not found"}


async def test_context_overflow_truncates_silently(ollama: httpx.AsyncClient) -> None:
    # Ollama does not error on overflow: it truncates the prompt and reports
    # prompt_eval_count == num_ctx // 2 + 2, so a count >= num_ctx never occurs
    client = OllamaClient(ollama, OllamaSettings())
    request = _request(_words(1500), options={"num_ctx": NUM_CTX})

    first = await client.chat(request)
    second = await client.chat(request)

    assert first.prompt_eval_count == NUM_CTX // 2 + 2
    assert second.prompt_eval_count == NUM_CTX // 2 + 2


async def test_prompt_below_context_is_not_truncated(
    ollama: httpx.AsyncClient,
) -> None:
    client = OllamaClient(ollama, OllamaSettings())
    request = _request(_words(500), options={"num_ctx": NUM_CTX})

    first = await client.chat(request)
    second = await client.chat(request)

    assert first.prompt_eval_count is not None
    assert first.prompt_eval_count != NUM_CTX // 2 + 2
    # KV-cache reuse does not lower the reported count
    assert second.prompt_eval_count == first.prompt_eval_count
