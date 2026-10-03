from collections.abc import AsyncIterator

import httpx
import httpx2
import pytest
from api.dependencies import get_ollama_client
from fastapi import FastAPI
from llm.client import OllamaClient
from llm.config import OllamaSettings
from openai import AsyncOpenAI, NotFoundError
from openai.types.chat import ChatCompletionUserMessageParam

pytestmark = pytest.mark.integration

MODEL = "qwen3.5:9b"
MESSAGES: list[ChatCompletionUserMessageParam] = [
    {"role": "user", "content": "Reply with one short word."}
]


@pytest.fixture
async def sdk(test_app: FastAPI) -> AsyncIterator[AsyncOpenAI]:
    async with httpx.AsyncClient() as ollama_http:
        ollama = OllamaClient(ollama_http, OllamaSettings())
        test_app.dependency_overrides[get_ollama_client] = lambda: ollama
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=test_app), base_url="http://test/v1"
        ) as http_client:
            yield AsyncOpenAI(
                base_url="http://test/v1", api_key="unused", http_client=http_client
            )


async def test_models_list(sdk: AsyncOpenAI) -> None:
    models = await sdk.models.list()

    assert [m.id for m in models.data] == [MODEL]


async def test_non_streaming(sdk: AsyncOpenAI) -> None:
    completion = await sdk.chat.completions.create(
        model=MODEL, messages=MESSAGES, max_tokens=50
    )

    assert completion.choices[0].message.content
    assert completion.usage is not None
    assert completion.usage.total_tokens > 0


async def test_streaming(sdk: AsyncOpenAI) -> None:
    stream = await sdk.chat.completions.create(
        model=MODEL,
        messages=MESSAGES,
        max_tokens=50,
        stream=True,
        stream_options={"include_usage": True},
    )

    chunks = [chunk async for chunk in stream]

    text = "".join(c.choices[0].delta.content or "" for c in chunks if c.choices)
    assert text
    assert chunks[-1].usage is not None


async def test_unknown_model_raises_not_found(sdk: AsyncOpenAI) -> None:
    with pytest.raises(NotFoundError):
        await sdk.chat.completions.create(model="gpt-4o", messages=MESSAGES)
