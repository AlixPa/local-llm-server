import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import anyio
from db.models import StepStatus, TraceOutcome
from llm.client import (
    OllamaModelNotFoundError,
    OllamaServerError,
    OllamaUnreachableError,
)
from llm.schemas import OllamaChatChunk

from api.errors import ApiError
from api.observability.tracing import Trace


class Policy(StrEnum):
    HONOR = "honor"
    EMULATE = "emulate"
    IGNORE = "ignore"
    REJECT = "reject"


THINK_LEVELS: dict[str, bool | str] = {
    "none": False,
    "minimal": False,
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
    "max": "high",
}

OLLAMA_ERRORS = (OllamaUnreachableError, OllamaServerError, OllamaModelNotFoundError)


class ClientDisconnectedError(Exception):
    pass


def unsupported(param: str, detail: str = "") -> ApiError:
    message = f"Unsupported parameter: '{param}'."
    if detail:
        message = f"{message} {detail}"
    return ApiError(
        400, "invalid_request_error", "unsupported_parameter", param, message
    )


def model_not_found(model: str) -> ApiError:
    return ApiError(
        404,
        "invalid_request_error",
        "model_not_found",
        None,
        f"The model `{model}` does not exist or you do not have access to it.",
    )


def context_exceeded(num_ctx: int, param: str = "messages") -> ApiError:
    return ApiError(
        400,
        "invalid_request_error",
        "context_length_exceeded",
        param,
        f"This model's maximum context length is {num_ctx} tokens. However, your "
        f"{param} resulted in more tokens. Please reduce the length of the {param}.",
    )


def to_api_error(exc: Exception, model: str) -> ApiError:
    if isinstance(exc, OllamaModelNotFoundError):
        return model_not_found(model)
    if isinstance(exc, OllamaUnreachableError):
        return ApiError(
            503, "server_error", None, None, f"Ollama is unreachable: {exc}"
        )
    return ApiError(500, "server_error", None, None, f"Ollama error: {exc}")


# Ollama truncates an oversized prompt silently and then reports this exact count
def overflowed(chunk: OllamaChatChunk, num_ctx: int) -> bool:
    return chunk.prompt_eval_count == num_ctx // 2 + 2


def internal_error() -> ApiError:
    return ApiError(500, "server_error", None, None, "Internal server error")


def ms(nanoseconds: int | None) -> int | None:
    return None if nanoseconds is None else round(nanoseconds / 1_000_000)


@dataclass
class Totals:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    generation_ns: int = 0
    load_ns: int = 0

    def add(self, chunk: OllamaChatChunk) -> None:
        self.calls += 1
        self.prompt_tokens += chunk.prompt_eval_count or 0
        self.completion_tokens += chunk.eval_count or 0
        self.generation_ns += chunk.eval_duration or 0
        self.load_ns += chunk.load_duration or 0


async def race[T](
    work: Coroutine[Any, Any, T], is_disconnected: Callable[[], Awaitable[bool]]
) -> T:
    async def watch() -> None:
        # Starlette only exposes disconnects by polling
        while not await is_disconnected():  # noqa: ASYNC110
            await asyncio.sleep(0.1)

    task = asyncio.ensure_future(work)
    watcher = asyncio.ensure_future(watch())
    try:
        await asyncio.wait({task, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if not task.done():
            raise ClientDisconnectedError
        return task.result()
    finally:
        task.cancel()
        watcher.cancel()
        await asyncio.gather(task, watcher, return_exceptions=True)


async def record_shielded(record: Callable[[], Awaitable[None]]) -> None:
    # A cancelled request must still be persisted. The scope shield (unlike
    # asyncio.shield) survives the repeated cancellation anyio delivers on
    # client disconnect, so the session isn't closed under the insert.
    with anyio.CancelScope(shield=True):
        await record()


def close_open_steps(
    trace: Trace,
    status: StepStatus,
    message: str | None = None,
    content: Any = None,
) -> None:
    while trace.has_open_step:
        trace.step_received(content, status, message)
    if status is StepStatus.CANCELED:
        trace.set_outcome(TraceOutcome.CANCELED)


@dataclass(frozen=True)
class ToolChoice:
    mode: str | None = None
    function: str | None = None
    allowed: frozenset[str] | None = None
    allowed_required: bool = False


def _tool_name(tool: dict[str, Any]) -> str:
    return str(tool["function"]["name"])


def _restrict(
    tools: list[dict[str, Any]], names: set[str] | frozenset[str], param: str
) -> list[dict[str, Any]]:
    kept = [tool for tool in tools if _tool_name(tool) in names]
    if not kept:
        raise ApiError(
            400,
            "invalid_request_error",
            "invalid_value",
            param,
            f"Invalid {param}: none of the requested functions are in the tools.",
        )
    return kept


def apply_tool_choice(
    tools: list[dict[str, Any]], choice: ToolChoice
) -> tuple[list[dict[str, Any]], str | None]:
    required = "You must call one of the provided functions to respond."
    if not tools:
        return tools, None
    if choice.function is not None:
        return (
            _restrict(tools, {choice.function}, "tool_choice"),
            f"You must call the function `{choice.function}` to respond.",
        )
    if choice.allowed is not None:
        restricted = _restrict(tools, choice.allowed, "tool_choice")
        return restricted, required if choice.allowed_required else None
    match choice.mode:
        case "none":
            return [], None
        case "required":
            return tools, required
        case _:
            return tools, None
