import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import anyio
from db.engine import get_async_session_factory
from db.models import (
    Participant,
    StepKind,
    StepStatus,
    TraceOutcome,
)
from db.repositories import tracing as tracing_repo
from db.repositories.tracing import NewStep
from pydantic_core import to_jsonable_python
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

TRACKED = frozenset({("POST", "/v1/chat/completions"), ("POST", "/v1/responses")})


@dataclass(frozen=True)
class TraceEvent:
    type: Literal["request.created", "request.updated"]
    id: int


class NotificationHub:
    def __init__(self) -> None:
        self._subscribers = set[asyncio.Queue[TraceEvent | None]]()
        self._closed = False

    def open(self) -> None:
        self._closed = False

    async def subscribe(self) -> AsyncGenerator[TraceEvent]:
        if self._closed:
            return
        queue = asyncio.Queue[TraceEvent | None]()
        self._subscribers.add(queue)
        try:
            while (event := await queue.get()) is not None:
                yield event
        finally:
            self._subscribers.discard(queue)

    def publish(self, event: TraceEvent) -> None:
        for queue in self._subscribers:
            queue.put_nowait(event)

    def close(self) -> None:
        self._closed = True
        for queue in self._subscribers:
            queue.put_nowait(None)


hub = NotificationHub()


@dataclass(frozen=True)
class _CreateRequest:
    trace: Trace
    endpoint: str
    method: str
    started_at: datetime


@dataclass(frozen=True)
class _UpdateRequest:
    trace: Trace
    summary: str | None
    response_id: str | None


@dataclass(frozen=True)
class _AddSteps:
    trace: Trace
    steps: list[NewStep]


@dataclass(frozen=True)
class _FinishStep:
    trace: Trace
    position: int
    status: StepStatus
    duration_ms: int
    content: Any
    error_message: str | None


@dataclass(frozen=True)
class _FinishRequest:
    trace: Trace
    outcome: TraceOutcome
    duration_ms: int
    http_status: int | None
    summary: str | None
    response_id: str | None
    error_message: str | None


type _Command = (
    _CreateRequest | _UpdateRequest | _AddSteps | _FinishStep | _FinishRequest
)


@dataclass
class _Rows:
    request_id: int
    step_ids: dict[int, int]


class TraceWriter:
    def __init__(self, notifications: NotificationHub) -> None:
        self._hub = notifications
        self._queue: asyncio.Queue[_Command | None] | None = None
        self._task: asyncio.Task[None] | None = None
        self._rows: dict[Trace, _Rows] = {}

    @property
    def running(self) -> bool:
        return self._queue is not None

    def start(self) -> None:
        queue = asyncio.Queue[_Command | None]()
        self._queue = queue
        self._task = asyncio.ensure_future(self._run(queue))

    async def stop(self) -> None:
        queue, task = self._queue, self._task
        self._queue = self._task = None
        if queue is None or task is None:
            return
        queue.put_nowait(None)
        await task

    async def drain(self) -> None:
        if self._queue is not None:
            await self._queue.join()

    def submit(self, command: _Command) -> None:
        # Not started (tests, shutdown): recording is simply off
        if self._queue is not None:
            self._queue.put_nowait(command)

    async def _run(self, queue: asyncio.Queue[_Command | None]) -> None:
        while (command := await queue.get()) is not None:
            try:
                await self._apply(command)
            except Exception:
                logger.exception("Failed to record trace command")
            finally:
                queue.task_done()
        self._rows.clear()

    async def _apply(self, command: _Command) -> None:
        async with get_async_session_factory()() as session:
            match command:
                case _CreateRequest():
                    request = await tracing_repo.create_request(
                        session,
                        endpoint=command.endpoint,
                        method=command.method,
                        started_at=command.started_at,
                    )
                    self._rows[command.trace] = _Rows(request.id, {})
                    self._hub.publish(TraceEvent("request.created", request.id))
                case _UpdateRequest():
                    if (rows := self._rows.get(command.trace)) is None:
                        return
                    await tracing_repo.update_request(
                        session,
                        rows.request_id,
                        summary=command.summary,
                        response_id=command.response_id,
                    )
                    self._hub.publish(TraceEvent("request.updated", rows.request_id))
                case _AddSteps():
                    if (rows := self._rows.get(command.trace)) is None:
                        return
                    ids = await tracing_repo.add_steps(
                        session, rows.request_id, command.steps
                    )
                    for step, step_id in zip(command.steps, ids, strict=True):
                        rows.step_ids[step.position] = step_id
                    self._hub.publish(TraceEvent("request.updated", rows.request_id))
                case _FinishStep():
                    if (rows := self._rows.get(command.trace)) is None:
                        return
                    if (known := rows.step_ids.get(command.position)) is None:
                        return
                    await tracing_repo.finish_step(
                        session,
                        known,
                        status=command.status,
                        duration_ms=command.duration_ms,
                        content=command.content,
                        error_message=command.error_message,
                    )
                    self._hub.publish(TraceEvent("request.updated", rows.request_id))
                case _FinishRequest():
                    if (rows := self._rows.pop(command.trace, None)) is None:
                        return
                    await tracing_repo.finish_request(
                        session,
                        rows.request_id,
                        outcome=command.outcome,
                        duration_ms=command.duration_ms,
                        http_status=command.http_status,
                        summary=command.summary,
                        response_id=command.response_id,
                        error_message=command.error_message,
                    )
                    self._hub.publish(TraceEvent("request.updated", rows.request_id))


