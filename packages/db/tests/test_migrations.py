import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from db.engine import clear_caches

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def test_upgrade_head_creates_tables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "data" / "migrated.db"
    monkeypatch.setenv("LOCAL_LLM_DB_PATH", str(db_path))
    clear_caches()

    command.upgrade(Config(str(ALEMBIC_INI)), "head")

    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert tables == {
        "alembic_version",
        "chat_completion_records",
        "chat_completion_contents",
        "models",
    }
    clear_caches()
