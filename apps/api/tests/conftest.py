from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from api.app import app
from db.config import get_settings
from db.engine import get_session
from db.models import Base
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from jsonschema import validate
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
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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
        yield session


@pytest.fixture
def test_app(session: AsyncSession) -> Iterator[FastAPI]:
    async def override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=test_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture(scope="session")
def openai_spec() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(SPEC_PATH.read_text())
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
