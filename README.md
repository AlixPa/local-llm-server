# local-llm-server

Prerequisites: [uv](https://docs.astral.sh/uv/) and Python 3.14. Run every command from the
repo root.

```sh
uv sync
cp .env.example .env
uv run pre-commit install
uv run alembic -c packages/db/alembic.ini upgrade head
uv run uvicorn api.app:app --reload
uv run pytest
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCAL_LLM_DB_PATH` | `data/local_llm.db` | SQLite file, relative to the working directory |
