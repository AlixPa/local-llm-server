import asyncio
import json
import re
from collections.abc import Awaitable, Callable

import httpx
from api.observability.tracing import Trace, get_trace, writer
from db.models import (
    Participant,
    StepKind,
    StepStatus,
    TracedRequest,
    TraceOutcome,
    WorkflowStep,
)
from httpx import AsyncClient, Request, Response
from ollama_fakes import (
    OllamaMock,
    chat_response,
    hanging_stream,
    ndjson,
    stream_lines,
)

MODEL = "qwen3.5:9b"
MINIMAL = {"model": MODEL, "messages": [{"role": "user", "content": "Hi"}]}
STREAM = {**MINIMAL, "stream": True}

type TraceRows = list[tuple[TracedRequest, list[WorkflowStep]]]
type ReadTraces = Callable[[], Awaitable[TraceRows]]


def _volatile(raw: bytes) -> bytes:
    return re.sub(rb'"(id|created)":\s*("[^"]*"|\d+)', rb'"\1":0', raw)


async def test_non_stream_success_records_four_steps(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    trace_writer: None,
    read_traces: ReadTraces,
) -> None:
    ollama_mock.handler = lambda _: chat_response("Hello there")

    response = await client.post("/v1/chat/completions", json=MINIMAL)

    [(request, steps)] = await read_traces()
    assert request.endpoint == "/v1/chat/completions"
    assert request.method == "POST"
    assert request.outcome is TraceOutcome.SUCCESS
    assert request.http_status == 200
    assert request.duration_ms is not None
    assert request.summary == f"{MODEL} · non-stream"
    assert request.response_id == response.json()["id"]
    assert request.error_message is None
    assert [(s.position, s.kind, s.source, s.destination) for s in steps] == [
        (0, StepKind.REQUEST_RECEIVED, Participant.CLIENT, Participant.API),
        (1, StepKind.SENT_TO_OLLAMA, Participant.API, Participant.OLLAMA),
        (2, StepKind.RECEIVED_FROM_OLLAMA, Participant.OLLAMA, Participant.API),
        (3, StepKind.RESPONSE_RETURNED, Participant.API, Participant.CLIENT),
    ]
    assert all(step.status is StepStatus.COMPLETED for step in steps)
    assert steps[0].content == MINIMAL
    assert steps[1].content["model"] == MODEL
    assert steps[2].content["message"]["content"] == "Hello there"
    assert steps[2].duration_ms is not None
    assert steps[3].content == response.json()


async def test_stream_success_records_assembled_content(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    trace_writer: None,
    read_traces: ReadTraces,
) -> None:
    ollama_mock.handler = lambda _: ndjson(stream_lines(["Hel", "lo"]))

    response = await client.post("/v1/chat/completions", json=STREAM)

    assert response.status_code == 200
    [(request, steps)] = await read_traces()
    assert request.outcome is TraceOutcome.SUCCESS
    assert request.summary == f"{MODEL} · stream"
    assert [s.kind for s in steps] == [
        StepKind.REQUEST_RECEIVED,
        StepKind.SENT_TO_OLLAMA,
        StepKind.RECEIVED_FROM_OLLAMA,
        StepKind.RESPONSE_RETURNED,
    ]
    assert steps[2].status is StepStatus.COMPLETED
    assert steps[2].content["choices"][0]["message"]["content"] == "Hello"
    assert steps[3].content["id"] == request.response_id


async def test_response_bytes_are_identical_with_tracing(
    client: AsyncClient, ollama_mock: OllamaMock, trace_db: None
) -> None:
    ollama_mock.handler = lambda _: chat_response("Hello")

    async def bodies() -> tuple[bytes, bytes]:
        plain = await client.post("/v1/chat/completions", json=MINIMAL)
        ollama_mock.handler = lambda _: ndjson(stream_lines(["a", "b"]))
        streamed = await client.post("/v1/chat/completions", json=STREAM)
        ollama_mock.handler = lambda _: chat_response("Hello")
        return plain.content, streamed.content

    untraced = await bodies()
    writer.start()
    traced = await bodies()

    assert _volatile(traced[0]) == _volatile(untraced[0])
    assert _volatile(traced[1]) == _volatile(untraced[1])


async def test_untracked_endpoints_create_no_rows(
    client: AsyncClient, trace_writer: None, read_traces: ReadTraces
) -> None:
    for path in ("/v1/models", "/v1/health", "/v1/analytics", "/v1/analytics/summary"):
        await client.get(path)
    await client.get("/v1/does-not-exist")

    assert await read_traces() == []


async def test_concurrent_requests_keep_their_own_steps(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    trace_writer: None,
    read_traces: ReadTraces,
) -> None:
    async def handler(request: Request) -> Response:
        prompt = json.loads(request.content)["messages"][-1]["content"]
        await asyncio.sleep(0.05 if prompt == "first" else 0.01)
        return chat_response(f"answer to {prompt}")

    ollama_mock.handler = handler

    def body(prompt: str) -> dict[str, object]:
        return {**MINIMAL, "messages": [{"role": "user", "content": prompt}]}

    await asyncio.gather(
        client.post("/v1/chat/completions", json=body("first")),
        client.post("/v1/chat/completions", json=body("second")),
    )

    rows = await read_traces()
    assert len(rows) == 2
    for _, steps in rows:
        assert [s.position for s in steps] == [0, 1, 2, 3]
        prompt = steps[0].content["messages"][0]["content"]
        assert steps[1].content["messages"][-1]["content"] == prompt
        assert steps[2].content["message"]["content"] == f"answer to {prompt}"
        assert f"answer to {prompt}" in json.dumps(steps[3].content)
    assert {steps[0].content["messages"][0]["content"] for _, steps in rows} == {
        "first",
        "second",
    }


