import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from httpx import Request, Response

type OllamaHandler = Callable[[Request], Response | Awaitable[Response]]


def _unconfigured(request: Request) -> Response:
    raise AssertionError(f"unexpected Ollama call: {request.url}")


@dataclass
class OllamaMock:
    handler: OllamaHandler = field(default=_unconfigured)
    requests: list[Request] = field(default_factory=list[Request])


def chat_body(
    content: str = "Hello",
    *,
    prompt: int = 5,
    completion: int = 3,
    done_reason: str = "stop",
    tool_calls: list[dict[str, Any]] | None = None,
    logprobs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    body: dict[str, Any] = {
        "model": "qwen3.5:9b",
        "message": message,
        "done": True,
        "done_reason": done_reason,
        "total_duration": 3_000_000_000,
        "load_duration": 1_000_000_000,
        "prompt_eval_count": prompt,
        "eval_count": completion,
        "eval_duration": 2_000_000_000,
    }
    if logprobs is not None:
        body["logprobs"] = logprobs
    return body


def chat_response(content: str = "Hello", **kwargs: Any) -> Response:
    return Response(200, json=chat_body(content, **kwargs))


def stream_lines(
    pieces: list[str], *, prompt: int = 5, completion: int = 3, **extra: Any
) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = [
        {
            "model": "qwen3.5:9b",
            "message": {"role": "assistant", "content": piece},
            "done": False,
        }
        for piece in pieces
    ]
    final = chat_body("", prompt=prompt, completion=completion, **extra)
    lines.append(final)
    return lines


def ndjson(lines: list[dict[str, Any]]) -> Response:
    return Response(
        200, content="".join(json.dumps(line) + "\n" for line in lines).encode()
    )


async def hanging_stream(
    first: list[dict[str, Any]], closed: list[bool]
) -> AsyncIterator[bytes]:
    try:
        for line in first:
            yield (json.dumps(line) + "\n").encode()
        await asyncio.sleep(3600)
    finally:
        closed.append(True)
