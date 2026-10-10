import asyncio
import json
import logging
import secrets
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import anyio
from db.models import RequestStatus, StepStatus, TraceOutcome
from db.repositories import chat_completions as chat_completions_repo
from db.repositories import models as models_repo
from llm.client import (
    OllamaClient,
    OllamaServerError,
)
from llm.schemas import (
    OllamaChatChunk,
    OllamaChatRequest,
    OllamaChatResponse,
    OllamaLogprob,
    OllamaMessage,
    OllamaToolCall,
    OllamaToolCallFunction,
)
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.schemas import (
    ChatCompletionAllowedToolsChoice,
    ChatCompletionMessageToolCall,
    ChatCompletionMessageToolCallChunk,
    ChatCompletionMessageToolCallChunkFunction,
    ChatCompletionMessageToolCallFunction,
    ChatCompletionMessageToolCalls,
    ChatCompletionNamedToolChoice,
    ChatCompletionNamedToolChoiceCustom,
    ChatCompletionRequestAssistantMessage,
    ChatCompletionRequestDeveloperMessage,
    ChatCompletionRequestFunctionMessage,
    ChatCompletionRequestMessageContentPartAudio,
    ChatCompletionRequestMessageContentPartFile,
    ChatCompletionRequestMessageContentPartImage,
    ChatCompletionRequestMessageContentPartText,
    ChatCompletionRequestSystemMessage,
    ChatCompletionRequestToolMessage,
    ChatCompletionRequestUserMessage,
    ChatCompletionResponseMessage,
    ChatCompletionStreamError,
    ChatCompletionStreamResponseDelta,
    ChatCompletionTokenLogprob,
    ChatCompletionTokenTopLogprob,
    ChatCompletionTool,
    ChoiceLogprobs,
    CompletionUsage,
    CreateChatCompletionRequest,
    CreateChatCompletionResponse,
    CreateChatCompletionResponseChoice,
    CreateChatCompletionStreamResponse,
    CreateChatCompletionStreamResponseChoice,
    CustomToolChatCompletions,
    FinishReason,
    FunctionCallMode,
    ResponseFormatJsonObject,
    ResponseFormatJsonSchema,
    ResponseModality,
    ToolChoiceMode,
)
from api.errors import ApiError, Error
from api.inference import (
    OLLAMA_ERRORS,
    THINK_LEVELS,
    ClientDisconnectedError,
    Policy,
    ToolChoice,
    Totals,
    apply_tool_choice,
    close_open_steps,
    context_exceeded,
    internal_error,
    model_not_found,
    ms,
    overflowed,
    race,
    record_shielded,
    to_api_error,
    unsupported,
)
from api.observability.tracing import Trace, get_trace

logger = logging.getLogger(__name__)


# Every CreateChatCompletionRequest property must appear here (research.md R5)
FIELD_POLICY: dict[str, Policy] = {
    "messages": Policy.HONOR,
    "model": Policy.HONOR,
    "stream": Policy.HONOR,
    "stream_options": Policy.HONOR,
    "temperature": Policy.HONOR,
    "top_p": Policy.HONOR,
    "seed": Policy.HONOR,
    "max_tokens": Policy.HONOR,
    "max_completion_tokens": Policy.HONOR,
    "stop": Policy.HONOR,
    "frequency_penalty": Policy.HONOR,
    "presence_penalty": Policy.HONOR,
    "response_format": Policy.HONOR,
    "tools": Policy.HONOR,
    "functions": Policy.HONOR,
    "function_call": Policy.HONOR,
    "tool_choice": Policy.EMULATE,
    "logprobs": Policy.HONOR,
    "top_logprobs": Policy.HONOR,
    "n": Policy.EMULATE,
    "reasoning_effort": Policy.HONOR,
    "modalities": Policy.HONOR,
    "logit_bias": Policy.REJECT,
    "audio": Policy.REJECT,
    "web_search_options": Policy.REJECT,
    "moderation": Policy.REJECT,
    "parallel_tool_calls": Policy.IGNORE,
    "verbosity": Policy.IGNORE,
    "prediction": Policy.IGNORE,
    "metadata": Policy.IGNORE,
    "store": Policy.IGNORE,
    "user": Policy.IGNORE,
    "safety_identifier": Policy.IGNORE,
    "service_tier": Policy.IGNORE,
    "prompt_cache_key": Policy.IGNORE,
    "prompt_cache_retention": Policy.IGNORE,
    "prompt_cache_options": Policy.IGNORE,
}

