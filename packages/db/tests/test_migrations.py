import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from db.config import get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def test_upgrade_head_creates_empty_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "data" / "migrated.db"
    monkeypatch.setenv("LOCAL_LLM_DB_PATH", str(db_path))
    get_settings.cache_clear()

    command.upgrade(Config(str(ALEMBIC_INI)), "head")

    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert tables == {"alembic_version"}
    get_settings.cache_clear()
