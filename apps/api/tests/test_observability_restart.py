from datetime import UTC, datetime

from api.app import app
from db.engine import get_async_session_factory
from db.models import (
    Participant,
    StepKind,
    StepStatus,
    TracedRequest,
    TraceOutcome,
    WorkflowStep,
)
from db.repositories import tracing as repo
from httpx import AsyncClient
from ollama_fakes import OllamaMock, chat_response
from sqlalchemy import select

MINIMAL = {
    "model": "qwen3.5:9b",
    "messages": [{"role": "user", "content": "Hi"}],
}


def _step(position: int, status: StepStatus) -> repo.NewStep:
    return repo.NewStep(
        position=position,
        kind=StepKind.SENT_TO_OLLAMA,
        source=Participant.API,
        destination=Participant.OLLAMA,
        status=status,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


async def test_startup_marks_in_progress_rows_interrupted(trace_db: None) -> None:
    started = datetime(2026, 1, 1, tzinfo=UTC)
    async with get_async_session_factory()() as session:
        running = await repo.create_request(
            session, endpoint="/v1/chat/completions", method="POST", started_at=started
        )
        done = await repo.create_request(
            session, endpoint="/v1/chat/completions", method="POST", started_at=started
        )
        await repo.finish_request(
            session,
            done.id,
            outcome=TraceOutcome.SUCCESS,
            duration_ms=5,
            http_status=200,
            summary=None,
            response_id=None,
            error_message=None,
        )
        await repo.add_steps(
            session,
            running.id,
            [_step(0, StepStatus.COMPLETED), _step(1, StepStatus.IN_PROGRESS)],
        )
        await repo.add_steps(session, done.id, [_step(0, StepStatus.COMPLETED)])
        running_id, done_id = running.id, done.id

    async with app.router.lifespan_context(app):
        pass

    async with get_async_session_factory()() as session:
        requests = {
            row.id: row
            for row in (await session.execute(select(TracedRequest))).scalars()
        }
        steps = list(
            (
                await session.execute(
                    select(WorkflowStep).order_by(
                        WorkflowStep.request_id, WorkflowStep.position
                    )
                )
            ).scalars()
        )
    assert requests[running_id].outcome is TraceOutcome.INTERRUPTED
    assert requests[done_id].outcome is TraceOutcome.SUCCESS
    assert [(s.request_id, s.status) for s in steps] == [
        (running_id, StepStatus.COMPLETED),
        (running_id, StepStatus.INTERRUPTED),
        (done_id, StepStatus.COMPLETED),
    ]


async def test_shutdown_drains_pending_commands(
    client: AsyncClient, ollama_mock: OllamaMock, trace_db: None
) -> None:
    ollama_mock.handler = lambda _: chat_response("Hello")

    async with app.router.lifespan_context(app):
        await client.post("/v1/chat/completions", json=MINIMAL)

    async with get_async_session_factory()() as session:
        [request] = (await session.execute(select(TracedRequest))).scalars()
        steps = (await session.execute(select(WorkflowStep))).scalars().all()
    assert request.outcome is TraceOutcome.SUCCESS
    assert len(steps) == 4