type StreamEvent = CreateChatCompletionStreamResponse | ChatCompletionStreamError


def _usage(totals: Totals) -> CompletionUsage:
    return CompletionUsage(
        prompt_tokens=totals.prompt_tokens,
        completion_tokens=totals.completion_tokens,
        total_tokens=totals.prompt_tokens + totals.completion_tokens,
    )


@dataclass
class _Run:
    request: CreateChatCompletionRequest
    stream: bool
    external_id: str = field(
        default_factory=lambda: f"chatcmpl-{secrets.token_hex(12)}"
    )
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started: float = field(default_factory=time.monotonic)
    totals: Totals = field(default_factory=Totals)
    time_to_first_token_ms: int | None = None
    finish_reasons: dict[int, FinishReason] = field(
        default_factory=dict[int, FinishReason]
    )
    contents: dict[int, str] = field(default_factory=dict[int, str])
    tool_calls: dict[int, ChatCompletionMessageToolCalls] = field(
        default_factory=dict[int, ChatCompletionMessageToolCalls]
    )

    @property
    def n(self) -> int:
        return self.request.n or 1

    def elapsed_ms(self) -> int:
        return round((time.monotonic() - self.started) * 1000)

    def streamed_response(self) -> dict[str, Any]:
        choices = [
            CreateChatCompletionResponseChoice(
                index=index,
                message=ChatCompletionResponseMessage(
                    role="assistant",
                    content=self.contents.get(index, ""),
                    tool_calls=self.tool_calls.get(index) or None,
                ),
                logprobs=None,
                finish_reason=self.finish_reasons.get(index, FinishReason.STOP),
            )
            for index in sorted(self.contents)
        ]
        return CreateChatCompletionResponse(
            id=self.external_id,
            object="chat.completion",
            created=int(self.created_at.timestamp()),
            model=self.request.model,
            choices=choices,
            usage=_usage(self.totals),
        ).model_dump(mode="json", exclude_unset=True)


async def _record(
    session: AsyncSession,
    run: _Run,
    status: RequestStatus,
    *,
    response: dict[str, Any] | None,
    error: ApiError | None = None,
) -> None:
    called = run.totals.calls > 0
    await chat_completions_repo.create_chat_completion(
        session,
        external_id=run.external_id,
        created_at=run.created_at,
        model=run.request.model,
        status=status,
        stream=run.stream,
        n=run.n,
        prompt_tokens=run.totals.prompt_tokens if called else None,
        completion_tokens=run.totals.completion_tokens if called else None,
        duration_ms=run.elapsed_ms(),
        time_to_first_token_ms=run.time_to_first_token_ms,
        generation_duration_ms=ms(run.totals.generation_ns) if called else None,
        load_duration_ms=ms(run.totals.load_ns) if called else None,
        finish_reason=run.finish_reasons.get(0),
        error_type=error.type if error else None,
        error_code=error.code if error else None,
        request=run.request.model_dump(mode="json", exclude_unset=True, by_alias=True),
        response=response,
        error_message=error.message if error else None,
    )


async def _record_shielded(
    session: AsyncSession,
    run: _Run,
    status: RequestStatus,
    *,
    response: dict[str, Any] | None,
    error: ApiError | None = None,
) -> None:
    await record_shielded(
        lambda: _record(session, run, status, response=response, error=error)
    )


