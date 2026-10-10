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
from db.repositories import models as models_repo
from db.repositories import responses as responses_repo
from llm.client import OllamaClient, OllamaServerError
from llm.schemas import (
    OllamaChatChunk,
    OllamaChatRequest,
    OllamaLogprob,
    OllamaMessage,
    OllamaToolCall,
    OllamaToolCallFunction,
)
from sqlalchemy.ext.asyncio import AsyncSession

from api.errors import ApiError
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
from api.responses.schemas import (
    ContentPart,
    CreateResponse,
    EasyInputMessage,
    FunctionCallOutputItemParam,
    FunctionTool,
    FunctionToolCall,
    IncludeEnum,
    IncompleteDetails,
    InputImageContent,
    InputMessage,
    InputTextContent,
    LogProb,
    LogProbTop,
    OutputItem,
    OutputMessage,
    OutputTextContent,
    ReasoningItem,
    Response,
    ResponseCompletedEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseCreatedEvent,
    ResponseError,
    ResponseFailedEvent,
    ResponseFormatJsonObject,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseIncompleteEvent,
    ResponseInProgressEvent,
    ResponseLogProb,
    ResponseLogProbTop,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseStatus,
    ResponseStreamEvent,
    ResponseTextDeltaEvent,
    ResponseTextDoneEvent,
    ResponseUsage,
    TextResponseFormatJsonSchema,
    ToolChoiceAllowed,
    ToolChoiceFunction,
    ToolChoiceOptions,
    ToolChoiceParam,
)

logger = logging.getLogger(__name__)

# Every CreateResponse property must appear here (research.md R3)
FIELD_POLICY: dict[str, Policy] = {
    "model": Policy.HONOR,
    "input": Policy.HONOR,
    "instructions": Policy.HONOR,
    "stream": Policy.HONOR,
    "temperature": Policy.HONOR,
    "top_p": Policy.HONOR,
    "max_output_tokens": Policy.HONOR,
    "text": Policy.HONOR,
    "tools": Policy.HONOR,
    "reasoning": Policy.HONOR,
    "top_logprobs": Policy.HONOR,
    "include": Policy.HONOR,
    "truncation": Policy.HONOR,
    "tool_choice": Policy.EMULATE,
    "parallel_tool_calls": Policy.IGNORE,
    "max_tool_calls": Policy.IGNORE,
    "metadata": Policy.IGNORE,
    "store": Policy.IGNORE,
    "stream_options": Policy.IGNORE,
    "user": Policy.IGNORE,
    "safety_identifier": Policy.IGNORE,
    "service_tier": Policy.IGNORE,
    "prompt_cache_key": Policy.IGNORE,
    "prompt_cache_retention": Policy.IGNORE,
    "prompt_cache_options": Policy.IGNORE,
    "access_programs": Policy.IGNORE,
    "previous_response_id": Policy.REJECT,
    "conversation": Policy.REJECT,
    "background": Policy.REJECT,
    "prompt": Policy.REJECT,
    "context_management": Policy.REJECT,
    "moderation": Policy.REJECT,
}


@dataclass
class _OpenMessage:
    id: str
    index: int
    text: str = ""
    logprobs: list[LogProb] = field(default_factory=list[LogProb])


@dataclass
class _Run:
    request: CreateResponse
    stream: bool
    external_id: str = field(default_factory=lambda: f"resp_{secrets.token_hex(12)}")
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started: float = field(default_factory=time.monotonic)
    totals: Totals = field(default_factory=Totals)
    time_to_first_token_ms: int | None = None
    finish_reason: str | None = None
    items: list[OutputItem] = field(default_factory=list[OutputItem])
    open_message: _OpenMessage | None = None
    sequence: int = 0
    final: Response | None = None

    @property
    def model(self) -> str:
        return self.request.model or ""

    def elapsed_ms(self) -> int:
        return round((time.monotonic() - self.started) * 1000)

    def next_sequence(self) -> int:
        number = self.sequence
        self.sequence += 1
        return number


def _usage(totals: Totals) -> ResponseUsage:
    return ResponseUsage(
        input_tokens=totals.prompt_tokens,
        output_tokens=totals.completion_tokens,
        total_tokens=totals.prompt_tokens + totals.completion_tokens,
    )