writer = TraceWriter(hub)


def _jsonable(value: Any) -> Any:
    return to_jsonable_python(value, exclude_none=True)


def _now() -> datetime:
    return datetime.now(UTC)


class Trace:
    def __init__(self, sink: TraceWriter | None, endpoint: str, method: str) -> None:
        self._sink = sink
        self._started = time.monotonic()
        self._position = 0
        self._open = deque[tuple[int, float]]()
        self._closers = list[Callable[[], Awaitable[object]]]()
        self._finalized = False
        self.summary: str | None = None
        self.outcome: TraceOutcome | None = None
        self.response: Any = None
        self.response_id: str | None = None
        self.errors: list[str] = []
        if sink is not None:
            sink.submit(_CreateRequest(self, endpoint, method, _now()))

    @property
    def active(self) -> bool:
        return self._sink is not None and not self._finalized

    @property
    def has_open_step(self) -> bool:
        return bool(self._open)

    def elapsed_ms(self) -> int:
        return round((time.monotonic() - self._started) * 1000)

    def _enqueue_steps(self, steps: list[NewStep]) -> None:
        if self._sink is not None:
            self._sink.submit(_AddSteps(self, steps))

    def _next_position(self) -> int:
        position = self._position
        self._position += 1
        return position

    def add_step(
        self,
        kind: StepKind,
        source: Participant,
        destination: Participant,
        content: Any = None,
        *,
        status: StepStatus = StepStatus.COMPLETED,
        error_message: str | None = None,
    ) -> None:
        if not self.active:
            return
        try:
            step = NewStep(
                position=self._next_position(),
                kind=kind,
                source=source,
                destination=destination,
                status=status,
                started_at=_now(),
                content=_jsonable(content),
                error_message=error_message,
            )
            self._enqueue_steps([step])
        except Exception:
            logger.exception("Failed to record trace step")

    def step_sent(self, payload: Any) -> None:
        if not self.active:
            return
        try:
            started_at = _now()
            sent = NewStep(
                position=self._next_position(),
                kind=StepKind.SENT_TO_OLLAMA,
                source=Participant.API,
                destination=Participant.OLLAMA,
                status=StepStatus.COMPLETED,
                started_at=started_at,
                content=_jsonable(payload),
            )
            received = NewStep(
                position=self._next_position(),
                kind=StepKind.RECEIVED_FROM_OLLAMA,
                source=Participant.OLLAMA,
                destination=Participant.API,
                status=StepStatus.IN_PROGRESS,
                started_at=started_at,
            )
            self._open.append((received.position, time.monotonic()))
            self._enqueue_steps([sent, received])
        except Exception:
            logger.exception("Failed to record trace step")

    def step_received(
        self,
        content: Any,
        status: StepStatus = StepStatus.COMPLETED,
        error_message: str | None = None,
    ) -> None:
        if self._sink is None or not self._open:
            return
        try:
            position, started = self._open.popleft()
            self._sink.submit(
                _FinishStep(
                    self,
                    position,
                    status,
                    round((time.monotonic() - started) * 1000),
                    _jsonable(content),
                    error_message,
                )
            )
        except Exception:
            logger.exception("Failed to record trace step")

    def set_summary(self, summary: str) -> None:
        if not self.active:
            return
        self.summary = summary
        self._update(summary=summary)

    def set_outcome(self, outcome: TraceOutcome) -> None:
        if self.active:
            self.outcome = outcome

    def set_response(self, body: Any) -> None:
        if self.active:
            self.response = body

    def set_response_id(self, response_id: str) -> None:
        if not self.active:
            return
        self.response_id = response_id
        self._update(response_id=response_id)

    def add_error(self, message: str) -> None:
        if self.active:
            self.errors.append(message)

    def _update(
        self, *, summary: str | None = None, response_id: str | None = None
    ) -> None:
        if self._sink is not None:
            self._sink.submit(_UpdateRequest(self, summary, response_id))

    def add_closer(self, closer: Callable[[], Awaitable[object]]) -> None:
        if self.active:
            self._closers.append(closer)

    async def close(self) -> None:
        # Lets work that reports into the trace (a stream body that Starlette
        # abandoned suspended at a yield) finish before finalization
        closers, self._closers = self._closers, []
        with anyio.CancelScope(shield=True):
            for closer in reversed(closers):
                try:
                    await closer()
                except Exception:
                    logger.exception("Failed to close trace work")

    def finalize(self, *, http_status: int | None, response_body: bytes | None) -> None:
        if self._sink is None or self._finalized:
            return
        try:
            self._finalize(http_status, response_body)
        except Exception:
            logger.exception("Failed to finalize trace")
        finally:
            self._finalized = True
            self._open.clear()
            self._closers.clear()

    def _finalize(self, http_status: int | None, response_body: bytes | None) -> None:
        assert self._sink is not None
        body = _parse_json(response_body)
        failed_status = http_status is not None and http_status >= 400
        outcome = self.outcome
        if outcome is None:
            if http_status is None or failed_status:
                outcome = TraceOutcome.ERROR
            else:
                outcome = TraceOutcome.SUCCESS
        error_message: str | None = None
        while self._open:
            if outcome is TraceOutcome.CANCELED:
                self.step_received(None, StepStatus.CANCELED)
            else:
                self.step_received(
                    None,
                    StepStatus.FAILED,
                    "Request ended before the step completed",
                )
        if outcome is not TraceOutcome.CANCELED:
            if failed_status or self.errors:
                error_message = (
                    _envelope_message(body) if failed_status else None
                ) or "; ".join(self.errors)
                if not error_message:
                    error_message = f"HTTP {http_status}"
                content = (
                    body
                    if failed_status and body is not None
                    else {"message": error_message}
                )
                self.add_step(
                    StepKind.ERROR,
                    Participant.API,
                    Participant.CLIENT,
                    content,
                    error_message=error_message,
                )
            elif outcome is TraceOutcome.SUCCESS:
                self.add_step(
                    StepKind.RESPONSE_RETURNED,
                    Participant.API,
                    Participant.CLIENT,
                    self.response if self.response is not None else body,
                )
        self._sink.submit(
            _FinishRequest(
                self,
                outcome,
                self.elapsed_ms(),
                http_status,
                self.summary,
                self.response_id,
                error_message,
            )
        )