def _begin_trace(trace: Trace, run: _Run) -> None:
    mode = "stream" if run.stream else "non-stream"
    trace.set_summary(f"{run.request.model} · {mode}")
    trace.set_response_id(run.external_id)


def _text(content: str | list[ChatCompletionRequestMessageContentPartText]) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(part.text for part in content)


def _image_payload(url: str) -> str:
    header, _, payload = url.partition(",")
    if not (header.startswith("data:") and header.endswith(";base64")):
        raise unsupported(
            "messages", "Only base64 data: URLs are supported for images."
        )
    return payload


def _tool_arguments(arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _translate_messages(request: CreateChatCompletionRequest) -> list[OllamaMessage]:
    tool_names: dict[str, str] = {}
    out: list[OllamaMessage] = []
    for message in request.messages:
        match message:
            case (
                ChatCompletionRequestDeveloperMessage()
                | ChatCompletionRequestSystemMessage()
            ):
                out.append(OllamaMessage(role="system", content=_text(message.content)))
            case ChatCompletionRequestUserMessage():
                if isinstance(message.content, str):
                    out.append(OllamaMessage(role="user", content=message.content))
                    continue
                texts: list[str] = []
                images: list[str] = []
                for part in message.content:
                    match part:
                        case ChatCompletionRequestMessageContentPartText():
                            texts.append(part.text)
                        case ChatCompletionRequestMessageContentPartImage():
                            images.append(_image_payload(part.image_url.url))
                        case ChatCompletionRequestMessageContentPartAudio():
                            raise unsupported(
                                "messages", "input_audio is not supported."
                            )
                        case ChatCompletionRequestMessageContentPartFile():
                            raise unsupported(
                                "messages", "file parts are not supported."
                            )
                out.append(
                    OllamaMessage(
                        role="user", content="\n".join(texts), images=images or None
                    )
                )
            case ChatCompletionRequestAssistantMessage():
                calls: list[OllamaToolCall] = []
                for call in message.tool_calls or []:
                    if isinstance(call, ChatCompletionMessageToolCall):
                        tool_names[call.id] = call.function.name
                        calls.append(
                            OllamaToolCall(
                                function=OllamaToolCallFunction(
                                    name=call.function.name,
                                    arguments=_tool_arguments(call.function.arguments),
                                )
                            )
                        )
                    else:
                        raise unsupported(
                            "messages", "custom tool calls are not supported."
                        )
                if message.function_call:
                    calls.append(
                        OllamaToolCall(
                            function=OllamaToolCallFunction(
                                name=message.function_call.name,
                                arguments=_tool_arguments(
                                    message.function_call.arguments
                                ),
                            )
                        )
                    )
                content = message.content
                if isinstance(content, list):
                    content = "\n".join(
                        part.text
                        for part in content
                        if isinstance(part, ChatCompletionRequestMessageContentPartText)
                    )
                out.append(
                    OllamaMessage(
                        role="assistant",
                        content=content or "",
                        tool_calls=calls or None,
                    )
                )
            case ChatCompletionRequestToolMessage():
                out.append(
                    OllamaMessage(
                        role="tool",
                        content=_text(message.content),
                        tool_name=tool_names.get(message.tool_call_id),
                    )
                )
            case ChatCompletionRequestFunctionMessage():
                out.append(
                    OllamaMessage(
                        role="tool",
                        content=message.content or "",
                        tool_name=message.name,
                    )
                )
    return out


def _reject_unsupported(request: CreateChatCompletionRequest) -> None:
    if request.logit_bias:
        raise unsupported("logit_bias")
    if request.audio is not None:
        raise unsupported("audio")
    if request.web_search_options is not None:
        raise unsupported("web_search_options")
    if request.moderation is not None:
        raise unsupported("moderation")
    if request.modalities and ResponseModality.AUDIO in request.modalities:
        raise unsupported("modalities", "Audio output is not supported.")
    if any(isinstance(tool, CustomToolChatCompletions) for tool in request.tools or []):
        raise unsupported("tools", "Custom tools are not supported.")
    if isinstance(request.tool_choice, ChatCompletionNamedToolChoiceCustom):
        raise unsupported("tool_choice", "Custom tools are not supported.")


def _tools(request: CreateChatCompletionRequest) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for tool in request.tools or []:
        if isinstance(tool, ChatCompletionTool):
            tools.append(
                {
                    "type": "function",
                    "function": tool.function.model_dump(
                        exclude_none=True, exclude={"strict"}
                    ),
                }
            )
    for function in request.functions or []:
        tools.append(
            {"type": "function", "function": function.model_dump(exclude_none=True)}
        )
    return tools


def _apply_tool_choice(
    request: CreateChatCompletionRequest,
    tools: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    # tool_choice wins over the legacy function_call
    choice = request.tool_choice
    if choice is None and request.function_call is not None:
        legacy = request.function_call
        if isinstance(legacy, FunctionCallMode):
            choice = ToolChoiceMode(legacy.value)
        else:
            choice = ChatCompletionNamedToolChoice.model_validate(
                {"type": "function", "function": {"name": legacy.name}}
            )
    normalized = ToolChoice()
    if isinstance(choice, ChatCompletionNamedToolChoice):
        normalized = ToolChoice(function=choice.function.name)
    elif isinstance(choice, ChatCompletionAllowedToolsChoice):
        normalized = ToolChoice(
            allowed=frozenset(
                str(entry.get("function", {}).get("name"))
                for entry in choice.allowed_tools.tools
            ),
            allowed_required=choice.allowed_tools.mode == "required",
        )
    elif isinstance(choice, ToolChoiceMode):
        normalized = ToolChoice(mode=choice.value)
    return apply_tool_choice(tools, normalized)


def _options(request: CreateChatCompletionRequest, num_ctx: int) -> dict[str, Any]:
    options: dict[str, Any] = {"num_ctx": num_ctx}
    stop = [request.stop] if isinstance(request.stop, str) else request.stop
    num_predict = (
        request.max_completion_tokens
        if request.max_completion_tokens is not None
        else request.max_tokens
    )
    candidates: dict[str, Any] = {
        "temperature": request.temperature,
        "top_p": request.top_p,
        "seed": request.seed,
        "frequency_penalty": request.frequency_penalty,
        "presence_penalty": request.presence_penalty,
        "stop": stop,
        "num_predict": num_predict,
    }
    options.update({k: v for k, v in candidates.items() if v is not None})
    return options


def _format(request: CreateChatCompletionRequest) -> str | dict[str, Any] | None:
    fmt = request.response_format
    if isinstance(fmt, ResponseFormatJsonObject):
        return "json"
    if isinstance(fmt, ResponseFormatJsonSchema):
        return fmt.json_schema.schema_ or "json"
    return None


@dataclass(frozen=True)
class _Prepared:
    ollama: OllamaChatRequest
    n: int
    include_usage: bool
    num_ctx: int


async def _prepare(
    request: CreateChatCompletionRequest, session: AsyncSession, num_ctx: int
) -> _Prepared:
    _reject_unsupported(request)
    messages = _translate_messages(request)
    tools, instruction = _apply_tool_choice(request, _tools(request))
    if await models_repo.get_model(session, request.model) is None:
        raise model_not_found(request.model)
    if instruction:
        if messages and messages[0].role == "system":
            messages[0].content = f"{messages[0].content}\n\n{instruction}"
        else:
            messages.insert(0, OllamaMessage(role="system", content=instruction))
    effort = request.reasoning_effort
    return _Prepared(
        ollama=OllamaChatRequest(
            model=request.model,
            messages=messages,
            tools=tools or None,
            format=_format(request),
            options=_options(request, num_ctx),
            think=THINK_LEVELS[effort] if effort else False,
            logprobs=True if request.logprobs else None,
            top_logprobs=request.top_logprobs if request.logprobs else None,
        ),
        n=request.n or 1,
        include_usage=bool(
            request.stream_options and request.stream_options.include_usage
        ),
        num_ctx=num_ctx,
    )


def _tool_call(call: OllamaToolCall) -> ChatCompletionMessageToolCall:
    return ChatCompletionMessageToolCall(
        id=f"call_{secrets.token_hex(12)}",
        type="function",
        function=ChatCompletionMessageToolCallFunction(
            name=call.function.name, arguments=json.dumps(call.function.arguments)
        ),
    )


def _finish_reason(chunk: OllamaChatChunk, *, tool_calls: bool) -> FinishReason:
    if tool_calls:
        return FinishReason.TOOL_CALLS
    return FinishReason.LENGTH if chunk.done_reason == "length" else FinishReason.STOP


def _logprobs(
    items: list[OllamaLogprob] | None, *, wanted: bool
) -> ChoiceLogprobs | None:
    if not wanted or items is None:
        return None
    return ChoiceLogprobs(
        content=[
            ChatCompletionTokenLogprob(
                token=item.token,
                logprob=item.logprob,
                bytes=item.bytes,
                top_logprobs=[
                    ChatCompletionTokenTopLogprob(
                        token=top.token, logprob=top.logprob, bytes=top.bytes
                    )
                    for top in item.top_logprobs or []
                ],
            )
            for item in items
        ],
        refusal=None,
    )


async def _generate_all(
    ollama: OllamaClient, prepared: _Prepared
) -> list[OllamaChatResponse]:
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(ollama.chat(prepared.ollama))
                for _ in range(prepared.n)
            ]
    except ExceptionGroup as group_error:
        raise group_error.exceptions[0] from None
    return [task.result() for task in tasks]


def _build_response(
    run: _Run, responses: list[OllamaChatResponse]
) -> CreateChatCompletionResponse:
    choices: list[CreateChatCompletionResponseChoice] = []
    for index, response in enumerate(responses):
        message = response.message
        calls: ChatCompletionMessageToolCalls = [
            _tool_call(call) for call in (message.tool_calls if message else None) or []
        ]
        finish = _finish_reason(response, tool_calls=bool(calls))
        run.finish_reasons[index] = finish
        choices.append(
            CreateChatCompletionResponseChoice(
                index=index,
                message=ChatCompletionResponseMessage(
                    role="assistant",
                    content=message.content if message else "",
                    tool_calls=calls or None,
                ),
                logprobs=_logprobs(
                    response.logprobs, wanted=bool(run.request.logprobs)
                ),
                finish_reason=finish,
            )
        )
    return CreateChatCompletionResponse(
        id=run.external_id,
        object="chat.completion",
        created=int(run.created_at.timestamp()),
        model=run.request.model,
        choices=choices,
        usage=_usage(run.totals),
    )


async def create_chat_completion(
    request: CreateChatCompletionRequest,
    *,
    session: AsyncSession,
    ollama: OllamaClient,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> CreateChatCompletionResponse:
    run = _Run(request, stream=False)
    trace = get_trace()
    _begin_trace(trace, run)
    failed = RequestStatus.FAILED
    try:
        prepared = await _prepare(request, session, ollama.num_ctx)
        for _ in range(prepared.n):
            trace.step_sent(prepared.ollama)
        responses = await race(_generate_all(ollama, prepared), is_disconnected)
        for response in responses:
            trace.step_received(response)
            run.totals.add(response)
        if any(overflowed(response, prepared.num_ctx) for response in responses):
            raise context_exceeded(prepared.num_ctx)
        body = _build_response(run, responses)
    except ClientDisconnectedError:
        close_open_steps(trace, StepStatus.CANCELED)
        await _record(session, run, RequestStatus.CANCELLED, response=None)
        raise ApiError(
            499, "invalid_request_error", None, None, "Client closed the request."
        ) from None
    except asyncio.CancelledError:
        close_open_steps(trace, StepStatus.CANCELED)
        await _record_shielded(session, run, RequestStatus.CANCELLED, response=None)
        raise
    except ApiError as exc:
        close_open_steps(trace, StepStatus.FAILED, exc.message)
        await _record(session, run, failed, response=None, error=exc)
        raise
    except OLLAMA_ERRORS as exc:
        error = to_api_error(exc, request.model)
        close_open_steps(trace, StepStatus.FAILED, error.message)
        await _record(session, run, failed, response=None, error=error)
        raise error from exc
    except Exception:
        close_open_steps(trace, StepStatus.FAILED, "Internal server error")
        await _record(session, run, failed, response=None, error=internal_error())
        raise
    await _record(
        session,
        run,
        RequestStatus.SUCCEEDED,
        response=body.model_dump(mode="json", exclude_unset=True),
    )
    return body


async def _chain(
    first: OllamaChatChunk, rest: AsyncGenerator[OllamaChatChunk]
) -> AsyncGenerator[OllamaChatChunk]:
    yield first
    async for chunk in rest:
        yield chunk


async def start_stream(
    request: CreateChatCompletionRequest,
    *,
    session: AsyncSession,
    ollama: OllamaClient,
) -> AsyncGenerator[StreamEvent]:
    run = _Run(request, stream=True)
    trace = get_trace()
    _begin_trace(trace, run)
    failed = RequestStatus.FAILED
    upstream: AsyncGenerator[OllamaChatChunk] | None = None
    try:
        prepared = await _prepare(request, session, ollama.num_ctx)
        trace.step_sent(prepared.ollama)
        upstream = ollama.chat_stream(prepared.ollama)
        first = await anext(upstream)
        run.time_to_first_token_ms = run.elapsed_ms()
    except asyncio.CancelledError:
        close_open_steps(trace, StepStatus.CANCELED)
        with anyio.CancelScope(shield=True):
            if upstream is not None:
                await upstream.aclose()
        await _record_shielded(session, run, RequestStatus.CANCELLED, response=None)
        raise
    except StopAsyncIteration:
        error = ApiError(500, "server_error", None, None, "Ollama returned no data.")
        close_open_steps(trace, StepStatus.FAILED, error.message)
        await _record(session, run, failed, response=None, error=error)
        raise error from None
    except ApiError as exc:
        close_open_steps(trace, StepStatus.FAILED, exc.message)
        await _record(session, run, failed, response=None, error=exc)
        raise
    except OLLAMA_ERRORS as exc:
        error = to_api_error(exc, request.model)
        close_open_steps(trace, StepStatus.FAILED, error.message)
        await _record(session, run, failed, response=None, error=error)
        raise error from exc
    except Exception:
        close_open_steps(trace, StepStatus.FAILED, "Internal server error")
        await _record(session, run, failed, response=None, error=internal_error())
        raise
    body = _stream_body(run, prepared, ollama, session, _chain(first, upstream))
    trace.add_closer(body.aclose)
    return body


def _chunk(
    run: _Run,
    index: int,
    delta: ChatCompletionStreamResponseDelta,
    *,
    finish_reason: FinishReason | None = None,
    logprobs: ChoiceLogprobs | None = None,
) -> CreateChatCompletionStreamResponse:
    return CreateChatCompletionStreamResponse(
        id=run.external_id,
        object="chat.completion.chunk",
        created=int(run.created_at.timestamp()),
        model=run.request.model,
        choices=[
            CreateChatCompletionStreamResponseChoice(
                index=index,
                delta=delta,
                logprobs=logprobs,
                finish_reason=finish_reason,
            )
        ],
    )


async def _stream_body(
    run: _Run,
    prepared: _Prepared,
    ollama: OllamaClient,
    session: AsyncSession,
    first_choice: AsyncGenerator[OllamaChatChunk],
) -> AsyncGenerator[StreamEvent]:
    status = RequestStatus.CANCELLED
    error: ApiError | None = None
    wants_logprobs = bool(run.request.logprobs)
    trace = get_trace()
    try:
        for index in range(prepared.n):
            if index > 0:
                trace.step_sent(prepared.ollama)
            chunks = first_choice if index == 0 else ollama.chat_stream(prepared.ollama)
            run.contents[index] = ""
            run.tool_calls[index] = []
            finished = False
            async with aclosing(chunks):
                yield _chunk(
                    run,
                    index,
                    ChatCompletionStreamResponseDelta(role="assistant", content=""),
                )
                async for item in chunks:
                    message = item.message
                    content = message.content if message else ""
                    if content or (item.logprobs and wants_logprobs):
                        run.contents[index] += content
                        yield _chunk(
                            run,
                            index,
                            ChatCompletionStreamResponseDelta(content=content),
                            logprobs=_logprobs(item.logprobs, wanted=wants_logprobs),
                        )
                    for call in (message.tool_calls if message else None) or []:
                        full = _tool_call(call)
                        run.tool_calls[index].append(full)
                        yield _chunk(
                            run,
                            index,
                            ChatCompletionStreamResponseDelta(
                                tool_calls=[
                                    ChatCompletionMessageToolCallChunk(
                                        index=len(run.tool_calls[index]) - 1,
                                        id=full.id,
                                        type="function",
                                        function=ChatCompletionMessageToolCallChunkFunction(
                                            name=full.function.name,
                                            arguments=full.function.arguments,
                                        ),
                                    )
                                ]
                            ),
                        )
                    if item.done:
                        finished = True
                        run.totals.add(item)
                        if overflowed(item, prepared.num_ctx):
                            raise context_exceeded(prepared.num_ctx)
                        finish = _finish_reason(
                            item, tool_calls=bool(run.tool_calls[index])
                        )
                        run.finish_reasons[index] = finish
                        yield _chunk(
                            run,
                            index,
                            ChatCompletionStreamResponseDelta(),
                            finish_reason=finish,
                        )
            if not finished:
                raise OllamaServerError("Ollama stream ended before completion")
            trace.step_received(run.streamed_response())
        if prepared.include_usage:
            yield CreateChatCompletionStreamResponse(
                id=run.external_id,
                object="chat.completion.chunk",
                created=int(run.created_at.timestamp()),
                model=run.request.model,
                choices=[],
                usage=_usage(run.totals),
            )
        status = RequestStatus.SUCCEEDED
    except ApiError as exc:
        status, error = RequestStatus.FAILED, exc
        yield _error_event(exc)
    except OLLAMA_ERRORS as exc:
        status, error = (
            RequestStatus.FAILED,
            to_api_error(exc, run.request.model),
        )
        yield _error_event(error)
    except Exception:
        logger.exception("Unexpected error while streaming chat completion")
        status, error = RequestStatus.FAILED, internal_error()
        yield _error_event(error)
    finally:
        partial = run.streamed_response() if run.contents else None
        match status:
            case RequestStatus.SUCCEEDED:
                trace.set_response(run.streamed_response())
            case RequestStatus.FAILED:
                failure = error.message if error else "Internal server error"
                close_open_steps(trace, StepStatus.FAILED, failure, partial)
                trace.add_error(failure)
                trace.set_outcome(TraceOutcome.ERROR)
            case RequestStatus.CANCELLED:
                close_open_steps(trace, StepStatus.CANCELED, None, partial)
                trace.set_outcome(TraceOutcome.CANCELED)
        await _record_shielded(
            session,
            run,
            status,
            response=partial,
            error=error,
        )


def _error_event(error: ApiError) -> ChatCompletionStreamError:
    return ChatCompletionStreamError(
        error=Error(
            message=error.message, type=error.type, param=error.param, code=error.code
        )
    )
