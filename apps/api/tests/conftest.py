import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import uvicorn
import yaml
from api.app import app
from api.dependencies import get_ollama_client, get_session
from api.observability.tracing import writer
from db.engine import (
    clear_caches,
    get_async_engine,
    get_async_session_factory,
)
from db.models import Base, Model, TracedRequest, WorkflowStep
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response
from jsonschema import validate
from llm.client import OllamaClient
from llm.config import OllamaSettings
from ollama_fakes import OllamaMock
from openapi_core import Config, OpenAPI
from openapi_core.testing import MockRequest, MockResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

SPEC_PATH = Path(__file__).resolve().parents[3] / "openai-spec" / "openapi.yaml"


@pytest.fixture(autouse=True)
def settings_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[None]:
    monkeypatch.setenv("LOCAL_LLM_DB_PATH", str(tmp_path / "test.db"))
    clear_caches()
    yield
    clear_caches()


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        # Tables come from metadata, so the migration's seed row is absent
        session.add(
            Model(
                external_id="qwen3.5:9b",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                owned_by="qwen",
            )
        )
        await session.commit()
        yield session


@pytest.fixture
def ollama_mock() -> OllamaMock:
    return OllamaMock()


@pytest.fixture
def ollama_client(ollama_mock: OllamaMock) -> OllamaClient:
    async def handle(request: Request) -> Response:
        ollama_mock.requests.append(request)
        result = ollama_mock.handler(request)
        return result if isinstance(result, Response) else await result

    return OllamaClient(AsyncClient(transport=MockTransport(handle)), OllamaSettings())


@pytest.fixture
def test_app(session: AsyncSession, ollama_client: OllamaClient) -> Iterator[FastAPI]:
    async def override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_ollama_client] = lambda: ollama_client
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=test_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
async def trace_db() -> AsyncIterator[None]:
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await writer.stop()
    await engine.dispose()


@pytest.fixture
async def trace_writer(trace_db: None) -> AsyncIterator[None]:
    writer.start()
    yield


@pytest.fixture
def read_traces() -> Callable[
    [], Awaitable[list[tuple[TracedRequest, list[WorkflowStep]]]]
]:
    async def read() -> list[tuple[TracedRequest, list[WorkflowStep]]]:
        await writer.drain()
        async with get_async_session_factory()() as session:
            requests = (
                await session.execute(select(TracedRequest).order_by(TracedRequest.id))
            ).scalars()
            return [
                (
                    request,
                    list(
                        (
                            await session.execute(
                                select(WorkflowStep)
                                .where(WorkflowStep.request_id == request.id)
                                .order_by(WorkflowStep.position)
                            )
                        ).scalars()
                    ),
                )
                for request in list(requests)
            ]

    return read


@pytest.fixture
async def live_server(test_app: FastAPI, trace_db: None) -> AsyncIterator[str]:
    server = uvicorn.Server(
        uvicorn.Config(test_app, port=0, log_level="warning", lifespan="on")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:
        if task.done():
            task.result()
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task


def _normalize_spec(node: Any) -> Any:
    # The spec is OpenAPI 3.1, which dropped `nullable`, but OpenAI still uses it
    # (request schemas); rewrite to the 3.1 form so null is accepted as OpenAI does.
    if isinstance(node, list):
        return [_normalize_spec(item) for item in node]
    if not isinstance(node, dict):
        return node
    # Discriminators without a mapping point at schema names the spec doesn't have
    # (`user` vs ChatCompletionRequestUserMessage); plain oneOf matching still applies
    out = {
        key: _normalize_spec(value)
        for key, value in node.items()
        if key != "discriminator"
    }
    if out.pop("nullable", False) is not True:
        return out
    if isinstance(out.get("type"), str):
        out["type"] = [out["type"], "null"]
        if "enum" in out and None not in out["enum"]:
            out["enum"] = [*out["enum"], None]
        return out
    return {"anyOf": [out, {"type": "null"}]}


@pytest.fixture(scope="session")
def openai_spec() -> dict[str, Any]:
    loaded: dict[str, Any] = _normalize_spec(yaml.safe_load(SPEC_PATH.read_text()))
    # No auth on this server; paths are matched under our test base URL
    loaded.pop("security", None)
    loaded["servers"] = [{"url": "http://test/v1"}]
    return loaded


@pytest.fixture
def validate_schema(openai_spec: dict[str, Any]) -> Callable[[Any, str], None]:
    def _validate(body: Any, name: str) -> None:
        validate(
            body,
            {
                "$ref": f"#/components/schemas/{name}",
                "components": openai_spec["components"],
            },
        )

    return _validate


@pytest.fixture(scope="session")
def validate_contract(openai_spec: dict[str, Any]) -> Callable[[Response], None]:
    # The vendored spec is not strictly valid OpenAPI (e.g. a null default matching no
    # oneOf branch), so spec-level validation is skipped (None is documented but not
    # in the type stubs)
    openapi = OpenAPI.from_dict(
        openai_spec,
        config=Config(spec_validator_cls=None),  # type: ignore[arg-type]
    )

    def _validate(response: Response) -> None:
        request = response.request
        mock_request = MockRequest(
            "http://test",
            request.method.lower(),
            request.url.path,
            args=dict(request.url.params.multi_items()),
            headers=dict(request.headers),
            data=request.content,
            content_type=request.headers.get("content-type", "application/json"),
        )
        openapi.validate_request(mock_request)
        openapi.validate_response(
            mock_request,
            MockResponse(
                response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                content_type=response.headers.get("content-type", "application/json"),
            ),
        )

    return _validate