def _echo_tool(tool: Any) -> dict[str, Any]:
    dumped: dict[str, Any] = tool.model_dump(mode="json", exclude_unset=True)
    return {"strict": None, "parameters": None, **dumped}


def _echo_tool_choice(choice: ToolChoiceParam | None) -> str | dict[str, Any]:
    match choice:
        case None:
            return "auto"
        case ToolChoiceOptions():
            return choice.value
        case _:
            return choice.model_dump(mode="json", exclude_unset=True)


def _response(
    run: _Run,
    status: ResponseStatus,
    output: list[OutputItem],
    *,
    error: ResponseError | None = None,
) -> Response:
    request = run.request
    done = status in (ResponseStatus.COMPLETED, ResponseStatus.INCOMPLETE)
    return Response(
        id=run.external_id,
        created_at=int(run.created_at.timestamp()),
        completed_at=int(time.time()) if done else None,
        status=status,
        model=run.model,
        output=output,
        usage=_usage(run.totals) if run.totals.calls else None,
        error=error,
        incomplete_details=(
            IncompleteDetails(reason="max_output_tokens")
            if status is ResponseStatus.INCOMPLETE
            else None
        ),
        instructions=request.instructions,
        metadata=request.metadata or {},
        tools=[_echo_tool(tool) for tool in request.tools or []],
        tool_choice=_echo_tool_choice(request.tool_choice),
        temperature=1.0 if request.temperature is None else request.temperature,
        top_p=1.0 if request.top_p is None else request.top_p,
        parallel_tool_calls=request.parallel_tool_calls is not False,
        max_output_tokens=request.max_output_tokens,
        text=(
            request.text.model_dump(mode="json", exclude_unset=True, by_alias=True)
            if request.text
            else {"format": {"type": "text"}}
        ),
        truncation=request.truncation or "disabled",
        reasoning=(
            request.reasoning.model_dump(mode="json", exclude_unset=True)
            if request.reasoning
            else None
        ),
        top_logprobs=request.top_logprobs,
    )


