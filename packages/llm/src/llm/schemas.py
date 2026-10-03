from typing import Any

from pydantic import BaseModel, ConfigDict


class _OllamaModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class OllamaToolCallFunction(_OllamaModel):
    name: str
    arguments: dict[str, Any] = {}


class OllamaToolCall(_OllamaModel):
    function: OllamaToolCallFunction


class OllamaMessage(_OllamaModel):
    role: str
    content: str = ""
    thinking: str | None = None
    images: list[str] | None = None
    tool_calls: list[OllamaToolCall] | None = None
    tool_name: str | None = None


class OllamaChatRequest(_OllamaModel):
    model: str
    messages: list[OllamaMessage]
    tools: list[dict[str, Any]] | None = None
    format: str | dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    stream: bool = False
    think: bool | str | None = None
    logprobs: bool | None = None
    top_logprobs: int | None = None


class OllamaTopLogprob(_OllamaModel):
    token: str
    logprob: float
    bytes: list[int] | None = None


class OllamaLogprob(OllamaTopLogprob):
    top_logprobs: list[OllamaTopLogprob] | None = None


# Durations are nanoseconds
class OllamaChatChunk(_OllamaModel):
    model: str | None = None
    message: OllamaMessage | None = None
    done: bool = False
    done_reason: str | None = None
    total_duration: int | None = None
    load_duration: int | None = None
    prompt_eval_count: int | None = None
    prompt_eval_duration: int | None = None
    eval_count: int | None = None
    eval_duration: int | None = None
    logprobs: list[OllamaLogprob] | None = None


class OllamaChatResponse(OllamaChatChunk):
    pass


class OllamaErrorBody(_OllamaModel):
    error: str