async def test_live_server_stream_is_recorded(
    live_server: str,
    ollama_mock: OllamaMock,
    read_traces: ReadTraces,
) -> None:
    ollama_mock.handler = lambda _: ndjson(stream_lines(["Hel", "lo"]))

    async with httpx.AsyncClient(base_url=live_server) as http:
        response = await http.post("/v1/chat/completions", json=STREAM)
    assert response.text.endswith("data: [DONE]\n\n")

    rows: TraceRows = []
    for _ in range(100):
        rows = await read_traces()
        if rows and rows[0][0].outcome is not TraceOutcome.IN_PROGRESS:
            break
        await asyncio.sleep(0.02)
    [(request, steps)] = rows
    assert request.outcome is TraceOutcome.SUCCESS
    assert [s.kind for s in steps][-1] is StepKind.RESPONSE_RETURNED


async def _settled(read_traces: ReadTraces) -> TraceRows:
    rows: TraceRows = []
    for _ in range(150):
        rows = await read_traces()
        if rows and rows[0][0].outcome is not TraceOutcome.IN_PROGRESS:
            break
        await asyncio.sleep(0.02)
    return rows


async def test_live_server_disconnect_records_canceled_partial_stream(
    live_server: str,
    ollama_mock: OllamaMock,
    read_traces: ReadTraces,
) -> None:
    closed: list[bool] = []
    ollama_mock.handler = lambda _: Response(
        200, content=hanging_stream(stream_lines(["Hel"])[:-1], closed)
    )

    async with httpx.AsyncClient(base_url=live_server) as http:
        async with http.stream("POST", "/v1/chat/completions", json=STREAM) as resp:
            async for line in resp.aiter_lines():
                if "Hel" in line:
                    break

    [(request, steps)] = await _settled(read_traces)
    assert request.outcome is TraceOutcome.CANCELED
    assert request.summary == f"{MODEL} · stream"
    assert StepKind.RESPONSE_RETURNED not in [s.kind for s in steps]
    assert StepKind.ERROR not in [s.kind for s in steps]
    received = steps[-1]
    assert received.kind is StepKind.RECEIVED_FROM_OLLAMA
    assert received.status is StepStatus.CANCELED
    assert received.content["choices"][0]["message"]["content"] == "Hel"
    assert closed == [True]


async def test_stream_with_empty_content_returns_assembled_response(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    trace_writer: None,
    read_traces: ReadTraces,
) -> None:
    ollama_mock.handler = lambda _: ndjson(stream_lines([]))

    await client.post("/v1/chat/completions", json=STREAM)

    [(request, steps)] = await read_traces()
    assert request.outcome is TraceOutcome.SUCCESS
    assert steps[-1].kind is StepKind.RESPONSE_RETURNED
    assert steps[-1].content["choices"][0]["message"]["content"] == ""


async def test_summary_and_response_id_persist_before_finish(
    trace_writer: None, read_traces: ReadTraces
) -> None:
    trace = Trace(writer, "/v1/chat/completions", "POST")
    trace.set_summary("in flight")
    trace.set_response_id("chatcmpl-x")

    [(request, _)] = await read_traces()
    assert request.outcome is TraceOutcome.IN_PROGRESS
    assert request.summary == "in flight"
    assert request.response_id == "chatcmpl-x"
    trace.finalize(http_status=200, response_body=None)


async def test_finalize_closes_open_steps_and_late_calls_are_noops(
    trace_writer: None, read_traces: ReadTraces
) -> None:
    trace = Trace(writer, "/v1/chat/completions", "POST")
    trace.step_sent({"model": MODEL})
    trace.set_outcome(TraceOutcome.CANCELED)

    trace.finalize(http_status=200, response_body=None)
    trace.step_received({"late": True})
    trace.set_outcome(TraceOutcome.ERROR)
    trace.add_error("late")
    trace.add_step(StepKind.ERROR, Participant.API, Participant.CLIENT)
    trace.finalize(http_status=500, response_body=None)

    [(request, steps)] = await read_traces()
    assert request.outcome is TraceOutcome.CANCELED
    assert [s.kind for s in steps] == [
        StepKind.SENT_TO_OLLAMA,
        StepKind.RECEIVED_FROM_OLLAMA,
    ]
    assert steps[1].status is StepStatus.CANCELED


async def test_noop_trace_accumulates_nothing() -> None:
    trace = get_trace()
    trace.set_summary("x")
    trace.set_response_id("y")
    trace.set_response({"a": 1})
    trace.set_outcome(TraceOutcome.ERROR)
    trace.add_error("boom")
    trace.add_closer(lambda: asyncio.sleep(0))

    assert (trace.summary, trace.response_id, trace.response) == (None, None, None)
    assert trace.outcome is None
    assert trace.errors == []
    assert trace._closers == []