def _parse_json(raw: bytes | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _envelope_message(body: Any) -> str | None:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return str(error["message"])
    return None


_NOOP = Trace(None, "", "")
_current: ContextVar[Trace | None] = ContextVar("trace", default=None)


def get_trace() -> Trace:
    return _current.get() or _NOOP


class TracingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or (scope["method"], scope["path"]) not in TRACKED
            or not writer.running
        ):
            await self.app(scope, receive, send)
            return

        trace = Trace(writer, scope["path"], scope["method"])
        token = _current.set(trace)
        request_body = bytearray()
        request_recorded = False
        status: int | None = None
        capture_response = False
        response_body = bytearray()

        def record_request() -> None:
            nonlocal request_recorded
            if request_recorded:
                return
            request_recorded = True
            raw = bytes(request_body)
            try:
                content: Any = json.loads(raw)
            except ValueError:
                content = {"raw": raw.decode(errors="replace")}
            trace.add_step(
                StepKind.REQUEST_RECEIVED, Participant.CLIENT, Participant.API, content
            )

        async def traced_receive() -> Message:
            message = await receive()
            if message["type"] == "http.request" and not request_recorded:
                request_body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    record_request()
            return message

        async def traced_send(message: Message) -> None:
            nonlocal status, capture_response
            if message["type"] == "http.response.start":
                status = message["status"]
                content_type = dict(message.get("headers", [])).get(
                    b"content-type", b""
                )
                capture_response = content_type.startswith(b"application/json")
            elif message["type"] == "http.response.body" and capture_response:
                response_body.extend(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, traced_receive, traced_send)
        except asyncio.CancelledError:
            trace.set_outcome(TraceOutcome.CANCELED)
            raise
        except Exception:
            trace.set_outcome(TraceOutcome.ERROR)
            trace.add_error("Internal server error")
            if status is None:
                status = 500
            raise
        finally:
            record_request()
            await trace.close()
            _current.reset(token)
            trace.finalize(http_status=status, response_body=bytes(response_body))