async def _record(
    session: AsyncSession,
    run: _Run,
    status: RequestStatus,
    *,
    response: dict[str, Any] | None,
    error: ApiError | None = None,
) -> None:
    called = run.totals.calls > 0
    await responses_repo.create_response(
        session,
        external_id=run.external_id,
        created_at=run.created_at,
        model=run.model,
        status=status,
        stream=run.stream,
        prompt_tokens=run.totals.prompt_tokens if called else None,
        completion_tokens=run.totals.completion_tokens if called else None,
        duration_ms=run.elapsed_ms(),
        time_to_first_token_ms=run.time_to_first_token_ms,
        generation_duration_ms=ms(run.totals.generation_ns) if called else None,
        load_duration_ms=ms(run.totals.load_ns) if called else None,
        finish_reason=run.finish_reason,
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
    trace.set_summary(f"{run.model} · {mode}")
    trace.set_response_id(run.external_id)


def _image_payload(part: InputImageContent) -> str:
    header, _, payload = (part.image_url or "").partition(",")
    if not (header.startswith("data:") and header.endswith(";base64")):
        raise unsupported("input", "Only base64 data: URLs are supported for images.")
    return payload


def _message(role: str, content: str | list[ContentPart]) -> OllamaMessage:
    role = "system" if role == "developer" else role
    if isinstance(content, str):
        return OllamaMessage(role=role, content=content)
    texts: list[str] = []
    images: list[str] = []
    for part in content:
        match part:
            case InputTextContent() | OutputTextContent():
                texts.append(part.text)
            case InputImageContent():
                images.append(_image_payload(part))
            case _:
                raise unsupported(
                    "input", f"Content part type '{part.type}' is not supported."
                )
    return OllamaMessage(role=role, content="\n".join(texts), images=images or None)


def _tool_arguments(arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_output(output: str | list[dict[str, Any]]) -> str:
    if isinstance(output, str):
        return output
    texts: list[str] = []
    for part in output:
        if part.get("type") != "input_text":
            raise unsupported("input", "Only text tool outputs are supported.")
        texts.append(str(part.get("text", "")))
    return "\n".join(texts)


def _translate_input(request: CreateResponse) -> list[OllamaMessage]:
    items = request.input
    if items is None:
        return []
    if isinstance(items, str):
        return [OllamaMessage(role="user", content=items)]
    tool_names: dict[str, str] = {}
    out: list[OllamaMessage] = []
    for item in items:
        match item:
            case EasyInputMessage() | InputMessage() | OutputMessage():
                out.append(_message(item.role, item.content))
            case FunctionToolCall():
                tool_names[item.call_id] = item.name
                call = OllamaToolCall(
                    function=OllamaToolCallFunction(
                        name=item.name, arguments=_tool_arguments(item.arguments)
                    )
                )
                if out and out[-1].role == "assistant":
                    out[-1].tool_calls = [*(out[-1].tool_calls or []), call]
                else:
                    out.append(
                        OllamaMessage(role="assistant", content="", tool_calls=[call])
                    )
            case FunctionCallOutputItemParam():
                out.append(
                    OllamaMessage(
                        role="tool",
                        content=_tool_output(item.output),
                        tool_name=tool_names.get(item.call_id or ""),
                    )
                )
            case ReasoningItem():
                continue
            case _:
                raise unsupported(
                    "input", f"Input item type '{item.type}' is not supported."
                )
    return out


def _reject_unsupported(request: CreateResponse) -> None:
    if not request.model:
        raise ApiError(
            400,
            "invalid_request_error",
            "missing_required_parameter",
            "model",
            "Missing required parameter: 'model'.",
        )
    for name, policy in FIELD_POLICY.items():
        if policy is Policy.REJECT and getattr(request, name):
            raise unsupported(name)


def _tools(request: CreateResponse) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for tool in request.tools or []:
        if not isinstance(tool, FunctionTool):
            raise unsupported("tools", f"Tool type '{tool.type}' is not supported.")
        tools.append(
            {
                "type": "function",
                "function": tool.model_dump(
                    exclude_none=True, exclude={"type", "strict"}
                ),
            }
        )
    return tools


def _apply_tool_choice(
    request: CreateResponse, tools: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str | None]:
    choice = request.tool_choice
    match choice:
        case None:
            normalized = ToolChoice()
        case ToolChoiceOptions():
            normalized = ToolChoice(mode=choice.value)
        case ToolChoiceFunction():
            normalized = ToolChoice(function=choice.name)
        case ToolChoiceAllowed():
            raise unsupported("tool_choice", "allowed_tools is not supported.")
        case _:
            raise unsupported(
                "tool_choice", f"Tool choice type '{choice.type}' is not supported."
            )
    return apply_tool_choice(tools, normalized)


def _options(request: CreateResponse, num_ctx: int) -> dict[str, Any]:
    options: dict[str, Any] = {"num_ctx": num_ctx}
    candidates: dict[str, Any] = {
        "temperature": request.temperature,
        "top_p": request.top_p,
        "num_predict": request.max_output_tokens,
    }
    options.update({k: v for k, v in candidates.items() if v is not None})
    return options


def _format(request: CreateResponse) -> str | dict[str, Any] | None:
    fmt = request.text.format if request.text else None
    if isinstance(fmt, ResponseFormatJsonObject):
        return "json"
    if isinstance(fmt, TextResponseFormatJsonSchema):
        return fmt.schema_ or "json"
    return None


def _wants_logprobs(request: CreateResponse) -> bool:
    return IncludeEnum.MESSAGE_OUTPUT_TEXT_LOGPROBS in (request.include or [])


@dataclass(frozen=True)
class _Prepared:
    ollama: OllamaChatRequest
    num_ctx: int
    check_overflow: bool
    logprobs: bool


async def _prepare(
    request: CreateResponse, session: AsyncSession, num_ctx: int
) -> _Prepared:
    _reject_unsupported(request)
    messages = _translate_input(request)
    tools, instruction = _apply_tool_choice(request, _tools(request))
    if await models_repo.get_model(session, request.model or "") is None:
        raise model_not_found(request.model or "")
    if request.instructions:
        messages.insert(0, OllamaMessage(role="system", content=request.instructions))
    if instruction:
        if messages and messages[0].role == "system":
            messages[0].content = f"{messages[0].content}\n\n{instruction}"
        else:
            messages.insert(0, OllamaMessage(role="system", content=instruction))
    effort = request.reasoning.effort if request.reasoning else None
    wants_logprobs = _wants_logprobs(request)
    return _Prepared(
        ollama=OllamaChatRequest(
            model=request.model or "",
            messages=messages,
            tools=tools or None,
            format=_format(request),
            options=_options(request, num_ctx),
            think=THINK_LEVELS[effort.value] if effort else False,
            logprobs=True if wants_logprobs else None,
            top_logprobs=request.top_logprobs if wants_logprobs else None,
        ),
        num_ctx=num_ctx,
        check_overflow=request.truncation != "auto",
        logprobs=wants_logprobs,
    )


def _tool_call(call: OllamaToolCall) -> FunctionToolCall:
    return FunctionToolCall(
        id=f"fc_{secrets.token_hex(12)}",
        call_id=f"call_{secrets.token_hex(12)}",
        name=call.function.name,
        arguments=json.dumps(call.function.arguments),
        status=ResponseStatus.COMPLETED,
    )


def _logprobs(items: list[OllamaLogprob] | None, *, wanted: bool) -> list[LogProb]:
    if not wanted or items is None:
        return []
    return [
        LogProb(
            token=item.token,
            logprob=item.logprob,
            bytes=item.bytes or [],
            top_logprobs=[
                LogProbTop(token=top.token, logprob=top.logprob, bytes=top.bytes or [])
                for top in item.top_logprobs or []
            ],
        )
        for item in items
    ]


def _event_logprobs(logprobs: list[LogProb]) -> list[ResponseLogProb]:
    return [
        ResponseLogProb(
            token=item.token,
            logprob=item.logprob,
            top_logprobs=[
                ResponseLogProbTop(token=top.token, logprob=top.logprob)
                for top in item.top_logprobs
            ],
        )
        for item in logprobs
    ]


def _message_item(
    message_id: str,
    text: str,
    logprobs: list[LogProb],
    status: ResponseStatus,
) -> OutputMessage:
    parts: list[ContentPart] = [
        OutputTextContent(
            type="output_text", text=text, annotations=[], logprobs=logprobs
        )
    ]
    return OutputMessage(
        id=message_id, type="message", role="assistant", content=parts, status=status
    )


def _finish(chunk: OllamaChatChunk, run: _Run) -> ResponseStatus:
    length = chunk.done_reason == "length"
    has_call = any(isinstance(item, FunctionToolCall) for item in run.items)
    if has_call:
        run.finish_reason = "tool_calls"
    else:
        run.finish_reason = "length" if length else "stop"
    return ResponseStatus.INCOMPLETE if length else ResponseStatus.COMPLETED


async def create_response(
    request: CreateResponse,
    *,
    session: AsyncSession,
    ollama: OllamaClient,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> Response:
    run = _Run(request, stream=False)
    trace = get_trace()
    _begin_trace(trace, run)
    failed = RequestStatus.FAILED
    try:
        prepared = await _prepare(request, session, ollama.num_ctx)
        trace.step_sent(prepared.ollama)
        result = await race(ollama.chat(prepared.ollama), is_disconnected)
        trace.step_received(result)
        run.totals.add(result)
        if prepared.check_overflow and overflowed(result, prepared.num_ctx):
            raise context_exceeded(prepared.num_ctx, "input")
        message = result.message
        calls = [
            _tool_call(call) for call in (message.tool_calls if message else None) or []
        ]
        run.items.extend(calls)
        status = _finish(result, run)
        text = message.content if message else ""
        output: list[OutputItem] = []
        if text or not calls:
            output.append(
                _message_item(
                    f"msg_{secrets.token_hex(12)}",
                    text,
                    _logprobs(result.logprobs, wanted=prepared.logprobs),
                    ResponseStatus.INCOMPLETE
                    if status is ResponseStatus.INCOMPLETE
                    else ResponseStatus.COMPLETED,
                )
            )
        output.extend(calls)
        body = _response(run, status, output)
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
        error = to_api_error(exc, run.model)
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
        response=body.model_dump(mode="json"),
    )
    return body


async def start_stream(
    request: CreateResponse,
    *,
    session: AsyncSession,
    ollama: OllamaClient,
) -> AsyncGenerator[ResponseStreamEvent]:
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
        error = to_api_error(exc, run.model)
        close_open_steps(trace, StepStatus.FAILED, error.message)
        await _record(session, run, failed, response=None, error=error)
        raise error from exc
    except Exception:
        close_open_steps(trace, StepStatus.FAILED, "Internal server error")
        await _record(session, run, failed, response=None, error=internal_error())
        raise
    body = _stream_body(run, prepared, session, _chain(first, upstream))
    trace.add_closer(body.aclose)
    return body


async def _chain(
    first: OllamaChatChunk, rest: AsyncGenerator[OllamaChatChunk]
) -> AsyncGenerator[OllamaChatChunk]:
    yield first
    async for chunk in rest:
        yield chunk


def _open_message(run: _Run) -> list[ResponseStreamEvent]:
    message = _OpenMessage(id=f"msg_{secrets.token_hex(12)}", index=len(run.items))
    run.open_message = message
    return [
        ResponseOutputItemAddedEvent(
            output_index=message.index,
            item=OutputMessage(
                id=message.id, content=[], status=ResponseStatus.IN_PROGRESS
            ),
            sequence_number=run.next_sequence(),
        ),
        ResponseContentPartAddedEvent(
            item_id=message.id,
            output_index=message.index,
            content_index=0,
            part=OutputTextContent(type="output_text", text=""),
            sequence_number=run.next_sequence(),
        ),
    ]


def _close_message(run: _Run, status: ResponseStatus) -> list[ResponseStreamEvent]:
    message = run.open_message
    if message is None:
        return []
    run.open_message = None
    item = _message_item(message.id, message.text, message.logprobs, status)
    run.items.append(item)
    return [
        ResponseTextDoneEvent(
            item_id=message.id,
            output_index=message.index,
            content_index=0,
            text=message.text,
            logprobs=_event_logprobs(message.logprobs),
            sequence_number=run.next_sequence(),
        ),
        ResponseContentPartDoneEvent(
            item_id=message.id,
            output_index=message.index,
            content_index=0,
            part=OutputTextContent(
                type="output_text",
                text=message.text,
                annotations=[],
                logprobs=message.logprobs,
            ),
            sequence_number=run.next_sequence(),
        ),
        ResponseOutputItemDoneEvent(
            output_index=message.index, item=item, sequence_number=run.next_sequence()
        ),
    ]


def _call_events(run: _Run, call: FunctionToolCall) -> list[ResponseStreamEvent]:
    index = len(run.items)
    item_id = call.id or ""
    run.items.append(call)
    return [
        ResponseOutputItemAddedEvent(
            output_index=index,
            item=call.model_copy(
                update={"arguments": "", "status": ResponseStatus.IN_PROGRESS}
            ),
            sequence_number=run.next_sequence(),
        ),
        ResponseFunctionCallArgumentsDeltaEvent(
            item_id=item_id,
            output_index=index,
            delta=call.arguments,
            sequence_number=run.next_sequence(),
        ),
        ResponseFunctionCallArgumentsDoneEvent(
            item_id=item_id,
            output_index=index,
            arguments=call.arguments,
            sequence_number=run.next_sequence(),
        ),
        ResponseOutputItemDoneEvent(
            output_index=index, item=call, sequence_number=run.next_sequence()
        ),
    ]


def _partial(
    run: _Run, status: ResponseStatus, error: ResponseError | None = None
) -> Response | None:
    output = list(run.items)
    open_message = run.open_message
    if open_message is not None:
        output.append(
            _message_item(
                open_message.id,
                open_message.text,
                open_message.logprobs,
                ResponseStatus.INCOMPLETE,
            )
        )
    if not output and run.totals.calls == 0:
        return None
    return _response(run, status, output, error=error)


async def _stream_body(
    run: _Run,
    prepared: _Prepared,
    session: AsyncSession,
    chunks: AsyncGenerator[OllamaChatChunk],
) -> AsyncGenerator[ResponseStreamEvent]:
    status = RequestStatus.CANCELLED
    error: ApiError | None = None
    failure: Response | None = None
    trace = get_trace()
    try:
        async with aclosing(chunks):
            yield ResponseCreatedEvent(
                response=_response(run, ResponseStatus.IN_PROGRESS, []),
                sequence_number=run.next_sequence(),
            )
            yield ResponseInProgressEvent(
                response=_response(run, ResponseStatus.IN_PROGRESS, []),
                sequence_number=run.next_sequence(),
            )
            final_status: ResponseStatus | None = None
            async for item in chunks:
                message = item.message
                content = message.content if message else ""
                if content or (item.logprobs and prepared.logprobs):
                    if run.open_message is None:
                        for event in _open_message(run):
                            yield event
                    open_message = run.open_message
                    assert open_message is not None
                    logprobs = _logprobs(item.logprobs, wanted=prepared.logprobs)
                    open_message.text += content
                    open_message.logprobs.extend(logprobs)
                    yield ResponseTextDeltaEvent(
                        item_id=open_message.id,
                        output_index=open_message.index,
                        content_index=0,
                        delta=content,
                        logprobs=_event_logprobs(logprobs),
                        sequence_number=run.next_sequence(),
                    )
                for call in (message.tool_calls if message else None) or []:
                    for event in _close_message(run, ResponseStatus.COMPLETED):
                        yield event
                    for event in _call_events(run, _tool_call(call)):
                        yield event
                if item.done:
                    run.totals.add(item)
                    if prepared.check_overflow and overflowed(item, prepared.num_ctx):
                        raise context_exceeded(prepared.num_ctx, "input")
                    final_status = _finish(item, run)
            if final_status is None:
                raise OllamaServerError("Ollama stream ended before completion")
            message_status = (
                ResponseStatus.INCOMPLETE
                if final_status is ResponseStatus.INCOMPLETE
                else ResponseStatus.COMPLETED
            )
            if run.open_message is None and not run.items:
                for event in _open_message(run):
                    yield event
            for event in _close_message(run, message_status):
                yield event
            run.final = _response(run, final_status, run.items)
            trace.step_received(run.final.model_dump(mode="json"))
            if final_status is ResponseStatus.INCOMPLETE:
                yield ResponseIncompleteEvent(
                    response=run.final, sequence_number=run.next_sequence()
                )
            else:
                yield ResponseCompletedEvent(
                    response=run.final, sequence_number=run.next_sequence()
                )
        status = RequestStatus.SUCCEEDED
    except ApiError as exc:
        status, error = RequestStatus.FAILED, exc
        failure = _failure(run, exc)
        yield ResponseFailedEvent(response=failure, sequence_number=run.next_sequence())
    except OLLAMA_ERRORS as exc:
        status, error = RequestStatus.FAILED, to_api_error(exc, run.model)
        failure = _failure(run, error)
        yield ResponseFailedEvent(response=failure, sequence_number=run.next_sequence())
    except Exception:
        logger.exception("Unexpected error while streaming response")
        status, error = RequestStatus.FAILED, internal_error()
        failure = _failure(run, error)
        yield ResponseFailedEvent(response=failure, sequence_number=run.next_sequence())
    finally:
        recorded: Response | None = None
        match status:
            case RequestStatus.SUCCEEDED:
                recorded = run.final
                trace.set_response(
                    run.final.model_dump(mode="json") if run.final else None
                )
            case RequestStatus.FAILED:
                recorded = failure
                message_text = error.message if error else "Internal server error"
                close_open_steps(
                    trace, StepStatus.FAILED, message_text, _dump(recorded)
                )
                trace.add_error(message_text)
                trace.set_outcome(TraceOutcome.ERROR)
            case RequestStatus.CANCELLED:
                recorded = _partial(run, ResponseStatus.CANCELLED)
                close_open_steps(trace, StepStatus.CANCELED, None, _dump(recorded))
                trace.set_outcome(TraceOutcome.CANCELED)
        await _record_shielded(
            session, run, status, response=_dump(recorded), error=error
        )


def _failure(run: _Run, error: ApiError) -> Response:
    detail = ResponseError(code="server_error", message=error.message)
    return _partial(run, ResponseStatus.FAILED, detail) or _response(
        run, ResponseStatus.FAILED, [], error=detail
    )


def _dump(response: Response | None) -> dict[str, Any] | None:
    return response.model_dump(mode="json") if response else None
