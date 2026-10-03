from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from db.engine import clear_caches, get_sync_engine
from db.types import UtcDateTime
from sqlalchemy import Column, MetaData, Table, insert, select, text


def test_foreign_keys_are_enforced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCAL_LLM_DB_PATH", str(tmp_path / "fk.db"))
    clear_caches()
    with get_sync_engine().connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    clear_caches()


def test_utc_datetime_roundtrip_restores_timezone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCAL_LLM_DB_PATH", str(tmp_path / "dt.db"))
    clear_caches()
    table = Table("t", MetaData(), Column("at", UtcDateTime))
    local = datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=2)))
    with get_sync_engine().begin() as conn:
        table.create(conn)
        conn.execute(insert(table).values(at=local))
        stored = conn.execute(select(table.c.at)).scalar_one()
    assert stored == local
    assert stored.tzinfo == UTC
    clear_caches()


def test_utc_datetime_rejects_naive_values() -> None:
    with pytest.raises(ValueError):
        # the dialect is unused by process_bind_param
        UtcDateTime().process_bind_param(datetime(2026, 1, 1), None)  # type: ignore[arg-type]
