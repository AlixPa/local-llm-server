import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from db.engine import clear_caches
from db.models import Model
from db.repositories.models import get_model, list_models
from sqlalchemy.ext.asyncio import AsyncSession

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


async def _add(session: AsyncSession, *external_ids: str) -> None:
    session.add_all(
        Model(
            external_id=external_id,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            owned_by="qwen",
        )
        for external_id in external_ids
    )
    await session.commit()


async def test_list_models(session: AsyncSession) -> None:
    await _add(session, "a:1b", "b:2b")

    models = await list_models(session)

    assert [m.external_id for m in models] == ["a:1b", "b:2b"]


async def test_get_model_hit_and_miss(session: AsyncSession) -> None:
    await _add(session, "a:1b")

    hit = await get_model(session, "a:1b")

    assert hit is not None
    assert hit.owned_by == "qwen"
    assert await get_model(session, "missing") is None


def test_migration_seeds_served_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "seeded.db"
    monkeypatch.setenv("LOCAL_LLM_DB_PATH", str(db_path))
    clear_caches()

    command.upgrade(Config(str(ALEMBIC_INI)), "head")

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT external_id, owned_by FROM models").fetchall()
    assert rows == [("qwen3.5:9b", "qwen")]
    clear_caches()
